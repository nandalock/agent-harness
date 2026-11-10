"""Service key for the agent API controller."""
from agent_platform_plugin_sdk import ServiceKey

from .service import AgentApiService

AGENT_API: ServiceKey[AgentApiService] = ServiceKey("agent.api")
