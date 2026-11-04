"""Host access to the runtime-scoped agent service; no concrete driver imports."""
from agent_platform_agents import AGENT_RUNS, AgentService
from agent_platform_plugin_sdk import ServiceUnavailableError


def get_agent_runs() -> AgentService:
    from backend.plugin_host import get_plugin_host
    host = get_plugin_host()
    if host is None:
        raise ServiceUnavailableError(AGENT_RUNS.ref)
    return host.runtime.require(AGENT_RUNS)
