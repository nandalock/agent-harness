from pydantic import Field

from agent_platform_plugin_sdk import (
    APPROVAL, SdkModel, ServiceKey,
)

from .channel import DEFAULT_APPROVAL_TIMEOUT_S, InProcessApprovalChannel
from .service import ApprovalService
from minidsh_cordis import Context, Plugin

APPROVAL_INBOX = ServiceKey[ApprovalService]("approval.inbox")


class ApprovalConfig(SdkModel):
    timeout_seconds: float = Field(default=DEFAULT_APPROVAL_TIMEOUT_S, gt=0)


class UserApprovalPlugin(Plugin[ApprovalConfig]):
    name = "agent-platform.user-approval"
    version = "0.1.0"
    provides = (APPROVAL, APPROVAL_INBOX)
    config_model = ApprovalConfig

    async def setup(self, ctx: Context, config: ApprovalConfig) -> None:
        channel = InProcessApprovalChannel(config.timeout_seconds)
        service = ApprovalService(channel)
        ctx.provide(APPROVAL, service)
        ctx.provide(APPROVAL_INBOX, service)
        ctx.on_quiesce(service.aclose, label="settle pending approvals")
