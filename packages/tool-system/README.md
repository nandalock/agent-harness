# Agent Platform Tool System

原生工具系统的纯核心：`ToolDescriptor`、`ToolContext`、工具事件、`ToolRegistry`、`ToolRuntime`。发行包名为 `agent-platform-tool-system`，导入名为 `agent_platform_tool_system`。

这个包不导入 `backend`：

- 工具来源通过 `ToolProvider` 注入；包只自带 `BuiltinToolProvider`；
- executor 通过 `ToolRuntime(executors={...})` 注入；
- Agent 绑定通过 `configure_bindings(fn)` 注入；
- 沙箱策略和审批通道在 `ToolContext` 中是不透明字段。

宿主适配不在本包内：

- `packages/tool-host`：把宿主 `ToolContext` 接到 `tools.v1`，并提供调度器默认值；
- `packages/plugins/mcp-client`：MCP 连接、工具发现、动态管理、探测与重连；
- `packages/sandbox`：沙箱实现与执行器；
- `packages/plugins/skill-tools` / `sandbox-tools`：技能与沙箱工具插件。

backend 不再保留原生工具注册表或 MCP executor。
