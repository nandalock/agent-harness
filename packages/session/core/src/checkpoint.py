from typing import Protocol, Any


class CheckpointError(RuntimeError):
    code = "session/checkpoint-failed"

    def __init__(self, session_id: str, reason: str):
        self.session_id = session_id
        self.reason = reason
        super().__init__("进度保存失败，任务已停止。请稍后重试继续。")


class SessionCheckpoint(Protocol):
    enabled: bool
    failed: bool

    async def flush(self, reason: str) -> None: ...
    async def before_tool(self, call: Any) -> None: ...
