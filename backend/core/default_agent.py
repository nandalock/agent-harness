"""平台内置的默认智能体：本地终端工具 + DeepSeek 环境变量。

只在 ``agent_definitions`` 里没有 ``default`` 时插入；已有定义完全不动。
模型连接不写进 DB：``providers.resolve_model_config`` 会读
``DEEPSEEK_API_KEY`` / ``DEEPSEEK_BASE_URL`` / ``DEEPSEEK_MODEL``，DB 里的值
永远优先，其他 provider 只从 DB 读。
"""
from __future__ import annotations

import json
import os

DEFAULT_AGENT_KEY = "default"
DEFAULT_AGENT_NAME = "默认智能体"
DEFAULT_AGENT_TOOLS: tuple[str, ...] = (
    ("bash", "python", "powershell") if os.name == "nt" else ("bash", "python")
)

_TOOLS = "、".join(DEFAULT_AGENT_TOOLS)
DEFAULT_AGENT_DESCRIPTION = f"平台内置的通用智能体，已绑定本地终端工具：{_TOOLS}。"
DEFAULT_AGENT_CONFIG = {
    "provider": "deepseek",
    "system_prompt": (
        f"你是平台的默认智能体。你可以使用本地终端工具（{_TOOLS}）操作当前工作区："
        "执行命令前先确认工作目录，写文件优先限定在工作区内；"
        "涉及删除、覆盖或提升权限的操作，先说明影响再执行。"
    ),
    "fallback_reply": "抱歉，我暂时无法处理。",
    "max_steps": 20,
}


def seed_default_agent(cursor) -> bool:
    """Insert the default agent and bindings once; return whether it was inserted."""
    cursor.execute(
        """INSERT INTO agent_definitions
               (agent_key, name, description, config, status, agent_type)
           VALUES (%s, %s, %s, %s::jsonb, 'active', 'agent')
           ON CONFLICT (agent_key) DO NOTHING
           RETURNING agent_key""",
        (
            DEFAULT_AGENT_KEY,
            DEFAULT_AGENT_NAME,
            DEFAULT_AGENT_DESCRIPTION,
            json.dumps(DEFAULT_AGENT_CONFIG, ensure_ascii=False),
        ),
    )
    if cursor.fetchone() is None:
        return False
    cursor.executemany(
        """INSERT INTO agent_tool_bindings (agent_key, tool_name)
           VALUES (%s, %s) ON CONFLICT DO NOTHING""",
        [(DEFAULT_AGENT_KEY, tool) for tool in DEFAULT_AGENT_TOOLS],
    )
    return True
