# Agent Platform MCP Client

把任意 MCP server 的工具注册进插件侧 `tools.v1` 注册表的通用插件。发行包名为 `agent-platform-mcp-client`，导入名为 `agent_platform_mcp_client`。

一个配置实例对应一个 MCP server。插件在 `setup()` 连接 server、发现工具、把每个工具注册为 `tools-default` 中的工具；对话期间由 `McpToolExecutor` 把调用转给 MCP `call_tool`。

包内同时提供 `agent-platform.mcp-manager` 插件，发布 `mcp.manager.v1` 控制面：

- `probe(config)`：临时连接并返回工具列表（stdio 会临时拉起探测进程）；
- `add(config)` / `ensure(config)`：运行时连接并注册工具；
- `remove(server_name)` / `reconnect(server_name)`：注销并重连；
- `call(server_name, raw_name, args)`：直接调用已管理连接，transport 失效时重连一次。

静态 `mcp-client` 实例会把连接交给 manager 托管，因此 backend 的 MCP 导入、测试、调用、删除和重连都走这个包，不再保留原生 `MCPToolProvider`。

## 安装

```bash
pip install -r requirements-plugins.txt
```

## 配置

### HTTP / streamable-http

```yaml
version: 1
plugins:
  - id: mcp-builtin
    name: agent-platform.mcp-client
    config:
      server_name: builtin
      transport: http
      url: http://localhost:9001/mcp
      timeout_seconds: 300
```

### stdio

```yaml
  - id: mcp-paper
    name: agent-platform.mcp-client
    config:
      server_name: paper
      transport: stdio
      command: python
      args: ["-m", "agent_platform_paper_mcp.server"]
      timeout_seconds: 300
```

字段：

| 字段 | 说明 |
|---|---|
| `server_name` | 实例名，`[A-Za-z0-9_-]{1,32}`；用于 executor 名 `mcp.<server_name>` |
| `transport` | `http` 或 `stdio` |
| `url` | HTTP 地址 |
| `command` / `args` / `env` | stdio 启动参数 |
| `timeout_seconds` | 连接后的工具调用超时，默认 300 |
| `tool_prefix` | 工具名前缀，默认空；设为 `mcp__<server>__` 可避免跨 server 重名 |

`tool_prefix` 默认为空是刻意的：既有数据库里的 Agent 工具绑定使用 MCP 原始工具名（如 `query_orders`），保持空前缀不会破坏这些绑定。新接入的外部 server 建议显式加前缀。

## 行为

- 启动时连接一次，工具列表静态注册；静态实例的 server 工具列表变更仍需重载配置。
- manager 的 `reconnect()` 会重新连接并刷新工具列表；`call()` 遇到 transport 失效会重连一次再重试。
- 工具调用超时由 `tools-default` 与插件共同约束；取消信号会传递给 MCP 调用。
- MCP 返回 `isError` 时转成 `ToolResult(status="error", error=ToolError(code="mcp.tool_error", ...))`。
- 结果为 `{content, rows, count, structuredContent?}`：`content` 保留 MCP 内容块，`rows` 是文本内容 JSON 解析后的行，兼容原有 MCP 工具调用方。
- 关闭时逆序注销工具、executor，并关闭 MCP session/transport。

## 限制

- 静态 `mcp-client` 实例不订阅 `tools/list_changed`；工具列表变更需要重载配置或调用 manager.reconnect。
- 自动重连目前是“调用失败重连一次”，没有 DeepSeek 那样的指数退避与 attempt budget。
- 不处理 MCP resources/prompts，只注册 tools。
- 一个实例只连一个 server；多个 server 写多个配置条目，或通过 manager 动态添加。
