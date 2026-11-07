"""Service key for the workspace controller (RPC and legacy REST share it)."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .service import WorkspaceService

WORKSPACE_CONTROLLER: ServiceKey[WorkspaceService] = ServiceKey(
    ServiceRef(name="workspace.controller", api_version=1)
)
