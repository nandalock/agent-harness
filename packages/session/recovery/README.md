# Session recovery plugin

`agent-platform.session-recovery` owns the concrete checkpoint writer and the
exclusive prepare/resume flow:

- `checkpoint.py`: awaited, serialized persistence flushes
- `recovery.py`: write-ownership preparation, interrupted-tail repair, status
- provides `agent.session-recovery.v1`

Consumers import `agent_platform_session_recovery` directly; there is no backend
compatibility layer.
