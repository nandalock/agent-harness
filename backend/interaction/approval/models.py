"""审批的共享词汇 —— re-exported from the public ``approval.v1`` contract.

The contract lives in ``agent_platform_plugin_sdk.host`` so plugins (sandbox)
can consume it without importing the backend. The in-process approval channel
and service remain backend host implementations.
"""
from agent_platform_plugin_sdk import (  # noqa: F401
    ALLOWED,
    ApprovalChannel,
    ApprovalOutcome,
    ApprovalRequest,
    new_approval_id,
)

__all__ = [
    "ALLOWED",
    "ApprovalChannel",
    "ApprovalOutcome",
    "ApprovalRequest",
    "new_approval_id",
]
