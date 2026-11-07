"""Typed access to services owned by the active plugin runtime.

The HTTP layer resolves non-session services here; runtime code never does.
"""
from agent_platform_plugin_sdk import ServiceUnavailableError


def require(key):
    from backend.plugin_host import get_plugin_host

    host = get_plugin_host()
    if host is None:
        raise ServiceUnavailableError(key.ref)
    return host.runtime.require(key)


def prompts():
    from agent_platform_system_prompt import RUNTIME_PROMPTS
    return require(RUNTIME_PROMPTS)


def llm():
    from agent_platform_llm import LLM
    return require(LLM)


def sandbox():
    from agent_platform_sandbox.services import SANDBOX
    return require(SANDBOX)


def agent_runtime():
    from agent_platform_agent_runtime import AGENT_RUNTIME
    return require(AGENT_RUNTIME)


def agent_entry():
    from agent_platform_agent_entry import AGENT_ENTRY
    return require(AGENT_ENTRY)


def chat_store():
    from agent_platform_chat import CHAT
    return require(CHAT).store


def agents():
    from agent_platform_plugin_sdk import AGENTS
    return require(AGENTS)


def workspace_controller():
    from agent_platform_api_workspace import WORKSPACE_CONTROLLER
    return require(WORKSPACE_CONTROLLER)


def agent_api():
    from agent_platform_api_agents import AGENT_API
    return require(AGENT_API)


def session_api():
    from agent_platform_api_sessions import SESSION_API
    return require(SESSION_API)
