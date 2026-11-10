"""SurfaceManager — 决定哪些 SessionEvent 对 LLM 可见（ordered surface）

Event Log 是完整执行事实；Surface 是 LLM 可见子集。
普通消息按顺序追加。context/checkpoint 用摘要替换前缀，原始事件仍在 Event Log 中。
"""
from agent_platform_session.events import CONTEXT_CHECKPOINT, SURFACE_EVENT_TYPES, SessionEvent


class SurfaceManager:
    def __init__(self):
        self._events: list[SessionEvent] = []

    def append(self, event: SessionEvent) -> None:
        """维护模型可见的消息顺序。"""
        if event.type == CONTEXT_CHECKPOINT:
            # Earlier checkpoints have newer log seqs than the tail they precede.
            # A new checkpoint replaces that earlier summary as well as new history.
            through = event.data["through_seq"]
            self._events = [event, *(item for item in self._events
                                     if item.type != CONTEXT_CHECKPOINT and item.seq > through)]
        elif event.type in SURFACE_EVENT_TYPES:
            self._events.append(event)

    @property
    def events(self) -> list[SessionEvent]:
        """有序 surface 事件（返回副本，外部只读）"""
        return list(self._events)
