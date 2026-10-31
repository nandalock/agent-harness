"""当前租户、当前智能体可见的用户技能目录，包含聊天安装的技能。"""
import asyncio

from fastapi import APIRouter, Header, HTTPException

from backend.agents import get_agent
from backend.agents.runtime import AgentRuntime
from backend.core.connection import get_conn
from agent_platform_skills import SKILLS, SkillError
from agent_platform_plugin_sdk import AgentRunContext, ServiceUnavailableError
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
    from backend.plugin_host import get_plugin_host
    from backend.agents.runtime.extensions import get_agent_extensions
    host = get_plugin_host()
    if host is None:
        return {"skills": []}
    try:
        skills = host.runtime.require(SKILLS)
    except ServiceUnavailableError:
        return {"skills": []}
    try:
        contribution = await get_agent_extensions().prepare(AgentRunContext(
            tenant_id=x_tenant_id, agent_key=agent_key, config=config,
            tool_schemas=[{"type": "function", "function": {"name": name}} for name in names],
        ))
        # With the consumer plugin disabled there is no skill invocation UI.
        if "skills" not in contribution.capabilities:
            return {"skills": []}
        names = [tool["function"]["name"] for tool in contribution.tool_schemas]
        scope = scope_for(x_tenant_id, agent_key, names, config)
        entries = await asyncio.to_thread(catalog_entries, skills, scope)
    except SkillError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"skills": [e for e in entries if e["user_invocable"]]}
