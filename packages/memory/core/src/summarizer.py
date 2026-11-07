"""用户画像提取 — 从对话中提炼用户事实

客服场景不需要日记归档（PG messages 表已有原始记录）。
只需要从对话中提取用户画像，供下次对话注入 prompt。
"""
from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from agent_platform_plugin_sdk import ServiceClosedError

from .experience import ExperienceMemory

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """你是一个用户画像提取器。从对话中提取关于用户的持久事实。

## 提取原则
只提取**跨会话有用的信息**，忽略单次对话才会用到的内容：
- 用户身份：称呼、角色、级别
- 偏好：喜欢什么格式/风格、不喜欢什么
- 历史：之前遇到过什么问题、怎么解决的
- 习惯：常问什么类型的问题
- 其他持久事实

## 不要提取
- 本次对话的具体问题（如"退款什么时候到账"）
- 本次对话的临时状态（如"等待用户确认"）
- 客服已解决的一次性事项

## 如果对话中没有新的持久事实
回复 SKIP

## 输出格式
如果提取到新事实，输出 JSON：
{"facts": ["事实1", "事实2", ...]}"""

MERGE_PROMPT = """## 已有画像
{existing}

## 新提取
{new_facts}

合并去重，输出最终画像（JSON）：
{"facts": ["合并后的事实1", "事实2", ...]}

规则：
- 已有事实和新事实重复 → 保留一条
- 已有事实被新事实更新 → 用新的替代
- 新事实补充已有 → 追加
- 总计不超过 20 条"""


class ProfileExtractor:
    """用户画像提取器"""

    def __init__(self, experience: ExperienceMemory):
        self._experience = experience
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def extract(
        self,
        llm,
        messages: list,
        tenant_id: int,
        user_id: str,
    ) -> list[str] | None:
        """从对话中提取用户事实，合并到画像表。返回更新后的事实列表。"""
        if self._closed:
            raise ServiceClosedError("memory service is closed")
        history = self._render(messages)
        if not history.strip():
            return None

        # Step 1: 提取新事实
        try:
            response = await llm.ainvoke([
                SystemMessage(content=EXTRACT_PROMPT),
                HumanMessage(content=history),
            ])
            text = response.content.strip()
        except Exception as e:
            logger.warning(f"提取失败: {e}")
            return None

        if text.startswith("SKIP") or len(text) < 10:
            return None

        # 解析 JSON
        new_facts = self._parse_facts(text)
        if not new_facts:
            return None

        # Step 2: 与已有画像合并
        existing = self._experience.get_profile(tenant_id, user_id)
        if existing:
            merged = await self._merge(llm, existing, new_facts)
        else:
            merged = new_facts

        # Step 3: 写 PG
        self._experience.save_profile(tenant_id, user_id, merged)
        logger.info(f"画像更新: tenant={tenant_id} user={user_id} facts={len(merged)}")
        return merged

    def schedule(self, llm, messages: list, tenant_id: int, user_id: str):
        if self._closed:
            raise ServiceClosedError("memory service is closed")
        task = asyncio.create_task(self.extract(llm, list(messages), tenant_id, user_id))
        self._tasks.add(task)
        task.add_done_callback(self._finish)
        return task

    def _finish(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("画像提取任务失败", exc_info=error)

    async def aclose(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── 内部 ──

    _ROLE_MAP: dict[str, str] = {"human": "customer", "ai": "agent", "tool": "tool", "system": "system"}

    @classmethod
    def _role(cls, msg) -> str:
        raw = ""
        if hasattr(msg, 'type'):    raw = msg.type
        elif hasattr(msg, 'role'):  raw = msg.role
        elif hasattr(msg, 'get'):   raw = msg.get('role', '')
        return cls._ROLE_MAP.get(raw, raw)

    @classmethod
    def _content(cls, msg) -> str:
        if hasattr(msg, 'content'): return msg.content or ''
        if hasattr(msg, 'get'): return msg.get('content', '')
        return ''

    @classmethod
    def _render(cls, messages: list) -> str:
        lines: list[str] = []
        for msg in messages:
            role = cls._role(msg)
            content = cls._content(msg)
            if role in ('tool', 'function'):
                lines.append(f"[工具] {content[:300]}")
            elif role == 'system':
                continue
            else:
                speaker = "用户" if role == "customer" else "客服"
                lines.append(f"{speaker}：{content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_facts(text: str) -> list[str]:
        try:
            data = json.loads(text)
            return data.get("facts", [])
        except json.JSONDecodeError:
            # 尝试提取 ```json ... ``` 块
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0]
                return ProfileExtractor._parse_facts(text)
            return []

    async def _merge(self, llm, existing: list[str], new_facts: list[str]) -> list[str]:
        try:
            response = await llm.ainvoke([
                SystemMessage(content=MERGE_PROMPT),
                HumanMessage(content=MERGE_PROMPT.format(
                    existing=json.dumps(existing, ensure_ascii=False),
                    new_facts=json.dumps(new_facts, ensure_ascii=False),
                )),
            ])
            return self._parse_facts(response.content.strip()) or existing + new_facts
        except Exception:
            # 降级：直接追加去重
            merged = list(dict.fromkeys(existing + new_facts))
            return merged[:20]
