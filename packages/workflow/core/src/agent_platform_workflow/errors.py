"""Domain errors surfaced by the workflow service."""


class WorkflowError(Exception):
    """Base class for workflow domain failures."""


class WorkflowNotFound(WorkflowError):
    """The requested workflow row does not exist."""


class WorkflowNameConflict(WorkflowError):
    """A workflow with the same name already exists for the tenant."""


class WorkflowValidationError(WorkflowError):
    """The workflow definition cannot be built or saved."""
