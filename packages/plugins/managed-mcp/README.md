# Managed MCP service plugins

This package owns the lifecycle previously hardcoded in backend/main.py.
It exports four independent plugin entries:

| Entry | Lifecycle |
| --- | --- |
| agent-platform.builtin-mcp | Built-in HTTP service, connection, six tools |
| agent-platform.paper-mcp | Paper HTTP service, connection, four tools |
| agent-platform.overleaf-mcp | Persisted integration registration and isolated stdio connection |
| agent-platform.overleaf-rt-mcp | Persisted realtime integration registration and stdio connection |

Each instance requires mcp.manager.v1. Setup awaits HTTP readiness before
connecting. Connections register tools with the instance's plugin_id. Disposal
removes the current owned connection generation before closing its HTTP server.
Setup failure rolls back already acquired resources through PluginContext.
Each HTTP activation uses a fresh FastMCP instance, so close/start is repeatable.

Default composition lives in packages/platform-default/plugins.yaml. For example:

```yaml
version: 1
plugins:
  - id: builtin-mcp
    name: agent-platform.builtin-mcp
    disabled: true
  - id: paper-mcp
    name: agent-platform.paper-mcp
    config:
      port: 19002
```

Configuration supports enabled and optional port. Environment defaults remain
BUILTIN_MCP_PORT/PAPER_MCP_PORT (9001/9002, or 19001/19002 from the local launcher).
OVERLEAF_ENABLED and OVERLEAF_RT_ENABLED retain their existing behavior. Optional
Overleaf failures are logged without disabling other tool plugins. Set
MANAGED_MCP_ENABLED=false to turn off all four managed integrations.

Persisted server ids and raw tool names are retained, preserving API management
and existing bindings. These managed rows are excluded from DB client discovery
to prevent duplicate registration or accidental activation of disabled plugins.
PLUGIN_MCP_AUTO still controls only other database-discovered MCP clients.

The HTTP helper lives in this package; backend/embedded_mcp.py is a compatibility
import for older callers. This package does not import backend.
