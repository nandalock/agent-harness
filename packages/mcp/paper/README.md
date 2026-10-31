# Agent Platform Paper MCP

Paper search/fetch/summarize tools exposed as a FastMCP server. This package is independent of `backend/`; it reads LLM settings from `PAPER_LLM_*` environment variables or a local `llm.config.json`.

Run over HTTP (backend starts it on port 9002) or stdio:

```bash
python -m agent_platform_paper_mcp
```

Tools are registered into the plugin-side registry by `agent-platform.mcp-client`:

```yaml
- id: mcp-paper
  name: agent-platform.mcp-client
  config:
    server_name: paper
    transport: http
    url: http://localhost:9002/mcp
    timeout_seconds: 300
```

LLM config template: `llm.config.example.json` (copy to `llm.config.json` next to the module, or use env vars).
