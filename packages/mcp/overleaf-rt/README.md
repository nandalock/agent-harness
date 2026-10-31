# Agent Platform Overleaf RT MCP

Launcher and DB registration for the `overleaf-mcp-rt` realtime server, independent of `backend/`.

```bash
python -m agent_platform_overleaf_rt_mcp.launcher
```

`ensure_server()` inserts an `mcp_servers` row with this module as the stdio command. The backend auto-loads DB MCP servers through `agent-platform.mcp-client` at startup.
