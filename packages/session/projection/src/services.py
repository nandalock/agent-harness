"""Service key owned by the session projection plugin."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef


class SessionProjectionService:
    """Read-only projections exposed to hosts and UI adapters."""

    @staticmethod
    def trajectory(events):
        from .trajectory import project_trajectory
        return project_trajectory(events)

    @staticmethod
    def sandbox_mode(events):
        from .sandbox import project_sandbox_mode
        return project_sandbox_mode(events)

    @staticmethod
    def trace():
        from agent_platform_session.trace import TraceProjection
        return TraceProjection


SESSION_PROJECTION = ServiceKey[SessionProjectionService](
    ServiceRef(name="agent.session-projection", api_version=1)
)
