# Agent Platform Tools Default

`tools.v1` 的默认进程内实现，以普通插件包的形式提供。发行包名为 `agent-platform-tools-default`，导入名为 `agent_platform_tools_default`，Python 版本为 3.12 及以上。

它解决的问题是“工具注册表归谁”：注册、可见性、deadline、错误码和关闭语义都在这个插件里，工具插件只负责注册 executor 和工具描述。宿主（包括 backend）通过 `runtime.require(TOOLS)` 使用它，而不是自己维护一份工具注册表。

## 安装与验证

```bash
python -m pip install -e "./packages/plugin-sdk[dev]" -e "./packages/plugins/tools-default[dev]"
python -m unittest discover -s packages/plugins/tools-default/tests -v
cd packages/plugins/tools-default && python -m mypy
```

## 启用

插件包通过 entry point 暴露：

```toml
[project.entry-points."agent_platform.plugins"]
"agent-platform.tools-default" = "agent_platform_tools_default:ToolsDefaultPlugin"
```

在插件 YAML 中启用它，并让工具插件依赖它：

```yaml
version: 1
plugins:
  - id: tools
    name: agent-platform.tools-default
  - id: echo
    name: example.echo
    config:
      prefix: "收到："
```

运行时按依赖排序，先启动 `tools-default`，再启动声明 `requires=(TOOLS.ref,)` 的工具插件。工具插件在 `setup()` 里：

```python
tools = ctx.require(TOOLS)
ctx.track(tools.register_executor("example.echo", EchoExecutor()))
ctx.track(tools.register_tool(ToolDescriptor(...)))
```

宿主侧：

```python
tools = runtime.require(TOOLS)
result = await tools.execute(call, ToolContext(...))
```

## 公共接口

插件提供两个服务引用：

| 服务 | 用途 |
|---|---|
| `TOOLS` (`tools.v1`) | 标准 `ToolsService`：注册、执行、关闭 |
| `TOOL_CATALOG` (`tools.catalog.v1`) | 宿主快照：`descriptors()` / `has_tool()`，供 UI、绑定和镜像使用 |

`TOOL_CATALOG` 是 tools-default 的扩展，不属于 SDK 的 `tools.v1` 契约；它只返回**直接注册**的工具，不包含 provider 懒加载/scope 发现的结果。

实现行为：

- 重复工具、executor、provider 注册抛 `RegistrationConflictError`；
- 关闭后的服务拒绝注册（`ServiceClosedError`），执行返回 `tool.unavailable`；
- 调用前检查 `visible_tool_names`，空集合拒绝所有工具；
- deadline 取调用方与 `ToolDescriptor.timeout_seconds` 中较早者；已过期不会进入 executor；
- 执行器异常归一化为 `tool.unavailable`，`CancelledError` 继续传播；不自动重试；
- `aclose()` 幂等。

`verify_tools_service` 的完整基线套件在该实现上通过。

## 后端单轨

backend 启动时总是加载本插件，并把它作为唯一的 agent-facing 工具注册表：

- `UnifiedToolsRuntime` 把 MCP / sandbox / skill 等原生工具注册进本服务；
- AgentLoop 的调度器、系统提示词和工具列表都经 `TOOLS` 读取和执行；
- backend 的沙箱策略、审批和事件出口通过 `ToolContext.host_context` 传给原生 executor；
- 插件工具与原生工具共用同一套可见性、超时和关闭语义。

backend 依赖缺失或装配失败时会回退到旧的原生 ToolRuntime，但正常部署（Docker 镜像已安装本包）走单轨。

## 当前限制

- 只做进程内工具；不包含 MCP transport、沙箱或审批。
- provider 工具可以参与 `list_for_agent` / `lazy_load`，但宿主镜像只包含直接注册的工具。
- 没有热重载；插件注册在 `setup()` 期间完成。
- 包尚未发布到索引，使用仓库内 editable 安装。
