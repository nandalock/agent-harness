# Agent Platform Built-in MCP

Built-in database tools (orders, FAQ, user profile) exposed as a FastMCP server. This package is independent of `backend/`; it reads `DATABASE_URL` from the environment.

Run over HTTP (backend starts it on port 9001) or stdio:

```bash
python -m agent_platform_builtin_mcp
```

Tools are registered into the plugin-side registry by `agent-platform.mcp-client`:

```yaml
- id: mcp-builtin
  name: agent-platform.mcp-client
  config:
    server_name: builtin
    transport: http
    url: http://localhost:9001/mcp
```
