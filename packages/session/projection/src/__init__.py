"""Read-only projections over the session event log."""
from agent_platform_session.trace import TraceProjection, project_trace

from .sandbox import SandboxModeProjection, project_sandbox_mode
from .trajectory import TrajectoryProjection, project_trajectory

__all__ = [
    "SandboxModeProjection",
    "TraceProjection",
    "TrajectoryProjection",
    "project_sandbox_mode",
    "project_trace",
    "project_trajectory",
    "SESSION_PROJECTION",
    "SessionProjectionService",
    "SessionProjectionPlugin",
]
from .services import SESSION_PROJECTION, SessionProjectionService
from .plugin import SessionProjectionPlugin
