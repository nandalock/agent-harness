from agent_platform_plugin_sdk import ApprovalOutcome, ApprovalRequest

from .channel import InProcessApprovalChannel


class ApprovalService:
    """审批通道 + 可用性查询。实现 :class:`ApprovalChannel` 协议。"""

    def __init__(self, channel: InProcessApprovalChannel) -> None:
        self._channel = channel

    @property
    def available(self) -> bool:
        """当前部署有没有裁决方。

        消费者用它决定「要不要向模型宣传这条路」—— 提示一条必然失败的路径
        只会让它白烧一轮。
        """
        return self._channel.available

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        return await self._channel.request(req)

    def resolve(self, approval_id: str, decision: str) -> bool:
        return self._channel.resolve(approval_id, decision)

    def pending(self) -> list[ApprovalRequest]:
        return self._channel.pending()

    async def aclose(self) -> None:
        await self._channel.aclose()
