"""当前租户、当前智能体可见的用户技能目录，包含聊天安装的技能。"""
import asyncio

from fastapi import APIRouter, Header, HTTPException

from backend.agents import get_agent
from backend.agents.runtime import AgentRuntime
from backend.core.connection import get_conn
from agent_platform_skills.registry import SkillError, get_skill_registry
from agent_platform_skills.runtime import catalog_entries, scope_for

router = APIRouter(prefix="/api/agents", tags=["Skills"])


def _bindings(agent_key: str) -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tool_name FROM agent_tool_bindings "
                "WHERE agent_key = %s ORDER BY tool_name",
                (agent_key,),
            )
            return [row["tool_name"] for row in cur.fetchall()]


@router.get("/{agent_key}/skills")
async def list_skills(agent_key: str, session_id: str | None = None,
                      x_tenant_id: int = Header(alias="X-Tenant-ID")):
    try:
        agent = get_agent(agent_key)
    except KeyError:
        raise HTTPException(404, "智能体不存在")
    if session_id:
        def owned():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM conversations WHERE tenant_id = %s AND session_id = %s AND agent_key = %s",
                                (x_tenant_id, session_id, agent_key))
                    return cur.fetchone() is not None
        if not await asyncio.to_thread(owned):
            raise HTTPException(404, "会话不存在")
    if not isinstance(agent, AgentRuntime):
        return {"skills": []}
    config = await asyncio.to_thread(agent._cfg)
    names = await asyncio.to_thread(_bindings, agent_key)
    from agent_platform_skills.installer import install_enabled
    if install_enabled(config):
        names = [*names, "skill_install"]
    else:
        names = [name for name in names if name != "skill_install"]
    try:
        scope = scope_for(x_tenant_id, agent_key, names, config)
        entries = await asyncio.to_thread(catalog_entries, get_skill_registry(), scope)
    except SkillError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"skills": [e for e in entries if e["user_invocable"]]}
