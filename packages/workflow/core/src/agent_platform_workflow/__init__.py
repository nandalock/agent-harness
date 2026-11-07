"""Workflow plugin: CRUD, execution and extensible node kinds."""
from .contracts import (
    CacheFactory,
    CacheHandle,
    NodeContext,
    NodeDefinition,
    NodeFactory,
    RoutePlan,
    WORKFLOW,
    WORKFLOW_NODES,
    WorkflowNodeRegistry as WorkflowNodeRegistryProtocol,
    WorkflowService as WorkflowServiceProtocol,
)
from .errors import WorkflowError, WorkflowNameConflict, WorkflowNotFound, WorkflowValidationError
from .graph import MAX_TOTAL_STEPS, build_workflow
from .nodes import BUILTIN_NODES
from .plugin import WorkflowConfig, WorkflowPlugin
from .registry import WorkflowNodeRegistry
from .service import WorkflowService

__all__ = [
    "BUILTIN_NODES",
    "MAX_TOTAL_STEPS",
    "build_workflow",
    "CacheFactory",
    "CacheHandle",
    "NodeContext",
    "NodeDefinition",
    "NodeFactory",
    "RoutePlan",
    "WORKFLOW",
    "WORKFLOW_NODES",
    "WorkflowConfig",
    "WorkflowError",
    "WorkflowNameConflict",
    "WorkflowNodeRegistry",
    "WorkflowNodeRegistryProtocol",
    "WorkflowNotFound",
    "WorkflowPlugin",
    "WorkflowService",
    "WorkflowServiceProtocol",
    "WorkflowValidationError",
]
