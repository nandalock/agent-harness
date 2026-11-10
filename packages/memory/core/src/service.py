"""Runtime-owned memory services and the read-only debug pipeline."""
import asyncio
import json
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from agent_platform_session import Session
from agent_platform_session.events import CONTEXT_CHECKPOINT

from .admission import estimate_tokens, latest_memory, summarize
from .compressor import MemoryCompressor
from .config import MemoryConfig
from .context import MemoryContext
from .experience import ExperienceMemory
from .models import DebugRunRequest
from .session import SessionMemory
from .summarizer import EXTRACT_PROMPT, ProfileExtractor

logger = logging.getLogger(__name__)


class MemoryConversationNotFound(LookupError):
    pass


class MemoryRequestError(ValueError):
    pass


class MemoryService:
    def __init__(self, database, agents, chat_store, *, notes, sessions=None, persistence=None, llm=None):
        self.config = MemoryConfig(database)
        self.experience = ExperienceMemory(database)
        self._extractor = ProfileExtractor(self.experience)
        self._agents = agents
        self._chat = chat_store
        self._database = database
        self._notes = notes
        self._sessions = sessions
        self._persistence = persistence
        self._llm = llm

    async def list_agents(self) -> list[dict]:
        return [{"agent_key": item["agent_key"], "name": item.get("name") or item["agent_key"]}
                for item in await self._agents.list_definitions()]

    async def agent_memory(self, tenant_id: int, agent_key: str, content: str | None = None) -> dict:
        if await self._agents.get_definition(agent_key) is None:
            raise MemoryConversationNotFound("智能体不存在")
        return {"markdown": await self._note(tenant_id, "agent", agent_key, content)}

    def _session_owner(self, tenant_id: int, session_id: str) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT agent_key FROM conversations WHERE tenant_id = %s AND session_id = %s "
                    "ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1",
                    (tenant_id, session_id),
                )
                row = cur.fetchone()
        if row is None:
            raise MemoryConversationNotFound("会话不存在")
        return row

    async def session_memory(self, tenant_id: int, session_id: str, content: str | None = None) -> dict:
        owner = await asyncio.to_thread(self._session_owner, tenant_id, session_id)
        markdown = await self._note(tenant_id, "session", session_id, content)
        session = await self._load_session(session_id)
        checkpoint, usage = latest_memory(session.events if session else [])
        return {"agent_key": owner["agent_key"], "markdown": markdown,
                "summary": checkpoint.get("summary", ""), "usage": usage}

    async def _load_session(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id) if self._sessions is not None else None
        if session is not None or self._persistence is None:
            return session
        loaded = await asyncio.to_thread(self._persistence.load, session_id)
        return Session.from_events(*loaded) if loaded else None

    async def draft_session_notes(self, tenant_id: int, session_id: str) -> dict:
        owner = await asyncio.to_thread(self._session_owner, tenant_id, session_id)
        session = await self._load_session(session_id)
        if session is None or self._llm is None or not owner["agent_key"]:
            raise MemoryRequestError("当前会话缺少对话或模型配置")
        config = await self._agents.get_config(owner["agent_key"]) or {}
        model = self._llm.resolve(config)
        if not model.configured:
            raise MemoryRequestError("请先为当前智能体配置模型")
        checkpoint, _ = latest_memory(session.events)
        lines = []
        used = 0
        for event in reversed(session.surface.events):
            if event.type == CONTEXT_CHECKPOINT:
                continue
            message = session.derive_event_message(event)
            if message is None:
                continue
            content = message.get("content") or ""
            line = f"[{message['role']}] {str(content)[:1600]}"
            used += estimate_tokens(line)
            if used > 3200:
                break
            lines.append(line)
        if not lines:
            raise MemoryRequestError("当前会话没有可总结的消息")
        try:
            draft = await summarize(self._llm.create_client(model, max_llm_retries=0), model.model,
                                    "\n".join(reversed(lines)), checkpoint.get("summary", ""),
                                    max_tokens=768, timeout=25.0)
        except Exception as exc:
            logger.exception("Could not generate session notes")
            raise MemoryRequestError("生成笔记失败，请稍后重试") from exc
        if not draft:
            raise MemoryRequestError("模型未返回完整的笔记草稿")
        return {"markdown": draft[:6000]}

    async def _note(self, tenant_id: int, scope: str, identity: str, content: str | None) -> str:
        if content is None:
            return await asyncio.to_thread(self._notes.read, tenant_id, scope, identity)
        await asyncio.to_thread(self._notes.write, tenant_id, scope, identity, content)
        return content

    def create_context(self) -> MemoryContext:
        return MemoryContext(config=self.config, summarizer=self._extractor, experience=self.experience)

    async def aclose(self) -> None:
        await self._extractor.aclose()

    async def debug_run(self, body: DebugRunRequest, tenant_id: int) -> dict:
        """预览压缩和画像提取，返回调试页面需要的中间状态。"""
        t0 = time.perf_counter()
        try:
            # 1. Resolve messages
            raw_messages: list[dict] = []
            if body.conversation_id is not None:
                conv = self._chat.get_conversation(tenant_id, body.conversation_id)
                if not conv:
                    raise MemoryConversationNotFound("会话不存在")
                db_msgs = self._chat.list_messages(
                    tenant_id, body.conversation_id, page=1, page_size=500
                )
                raw_messages = [
                    {"role": m.role, "content": m.content}
                    for m in db_msgs
                ]
            else:
                raw_messages = [{"role": m.role, "content": m.content} for m in body.messages]

            if not raw_messages:
                return {"ok": False, "error": "没有消息", "result": None}

            # 2. Use the explicitly selected agent or caller-provided LLM settings.
            config = (await self._agents.get_config(body.agent_key) or {}) if body.agent_key else {}
            overrides = body.llm_override or {}
            if not (overrides.get("api_key") or config.get("api_key")):
                raise MemoryRequestError("请选择已配置模型的 Agent，或传入 llm_override")
            llm = ChatOpenAI(
                model=overrides.get("model") or config.get("model") or "deepseek-chat",
                api_key=overrides.get("api_key") or config.get("api_key") or "sk-xxx",
                base_url=overrides.get("base_url") or config.get("base_url") or "https://api.deepseek.com",
                temperature=0,
            )

            session = SessionMemory()
            compressor = MemoryCompressor()

            intermediate: dict = {}

            # Config snapshot
            cfg = self.config.get_config()
            intermediate["config"] = dict(cfg)
            threshold = int(cfg["max_tokens"] * cfg["compact_ratio"] * 0.9)
            system_tokens = session._estimate_tokens(body.system_prompt)
            intermediate["threshold"] = threshold
            intermediate["system_tokens"] = system_tokens

            # Token estimates
            buf_tokens = sum(session._estimate_tokens(session._content(m)) for m in raw_messages)
            intermediate["buf_tokens"] = buf_tokens
            budget = max(
                threshold - system_tokens - cfg["reserve_tokens"],
                cfg["max_tokens"] // 2,
            )
            intermediate["budget"] = budget
            intermediate["needs_compression"] = buf_tokens > budget

            # Tool truncation
            tool_before = len(raw_messages)
            compacted = session.compact_tool_result_for_all(
                raw_messages,
                keep_n=cfg["tool_keep_n"],
                max_chars=cfg["tool_max_chars"],
            )
            truncated_count = sum(
                1 for i, m in enumerate(raw_messages)
                if session._role(m) in ("tool", "function") and i < max(0, len(raw_messages) - cfg["tool_keep_n"])
            )
            intermediate["tool_compaction"] = {
                "keep_n": cfg["tool_keep_n"],
                "max_chars": cfg["tool_max_chars"],
                "before_total": tool_before,
                "after_total": len(compacted),
                "truncated_count": truncated_count,
            }

            # Context check
            to_keep, to_compact = session.check_context(compacted, budget)
            intermediate["context_check"] = {
                "to_keep_count": len(to_keep),
                "to_compact_count": len(to_compact),
                "to_keep_roles": [session._role(m) for m in to_keep],
                "to_compact_roles": [session._role(m) for m in to_compact],
            }

            # Run compression if needed
            compressed_summary = ""
            profile_facts: list[str] = []
            extraction_raw = ""
            if to_compact:
                compressed_summary = await compressor.compact(
                    llm=llm, messages=to_compact,
                    previous_summary=None,
                )

                # Profile extraction (inline, skip DB write)
                try:
                    history = compressor._render(to_compact)
                    response = await llm.ainvoke([
                        SystemMessage(content=EXTRACT_PROMPT),
                        HumanMessage(content=history),
                    ])
                    extraction_raw = response.content.strip()
                    if extraction_raw and not extraction_raw.startswith("SKIP") and len(extraction_raw) >= 10:
                        try:
                            data = json.loads(extraction_raw)
                            profile_facts = data.get("facts", [])
                        except json.JSONDecodeError:
                            if "```json" in extraction_raw:
                                jtext = extraction_raw.split("```json", 1)[1].split("```", 1)[0]
                                data = json.loads(jtext)
                                profile_facts = data.get("facts", [])
                except Exception as e:
                    extraction_raw = f"提取失败: {e}"
                    logger.warning(f"Profile extraction failed in debug: {e}")

            intermediate["compressed_summary"] = compressed_summary
            intermediate["profile_facts"] = profile_facts
            intermediate["extraction_raw"] = extraction_raw

            # Render output
            recent = session.render(to_keep)
            profile_text = self.experience.render_profile(tenant_id, body.user_id)
            parts = [p for p in [profile_text, compressed_summary, recent] if p]
            full = "\n\n".join(parts)

            intermediate["rendering"] = {
                "recent_char_count": len(recent),
                "recent_message_count": len(to_keep),
                "profile_char_count": len(profile_text),
                "summary_char_count": len(compressed_summary),
                "full_char_count": len(full),
            }

            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            intermediate["processing_time_ms"] = elapsed_ms

            return {
                "ok": True,
                "result": {
                    "profile": profile_text,
                    "summary": compressed_summary,
                    "recent": recent,
                    "full": full,
                    "intermediate": intermediate,
                },
            }

        except (MemoryConversationNotFound, MemoryRequestError):
            raise
        except Exception as e:
            logger.exception("Memory debug run failed")
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "result": None,
            }
