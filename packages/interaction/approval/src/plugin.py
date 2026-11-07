from pydantic import Field

from agent_platform_plugin_sdk import (
    APPROVAL, PluginContext, PluginSpec, SdkModel, ServiceKey, ServiceRef,
)

from .channel import DEFAULT_APPROVAL_TIMEOUT_S, InProcessApprovalChannel
from .service import ApprovalService

APPROVAL_INBOX = ServiceKey[ApprovalService](ServiceRef(name="approval.inbox", api_version=1))


class ApprovalConfig(SdkModel):
    timeout_seconds: float = Field(default=DEFAULT_APPROVAL_TIMEOUT_S, gt=0)


class UserApprovalPlugin:
    spec = PluginSpec(
        name="agent-platform.user-approval", version="0.1.0",
        provides=(APPROVAL.ref, APPROVAL_INBOX.ref),
    )
    config_model = ApprovalConfig

    async def setup(self, ctx: PluginContext, config: ApprovalConfig) -> None:
        channel = InProcessApprovalChannel(config.timeout_seconds)
        service = ApprovalService(channel)
        ctx.provide(APPROVAL, service)
        ctx.provide(APPROVAL_INBOX, service)
        ctx.on_quiesce(service.aclose, label="settle pending approvals")
