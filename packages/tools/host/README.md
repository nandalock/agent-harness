# agent-platform-tool-host

Single-track adapter used by a host runtime:

- converts a host `ToolContext` into the SDK `ToolContext` (`host_context` bridge);
- executes every Agent-facing tool through the one `tools.v1` registry;
- emits the canonical tool lifecycle events once;
- exposes the optional runtime singleton used by the scheduler/system prompt.

It contains no tool implementations and no database access.
