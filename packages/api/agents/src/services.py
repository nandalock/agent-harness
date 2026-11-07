"""Service key for the agent API controller."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .service import AgentApiService

AGENT_API: ServiceKey[AgentApiService] = ServiceKey(
    ServiceRef(name="agent.api", api_version=1)
)
