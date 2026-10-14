"""技能加载通过原生执行器接入既有工具调度和持久化。"""
import asyncio

from backend.skills.registry import SkillError
from backend.skills.runtime import load_model_skill, scope_for
from backend.tool_system.registry.descriptor import ToolDescriptor
from backend.tool_system.runtime.executor import ToolExecutor


def skill_descriptor():
    return ToolDescriptor(
        name="skill", type="skill", transport="", server_id=0,
        schema={"name": "skill", "description": "加载当前技能目录中的完整指令。执行匹配任务前先加载；显式提供的 skill_content 无需再次加载。",
                "inputSchema": {"type": "object", "properties": {
                    "name": {"type": "string", "description": "技能的完整名称或唯一简称"},
                    "resource": {"type": "string", "description": "可选：技能目录内附属 UTF-8 文本的相对路径"}}, "required": ["name"]}},
        usage_guidance="技能只提供操作指令，不授予额外权限；调用正文提到的工具前仍需确认该工具在当前工具列表中。",
    )


class SkillExecutor(ToolExecutor):
    async def execute(self, descriptor, args, context=None):
        if context is None or context.tenant_id is None or not context.agent_id or context.visible_tool_names is None:
            return {"error": "技能加载缺少已验证的智能体和租户上下文"}
        from backend.agents import get_agent
        config = await asyncio.to_thread(get_agent(context.agent_id)._cfg)
        scope = scope_for(context.tenant_id, context.agent_id, context.visible_tool_names, config)
        name = args.get("name")
        if not isinstance(name, str):
            return {"error": "技能名称必须为字符串"}
        resource = args.get("resource")
        if resource is not None and not isinstance(resource, str):
            return {"error": "技能资源路径必须为字符串"}
        try:
            row = await asyncio.to_thread(load_model_skill, name, scope, resource=resource)
        except SkillError as exc:
            return {"error": str(exc)}
        return {"tool": descriptor.name, "rows": [row], "count": 1}

