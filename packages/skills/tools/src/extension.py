"""Skill tool exposure and conversation hooks are registered by the plugin."""
import asyncio
from agent_platform_plugin_sdk import AgentRunContext, AgentRunContribution, ExecutionScope, ToolsService
from agent_platform_skills import SkillsService, scope_for
from agent_platform_skills.installer import install_enabled
from .descriptors import openai_tool
from .runtime import SkillPreStep


class SkillAgentExtension:
    def __init__(self, skills: SkillsService, tools: ToolsService) -> None:
        self.skills, self.tools = skills, tools

    async def __call__(self, context: AgentRunContext) -> AgentRunContribution:
        available = {tool.name: tool for tool in await self.tools.list_for_agent(
            ExecutionScope(tenant_id=context.tenant_id, agent_key=context.agent_key)
        )}
        schemas = list(context.tool_schemas)
        automatic: dict[str, set[str]] = {}

        def bind(name: str, owner: str) -> None:
            if name == "skill_install" and not install_enabled(context.config):
                return
            automatic.setdefault(name, set()).add(owner)
            if name in available and not any(t["function"]["name"] == name for t in schemas):
                schemas.append(openai_tool(available[name]))

        if not install_enabled(context.config):
            schemas = [tool for tool in schemas if tool["function"]["name"] != "skill_install"]
        elif "skill_install" in available:
            bind("skill_install", "技能安装")
        if context.config.get("skills_enabled", True) is False:
            schemas = [tool for tool in schemas if tool["function"]["name"] != "skill"]
        scope = scope_for(context.tenant_id, context.agent_key, [t["function"]["name"] for t in schemas], context.config)
        catalog = await asyncio.to_thread(self.skills.list, scope)
        for skill in catalog:
            for name in skill.bound_tools:
                bind(name, skill.package_name or skill.name)
        scope = scope_for(context.tenant_id, context.agent_key, [t["function"]["name"] for t in schemas], context.config)
        if "skill" in available and any(s.model_invocable and not s.unavailable_reason(scope) for s in catalog):
            bind("skill", "技能加载")
        scope = scope_for(context.tenant_id, context.agent_key, [t["function"]["name"] for t in schemas], context.config)
        return AgentRunContribution(schemas, SkillPreStep(scope, self.skills), frozenset({"skills"}),
                                    {name: tuple(sorted(owners)) for name, owners in automatic.items()})
