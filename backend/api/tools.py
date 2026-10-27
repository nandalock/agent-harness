"""Tools API — 工具绑定

绑定与**工具来源**正交：内建工具（沙箱 bash / python）与 MCP 工具走同一套绑定，
因此路径归在 /api/tools 而不是 /api/mcp。历史路径 /api/mcp/bindings 保留为别名
（见 api/mcp.py），旧客户端不受影响。

全量替换语义：PUT 会用请求体覆盖该 agent 的全部绑定。
"""
from fastapi import APIRouter, Body
from pydantic import BaseModel

from backend.core.connection import get_conn

router = APIRouter(prefix="/api/tools", tags=["Tools"])


class CapabilityBody(BaseModel):
    enabled: bool


@router.get("/bindings")
def api_list_bindings():
    """全部绑定：agent_key → [tool_name]"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT agent_key, tool_name FROM agent_tool_bindings ORDER BY agent_key")
            rows = cur.fetchall()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["agent_key"], []).append(r["tool_name"])
    return result


@router.put("/bindings/{agent_key}")
def api_save_bindings(agent_key: str, tools: list[str] = Body(...)):
    """全量替换该 agent 的绑定（先删后插）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_tool_bindings WHERE agent_key = %s", (agent_key,))
            for tn in tools:
                cur.execute(
                    "INSERT INTO agent_tool_bindings (agent_key, tool_name) VALUES (%s, %s)",
                    (agent_key, tn),
                )
        conn.commit()
    return {"ok": True, "agent_key": agent_key, "tools": tools}


# ── 能力开关 ──
# 值归各子系统所有（当前只有 sandbox），本层只做读写与转发。

@router.get("/capabilities/sandbox")
def api_get_sandbox_capability():
    """沙箱能力是否启用（settings.sandbox.enabled，缺省 true）。"""
    from agent_platform_sandbox_tools import is_sandbox_enabled

    from agent_platform_sandbox.runtime import get_sandbox_provider
    provider = get_sandbox_provider()
    return {"name": "sandbox", "enabled": is_sandbox_enabled(),
            "backend": getattr(provider, "backend", None)}


@router.put("/capabilities/sandbox")
async def api_set_sandbox_capability(body: CapabilityBody):
    """启停沙箱能力：插件立即注册/注销 bash、python，下一轮对话即生效。"""
    from agent_platform_sandbox_tools import set_sandbox_enabled

    try:
        await set_sandbox_enabled(body.enabled)
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(503, str(exc)) from exc
    return {"name": "sandbox", "enabled": body.enabled}
