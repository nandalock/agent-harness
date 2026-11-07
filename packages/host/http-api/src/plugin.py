"""HTTP/API plugin: owns the FastAPI application, not the agent runtime."""
from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_api_agents import AGENT_API
from agent_platform_api_sessions import SESSION_API
from agent_platform_api_workspace import WORKSPACE_CONTROLLER
from agent_platform_chat import CHAT
from agent_platform_faq import FAQ
from agent_platform_mcp_client import MCP_MANAGER
from agent_platform_memory import MEMORY
from agent_platform_plugin_inventory import PLUGIN_INVENTORY
from agent_platform_sandbox.services import SANDBOX
from agent_platform_skills import SKILLS
from agent_platform_system_prompt import RUNTIME_PROMPTS
from agent_platform_tool_host import UNIFIED_TOOLS
from agent_platform_user_approval import APPROVAL_INBOX
from agent_platform_xianyu import XIANYU
from agent_platform_plugin_sdk import (
    AGENTS,
    AGENT_EXTENSIONS,
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
    TOOL_BINDINGS,
    TOOLS,
)
from agent_platform_rpc_connection import CONNECTION
from agent_platform_workflow import WORKFLOW

from .app import create_app
from .services import HTTP_APP


class HttpConfig(SdkModel):
    pass


class HttpApiPlugin:
    spec = PluginSpec(
        name="agent-platform.http-api",
        version="0.1.0",
        provides=(HTTP_APP.ref,),
        requires=(
            *(ServiceRequirement(service=key.ref) for key in (
                CONNECTION, AGENT_ENTRY, CHAT, AGENTS, DATABASE, AGENT_EXTENSIONS,
            )),
            *(ServiceRequirement(service=key.ref, optional=True) for key in (
                APPROVAL_INBOX, MEMORY, WORKFLOW, FAQ, XIANYU, PLUGIN_INVENTORY,
                AGENT_API, SESSION_API, WORKSPACE_CONTROLLER, RUNTIME_PROMPTS,
                TOOLS, UNIFIED_TOOLS, TOOL_BINDINGS, SKILLS, MCP_MANAGER, SANDBOX,
            )),
        ),
    )
    config_model = HttpConfig

    async def setup(self, ctx: PluginContext, config: HttpConfig) -> None:
        services = {
            AGENTS.ref: ctx.require(AGENTS),
            AGENT_EXTENSIONS.ref: ctx.require(AGENT_EXTENSIONS),
            CHAT.ref: ctx.require(CHAT),
        }
        for key in (AGENT_API, SESSION_API, WORKSPACE_CONTROLLER, RUNTIME_PROMPTS,
                    TOOLS, UNIFIED_TOOLS, TOOL_BINDINGS, SKILLS, MCP_MANAGER, SANDBOX):
            service = ctx.get(key)
            if service is not None:
                services[key.ref] = service
        ctx.provide(HTTP_APP, create_app(
            ctx.require(CONNECTION), entry=ctx.require(AGENT_ENTRY),
            chat=ctx.require(CHAT), approval=ctx.get(APPROVAL_INBOX), agent_config=ctx.require(AGENTS),
            memory=ctx.get(MEMORY), workflow=ctx.get(WORKFLOW), faq=ctx.get(FAQ),
            xianyu=ctx.get(XIANYU),
            plugin_catalog=ctx.get(PLUGIN_INVENTORY), database=ctx.require(DATABASE),
            services=services,
        ))
