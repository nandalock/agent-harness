"""当前租户、当前智能体可见的用户技能目录，包含聊天安装的技能。"""
import asyncio

from fastapi import APIRouter, Header, HTTPException

from .. import services as plugin_services
from ..db import get_conn
from agent_platform_skills import SkillError
from agent_platform_plugin_sdk import ServiceUnavailableError
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
    catalog = await _read_catalog(agent_key, x_tenant_id, session_id=session_id)
    return {"skills": catalog["skills"]}


@router.get("/{agent_key}/skills/catalog")
async def list_skill_catalog(agent_key: str, x_tenant_id: int = Header(alias="X-Tenant-ID")):
    """Configuration view: includes unselected/disabled skills in the same scope.

    Only summaries are exposed. Execution and the chat catalog still enforce
    the persisted agent switches and whitelist.
    """
    return await _read_catalog(agent_key, x_tenant_id, include_unselected=True)


async def _read_catalog(agent_key: str, tenant_id: int, *, session_id: str | None = None,
                        include_unselected: bool = False):
    try:
        agents = plugin_services.agents()
    except ServiceUnavailableError:
        return {"skills": [], "available": False}
    definition = await agents.get_definition(agent_key)
    if definition is None:
        raise HTTPException(404, "智能体不存在")
    if session_id:
        def owned():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM conversations WHERE tenant_id = %s AND session_id = %s AND agent_key = %s",
                                (tenant_id, session_id, agent_key))
                    return cur.fetchone() is not None
        if not await asyncio.to_thread(owned):
            raise HTTPException(404, "会话不存在")
    if definition.get("agent_type") == "router":
        return {"skills": [], "available": False}
    config = await agents.get_config(agent_key) or {}
    if include_unselected:
        config = {**config, "skills_enabled": True, "enabled_skills": None}
    names = await asyncio.to_thread(_bindings, agent_key)
    from agent_platform_agent_runtime import prepare_bindings
    try:
        skills = plugin_services.skills()
        tools = plugin_services.tools()
    except ServiceUnavailableError:
        return {"skills": [], "available": False}
    try:
        contribution = await prepare_bindings(tenant_id, agent_key, config, names, tools, plugin_services.agent_extensions())
        # With the consumer plugin disabled there is no skill invocation UI.
        if "skills" not in contribution.capabilities:
            return {"skills": [], "available": False}
        names = [tool["function"]["name"] for tool in contribution.tool_schemas]
        scope = scope_for(tenant_id, agent_key, names, config)
        entries = await asyncio.to_thread(catalog_entries, skills, scope)
    except SkillError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"skills": entries if include_unselected else [e for e in entries if e["user_invocable"]],
            "available": True}
