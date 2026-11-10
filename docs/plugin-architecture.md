# Plugin runtime architecture

[文档首页](README.md) · [启动与插件运行](startup.md) · [插件开发](plugin-development.md)

The root Cordis `Context` is the only service container. Plugins publish typed services
through `ctx.provide(...)`, resolve declared dependencies with `ctx.require(...)`
or `ctx.get(...)` (optional), and own every effect through their context.

## Dependency rules

1. Contracts, errors, data types and pure functions may be imported normally.
2. A service instance with a lifecycle is always resolved from the runtime
   context. There is no module-level `get_*` / `set_*` fallback.
3. Plugin `setup()` constructs services and injects their dependencies.
4. Importing a package must not create a service instance or register anything.
5. Concrete providers (PostgreSQL persistence, database pool, LLM adapters)
   are plugins; consumers only import the contract and service key.
6. Two Cordis contexts in one process share no service state.

## Service map

| Key | Provider plugin | Consumers |
| --- | --- | --- |
| `database.v1` | `agent-platform.database-postgres` | persistence, settings, agent-config, HTTP/API |
| `agent.sessions.v1` | `agent-platform.session` | persistence, title, recovery, API |
| `agent.session-persistence.v1` | `agent-platform.session-persistence-postgres` | title, recovery, API |
| `agent.session-title.v1` | `agent-platform.session-title` | recovery, agent-runtime |
| `agent.session-recovery.v1` | `agent-platform.session-recovery` | agent-runtime, API |
| `agent.session-projection.v1` | `agent-platform.session-projection` | API/UI adapters |
| `llm.v1` | `agent-platform.llm` (+ provider rows such as `llm-deepseek`) | agent-runtime, session-title, API |
| `unified-tools.v1` | `agent-platform.tool-host` | system-prompt, tool APIs |
| `agent.prompts.v1` | `agent-platform.system-prompt` | agent-runtime, prompt preview API |
| `agent.sandbox.v1` | `agent-platform.sandbox-policy` | agent-runtime |
| `agents.v1` / `tool-bindings.v1` | `agent-platform.agent-config` | agent-runtime, tools, API |
| `settings.v1` | `agent-platform.settings-postgres` | sandbox-tools, API |
| `agent.entry.v1` | `agent-platform.agent-entry` | chat, workflows, headless CLI |
| `chat.v1` | `agent-platform.chat` | HTTP chat, memory views, Xianyu |
| `memory.v1` | `agent-platform.memory` | HTTP memory profiles and debug |
| `workflow.v1` / `workflow.nodes.v1` | `agent-platform.workflow` | Workflow HTTP routes, node-contributing plugins |
| `faq.v1` | `agent-platform.faq` | FAQ HTTP routes |
| `xianyu.v1` | `agent-platform.xianyu` | Xianyu HTTP/WS routes, chat persistence |
| `approval.v1` / `approval.inbox.v1` | `agent-platform.user-approval` | Agent Loop, sandbox tools, HTTP approval routes |
| `plugin-catalog.v1` | `PluginLoader` (native) | plugin inventory |
| `plugin.inventory.v1` | `agent-platform.plugin-inventory` | HTTP `/api/plugins`, frontend boot filter |
| `http.app.v1` | `agent-platform.http-api` | ASGI proxy |

`agent-platform.agent-runtime` requires `agents.v1`, `agent.runs.v1`,
`agent.prompts.v1`, `llm.v1`, `agent.sandbox.v1`, `agent.session-recovery.v1`
and optionally `agent.session-title.v1`. It imports no FastAPI, backend host
adapter or global singleton.

## Session lifecycle

`SessionRecoveryService` is constructed with the runtime's `SessionStore`,
`SessionPersistence` and optional `SessionTitleService`. `prepare_session()` is
a pure orchestration function that receives all three explicitly; it never
looks them up globally. The title service receives the same store/persistence
and the runtime LLM service, so replacing a persistence provider needs no
change in Runtime, Loop or API consumers.

## RPC boundary

Business operations use JSON-RPC 2.0 at `POST /api/rpc`:

