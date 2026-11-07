# Default composition

`plugins.yaml` is the default application assembly. Backend loads this package,
adds host configuration such as database MCP servers, and starts PluginRuntime.
It does not enumerate individual tools.

A plugin package is a lifecycle and assembly unit. Each configured instance may
publish services, register zero or many tools, and own cleanup effects:

| Package entry | Services | Tools per instance |
| --- | --- | --- |
| database-postgres | database.v1 | 0; owns the pooled connection factory and optional schema bootstrap |
| settings-postgres | settings.v1 | 0; DB-backed namespace settings |
| agent-config | agents.v1, tool-bindings.v1 | 0; definitions/configs and per-agent bindings |
| session | agent.sessions.v1 | 0; live SessionStore |
| session-persistence-postgres | agent.session-persistence.v1 | 0; durable event log |
| session-title | agent.session-title.v1 | 0; log-backed titles |
| session-recovery | agent.session-recovery.v1 | 0; checkpoint/ownership/recovery |
| session-projection | agent.session-projection.v1 | 0; read-only projections |
| llm | llm.v1 | 0; provider registry, client factory and HTTP pool |
| llm-deepseek | — (registers a route on llm.v1) | 0; resolves DeepSeek base URL/model/credential from plugin config + env |
| tools-default | tools.v1, tools.catalog.v1 | 0 of its own; hosts registrations |
| tool-host | unified-tools.v1 | 0; single-track bridge over tools.v1 |
| system-prompt | agent.prompts.v1 | 0; per-runtime prompt registry |
| agents | agent.runs.v1 | 0; owns driver factory and active run scopes |
| agent-loop | consumes agent.runs.v1, tools.v1, tools.catalog.v1 and approval.v1 | 0; supplies the default LLM/tool driver and drains it on unload |
| agent-runtime | agent.runtime.v1, agent.extensions.v1 | 0; requires prompt, LLM, session, sandbox and config services |
| mcp-manager | mcp.manager.v1 | 0 at setup; manages dynamic server tool groups |
| mcp-client | MCP connection lifecycle | 0–N discovered server tools |
| skills-default | skills.v1 | 0; merges registered skill providers |
| skills-filesystem | consumes skills.v1 | 0; contributes local/bundled/installed directories |
| skill-tools | consumes skills.v1, tools.v1, agents.v1 and agent.extensions.v1 | skill, skill_install; owns conversation hooks |
| sandbox-tools | consumes tools.v1 and settings.v1 | bash, python when enabled |
| sandbox-local / sandbox-docker | sandbox.v1 | 0; replaceable execution backend |
| sandbox-policy | agent.sandbox.v1 | 0; per-session policy over the selected provider |
| rpc-gateway | rpc.gateway.v1 | 0; explicit method registration and validated dispatch |
| rpc-connection | rpc.connection.v1 | 0; JSON-RPC 2.0 envelope/correlation/cancellation |
| api-workspace / api-agents / api-sessions | workspace.controller.v1 / agent.api.v1 / session.api.v1 | 0; business controllers shared by RPC and legacy REST |
| http-api | http.app.v1 | 0; FastAPI application owned by a plugin |

Native execution is the local default. `SANDBOX_BACKEND=docker` selects the Docker
provider through the host composition. sandbox-tools consumes sandbox.v1; Windows
native mode also registers powershell. See [native sandbox](../../../docs/native-sandbox.md).

Library packages such as skills, sandbox, and tool-system provide reusable
implementations. A package is discoverable as a plugin only when it exports a
plugin entry point. This composition package is a preset, not a runtime plugin.

`compose(user_config)` fills absent defaults. Override by package name or default
instance id. Explicit `disabled: true` is respected, including for tools-default;
disabling a required service without a replacement fails dependency validation.
Multiple explicit mcp-client instances each own their server's whole tool group.
