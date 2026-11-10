"""HTTP application service contract and request-scoped service access.

The HTTP plugin receives every service its legacy routes need at setup. Routes
read them through this module (a ContextVar bound by middleware), so no route
imports the backend host or a process singleton.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey


class HttpAppService(Protocol):
    def __call__(self, scope, receive, send) -> Any: ...


HTTP_APP: ServiceKey[HttpAppService] = ServiceKey("http.app")

_current: ContextVar[dict[ServiceKey[Any], Any]] = ContextVar("http_services", default={})


def set_services(services: dict[ServiceKey[Any], Any]) -> Token:
    return _current.set(services)


def reset_services(token: Token) -> None:
    _current.reset(token)


def require(key: ServiceKey[Any]) -> Any:
    services = _current.get()
    service = services.get(key)
    if service is None:
        from agent_platform_plugin_sdk import ServiceUnavailableError

        raise ServiceUnavailableError(key)
    return service


def agents():
    from agent_platform_plugin_sdk import AGENTS

    return require(AGENTS)


def agent_extensions():
    from agent_platform_plugin_sdk import AGENT_EXTENSIONS

    return require(AGENT_EXTENSIONS)


def agent_api():
    from agent_platform_api_agents import AGENT_API

    return require(AGENT_API)


def session_api():
    from agent_platform_api_sessions import SESSION_API

    return require(SESSION_API)


def workspace_controller():
    from agent_platform_api_workspace import WORKSPACE_CONTROLLER

    return require(WORKSPACE_CONTROLLER)


def prompts():
    from agent_platform_system_prompt import RUNTIME_PROMPTS

    return require(RUNTIME_PROMPTS)


def chat_store():
    from agent_platform_chat import CHAT

    return require(CHAT).store


def tools():
    from agent_platform_plugin_sdk import TOOLS

    return require(TOOLS)


def unified_tools():
    from agent_platform_tool_host import UNIFIED_TOOLS

    return require(UNIFIED_TOOLS)


def skills():
    from agent_platform_skills import SKILLS

    return require(SKILLS)


def mcp_manager():
    from agent_platform_mcp_client import MCP_MANAGER

    return require(MCP_MANAGER)


def tool_bindings():
    from agent_platform_plugin_sdk import TOOL_BINDINGS

    return require(TOOL_BINDINGS)


def sandbox():
    from agent_platform_sandbox.services import SANDBOX

    return require(SANDBOX)