```
browser remote.workspace.create(...)
  → packages/api/connection  (JSON-RPC envelope, correlation, cancellation)
  → packages/api/gateway     (explicit method table, Pydantic validation, errors)
  → packages/api/workspace   (WorkspaceController + WorkspaceService)
  → DATABASE / SESSION_* services
```

Controllers register methods in their plugin `setup()` and track the returned
handle; unloading a controller removes exactly its methods. The legacy REST
routes for migrated operations call the same controller service, not a second
implementation. Chat deltas/attach/cancel remain SSE; file transfer remains
HTTP. See [rpc-api.md](rpc-api.md).

## HTTP boundary

`apps/server` is only an ASGI carrier. It starts the plugin runtime on
lifespan, resolves `http.app.v1`, and delegates requests to the FastAPI
application owned by `agent-platform.http-api`. The carrier contains no routes
and no agent assembly.

A headless entry is available for deployments without the HTTP plugin:

```bash
python -m agent_platform_cli run --agent default "你好"
```

It loads the same composition, explicitly removes `agent-platform.http-api`,
resolves `agent.entry.v1` and runs one turn for a configured agent. Returning a fallback reply with no
model credentials is a valid result; it proves the agent path does not depend
on a web server.

## Chat and approval

The agent entry plugin resolves each request through `agents.v1`. It sends
regular agents to `agent.runtime.v1` and owns the configured L1/L2/L3 router
strategy. Chat owns conversation and message storage, live tasks, and stream
snapshots. FastAPI serializes each snapshot and event to SSE. Detaching the
viewer keeps the turn running. A reconnect attaches by session ID, and the
final event follows the message commit.

The approval plugin owns the pending requests and their timeouts. Tools use
`approval.v1` to ask and the HTTP adapter uses `approval.inbox.v1` to list
and resolve requests. Shutdown settles pending requests without granting
permission. Headless mode omits the interactive inbox provider by default.

## Memory

The memory plugin owns conversation compaction, profile extraction, and
cross-session lookups. It uses the existing PostgreSQL tables and the selected
agent's model configuration for the debug endpoint. The debug endpoint previews
extraction without saving profile facts. The Agent Runtime does not register
memory hooks.

## Workflow and node extensions

`agent-platform.workflow` owns workflow CRUD, graph execution and the response
cache. It publishes two services:

- `workflow.v1` — tenant-scoped list/create/get/save/delete/run. The HTTP
  plugin only formats SSE; it has no SQL or LangGraph code.
- `workflow.nodes.v1` — a node-kind registry. The plugin registers `start`,
  `end`, `agent`, `condition` and `router`; any plugin that declares a
  dependency on `workflow.nodes.v1` can register another kind with a handler
  and an optional conditional-edge router.

Node factories receive `NodeContext` (agent entry, agent config, node cache),
so a node kind never imports the workflow service or the host.

## Frontend enablement

Frontend plugins declare their backend identity in `package.json`:

```json
"dsh": {
  "plugin": "agent-platform.workflow",
  "client": { "platform": "web", "inject": ["@app/plugin-shell"] }
}
```

Python plugins with a `web_package` include their browser bundle as package data.
`GET /api/plugins` advertises modules from started packages and the HTTP plugin
serves their scripts. The browser app combines those entries with its bootstrap
shell. A single YAML entry enables a feature's Python and browser code.

## Process entry and boot

The repository has no `backend/` directory. Process concerns live in apps and
boot packages:

| Package | Role |
| --- | --- |
| `apps/server` | ASGI carrier for uvicorn: start runtime, resolve `http.app.v1` |
| `apps/cli` | `agent-platform run` (headless turn) and `agent-platform serve` |
| `packages/boot/app-boot` | composition discovery + `PluginLoader` start/stop |
| `packages/host/plugin-inventory` | `plugin.inventory.v1` projection of started instances |

`PluginLoader` provides `plugin-catalog.v1` natively; the inventory plugin
projects it for the HTTP plugin. MCP rows are loaded by
`agent-platform.mcp-database` after the database plugin starts, so boot never
reads a business table.

The HTTP plugin owns its request-scoped database and service adapters
(`packages/host/http-api/src/db.py`, `services.py`); route modules do not
import an app entry or a host singleton.
