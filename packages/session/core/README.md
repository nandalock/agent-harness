# Session core

会话事实层，现在同时是插件 `agent-platform.session`：

- 事件模型：`SessionEvent` / `SessionHeader` / `Session` / `SurfaceManager`
- 内存热区：`SessionStore`（插件启动时通过 `ctx.provide(SESSIONS, ...)` 提供）
- 检查点协议、工具调用/进度记录、崩溃尾部修复
- `SESSIONS` / `agent.sessions.v1` 服务

持久化、标题和投影不再由本包内置：

| 能力 | 包 |
| --- | --- |
| 持久化 seam | `packages/session/persistence` |
| PostgreSQL 持久化插件 | `packages/session/persistence-postgres` |
| 标题插件 | `packages/session/title` |
| checkpoint / recovery 插件 | `packages/session/recovery` |
| trace / trajectory / sandbox 投影 | `packages/session/projection` |

后端不再保留兼容 shim：所有调用方直接导入 `agent_platform_session` 及其兄弟包，
`tests/integration/session/` 只放跨包集成测试。PostgreSQL 实现位于持久化插件包，后端通过
`DATABASE` 服务注入连接池。
