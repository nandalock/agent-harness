# Session projection

Pure, read-only folds over the session event log:

- `trajectory.py`: typed events → UI trajectory nodes
- `sandbox.py`: `sandbox/mode` → effective session mode
- `trace.py` is re-exported from the session core package

The package registers as `agent-platform.session-projection` and provides
`agent.session-projection.v1`. Consumers import `agent_platform_session_projection`
directly; there is no backend compatibility layer.
