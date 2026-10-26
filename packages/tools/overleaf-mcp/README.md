# Agent Platform Overleaf MCP

Overleaf MCP launcher and DB registration, independent of `backend/`. The upstream `overleaf-mcp-plus` server runs in its own environment; this package only prepares credentials and launches it.

```bash
python -m agent_platform_overleaf_mcp.launcher
```

`ensure_server()` inserts an `mcp_servers` row with this module as the stdio command. The backend auto-loads DB MCP servers through `agent-platform.mcp-client` at startup.
