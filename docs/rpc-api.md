# RPC API

Business operations are exposed as JSON-RPC 2.0 over a single HTTP endpoint,
`POST /api/rpc`. The browser SDK in `packages/client/legacy/lib/remote/` wraps
request ids, tenant headers, typed params/results and errors; pages do not build
business REST URLs.

## Call chain

```
remote.workspace.sessions.create(params)
  → Connection (RpcConnection.dispatch_json)
  → Gateway (method lookup + Pydantic validation + context)
  → WorkspaceController
  → WorkspaceService (DATABASE / SESSION_PERSISTENCE / SESSION_TITLE)
```

`Connection`/`Gateway`/controllers are plugins. Registering a controller method
returns a lifecycle handle tracked by that plugin context, so unloading the
plugin removes its methods. Each `Loader` owns a separate gateway and
method table.

## Envelope

Request:

```json
{"jsonrpc":"2.0","id":"request-1","method":"workspace.projects.create",
 "params":{"path":"D:/my-project"}}
```

Success and failure:

```json
{"jsonrpc":"2.0","id":"request-1","result":{"created":true,"project":{"id":1}}}
{"jsonrpc":"2.0","id":"request-1","error":{"code":-32000,
 "message":"项目不存在: 1","data":{"code":"workspace/not-found","details":{}}}}
```

Codes: `-32700` parse, `-32600` invalid request, `-32601` unknown method,
`-32602` invalid params, `-32603` internal (message never contains the original
exception), `-32000` business error (`error.data.code` is stable), `-32800`
cancelled. Tenant comes from `X-Tenant-ID` (default `1`), optional session from
`X-Session-ID`.

## Migrated methods

| Method | Controller |
| --- | --- |
| `workspace.sessions.list/create/rename` | Workspace |
| `workspace.projects.list/create/update/delete` | Workspace |
| `workspace.folder.ensure` | Workspace |
| `workspace.files.list/create` | Workspace |
| `agent.list/create/getConfig/saveConfig` | Agent |
| `session.recovery/trajectory` | Session |
| `session.sandboxMode.get/set` | Session |

TypeScript types are generated from the Pydantic contracts:

```bash
python scripts/generate_rpc_contracts.py
```

The generated file is checked by `packages/api/workspace/tests/test_contracts_generated.py`.

## Streaming and file endpoints

Chat deltas, run attach/cancel and approvals remain dedicated HTTP/SSE routes;
JSON-RPC is unary. File preview/download/upload, folder picker, health and static
content also remain HTTP. Streaming and unary paths share the same controllers
and business services where they overlap (session recovery, sandbox mode,
workspace state).

## Legacy REST during migration

For each migrated operation the old REST route is a thin adapter over the same
controller service (`packages/host/http-api/src/routes/workspace.py`,
`packages/host/http-api/src/routes/agents.py`). There is no second business
implementation. Routes not yet migrated still use their existing HTTP handlers:

- chat streaming / live attach / cancel / steer, approvals, router route-test;
- skills catalog, tool bindings, sandbox capability switches;
- MCP, workflow, memory, FAQ, auth, xianyu administration;
- workspace file preview/download/upload, server-side browse, native folder picker;
- agent L1 keyword CRUD.

The HTTP/API plugin can be removed from the composition without affecting the
agent runtime; `python -m agent_platform_cli` runs a turn with no HTTP server.
