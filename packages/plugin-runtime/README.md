# Agent Platform Plugin Runtime

独立 Python 包，负责把声明式插件文档变成运行中的插件实例。发行包名为 `agent-platform-plugin-runtime`，导入名为 `agent_platform_plugin_runtime`，Python 版本为 3.12 及以上。

它依赖 [`agent-platform-plugin-sdk`](../plugin-sdk/README.md)，只使用 SDK 的公共契约，不导入 `backend`。运行时负责：读取 YAML、通过 entry point 发现插件包、校验 SDK 版本与插件配置、按服务依赖排序、执行 `setup()`、失败回滚和逆序关闭。它不实现 `tools.v1`；默认实现由独立插件包 [`packages/plugins/tools-default`](../plugins/tools-default/README.md) 提供。运行时也不安装插件或热重载。

设计上参考了 `deepseek-harness` 的 Cordis loader 与 app-boot，但配置语义和生命周期细节以本仓库的 SDK 契约为准。

插件是包导出的装配与生命周期单元，一个实例可以提供服务、注册 **0～N 个工具**，
工具名、执行器名与插件实例 id 各自独立。`tools-default` 提供注册表服务；
`skill-tools` 一个实例注册 `skill` 和 `skill_install`；`mcp-client` 一个实例接入
一台服务器的整组工具。所有注册通过 `ctx.track(...)` 归属插件，失败时整组回滚。
应用的默认清单由 [`platform-default`](../platform-default/README.md) 包提供，
通用 PluginRuntime 不硬编码任何工具或默认插件。

## 安装与验证

在仓库根目录执行：

```bash
# 一次安装插件栈：
python -m pip install -r requirements-plugins.txt
# 或者分别安装（runtime 测试需要 dev 依赖）：
python -m pip install -e "./packages/plugin-sdk[dev]" -e "./packages/plugin-runtime[dev]"
python -m unittest discover -s packages/plugin-runtime/tests -v
```

在 `packages/plugin-runtime` 下执行：

```bash
python -m mypy
python -m build
```

## 快速开始

仓库里有一个可运行的真实示例：[`examples/`](examples/README.md)，用 entry point 发现插件并调用工具。下面是它的最小形态。

插件文档（`plugins.yaml`）：

```yaml
version: 1
plugins:
  - id: tools
    name: agent-platform.tools-default
    config: {}
  - id: echo
    name: example.echo
    config:
      prefix: "收到："
```

宿主代码：

```python
from agent_platform_plugin_sdk import ExecutionScope, TOOLS, ToolCall, ToolContext
from agent_platform_plugin_runtime import PluginRuntime

runtime = PluginRuntime.from_yaml("plugins.yaml")
await runtime.start()

tools = runtime.require(TOOLS)
result = await tools.execute(
    ToolCall(call_id="1", name="echo", arguments={"text": "hello"}),
    ToolContext(
        scope=ExecutionScope(tenant_id=1, agent_key="assistant"),
        visible_tool_names=frozenset({"echo"}),
    ),
)

await runtime.aclose()
```

`tools-default` 是推荐做法：注册表和执行权都在插件侧。宿主也可以用 `host_services` 自己提供 `tools.v1`：

```python
runtime = PluginRuntime.from_yaml(
    "plugins.yaml",
    host_services={TOOLS: my_tools_service},
)
```

宿主服务是借用的：它们可以满足插件的 `requires`，但运行时不会关闭它们，插件也不能用同一个 `ServiceRef` 再次提供。此时 YAML 里不要再启用 `agent-platform.tools-default`，否则会触发服务冲突。

插件包通过自己的 `pyproject.toml` 暴露入口：

```toml
[project.entry-points."agent_platform.plugins"]
"example.echo" = "example_echo:EchoPlugin"
```

入口名必须与 `PluginSpec.name` 一致。每个配置条目都会调用一次入口工厂获得独立实例；同一实现可以配置多个实例。

## 配置格式

| 字段 | 说明 |
|---|---|
| `version` | 必须是整数 `1` |
| `plugins[].id` | 配置实例标识，全局唯一（包括 `disabled` 条目） |
| `plugins[].name` | entry point 名，也是实现的 `PluginSpec.name` |
| `plugins[].disabled` | `true` 时不发现、不校验、不启动，也不能满足依赖 |
| `plugins[].config` | JSON 对象，先由 SDK 校验为 JSON，再由插件的 `config_model` 校验 |

当前只支持平铺列表，不支持参考项目里的 group/include 嵌套；这是按 SDK 的 `PluginConfiguration` 实现的。

## 预检规则

在任何 `setup()` 执行之前，运行时按顺序完成：

1. 解析并校验文档形状（未知字段、非法标识符、重复实例 id 都会被拒绝）。
2. 对每个启用的条目发现 entry point，导入并实例化插件；入口名与 `spec.name` 不一致、返回的是类而不是实例、缺少异步 `setup()` 都会失败。
3. 检查 `PluginSpec.sdk_api_version == 1`（精确匹配），然后校验插件的 `config_model`。
4. 收集所有 `provides`，拒绝以下冲突：
   - 两个插件提供同一个 `ServiceRef`；
   - 插件提供宿主已经提供的 `ServiceRef`。
5. 检查每个 `requires`：
   - 宿主服务或启用的插件提供者存在 → 满足；
   - 缺失且 `optional=False` → `MissingServiceError`；
   - 缺失且 `optional=True` → 允许，`ctx.get()` 返回 `None`。
6. 用提供者 → 消费者的边做拓扑排序。缺失依赖、自依赖和环（包括只由可选依赖形成的环）都会在启动前失败。配置顺序只用于同层插件的稳定排序。

## 生命周期语义

- 提供者在消费者之前 `setup()`；运行时的服务表在启动时创建。
- 每个插件拿到独立的 `RuntimePluginContext`：
  - `require(key)` / `get(key)` 只能访问 `spec.requires` 中声明过的服务；
  - `provide(key, service)` 只能发布 `spec.provides` 中声明过的服务，并自动登记撤销；
  - `track(registration)` 接管外部注册句柄；
  - `on_dispose(callback, label=...)` 登记同步或异步清理。
- `setup()` 失败或被取消时，先关闭失败插件自己的上下文，再按逆序关闭已启动插件，然后重新抛出原始异常；回滚失败会以 note 的形式附加到原异常上。
- `aclose()` 幂等，先拒绝新工作，再按逆序尝试每一个清理；单项失败不会中断其余清理，最后把所有失败放进 `BaseExceptionGroup` 抛出。无论清理是否失败，运行时状态都会进入 `CLOSED`。
- 注册句柄关闭幂等；过期句柄不会误删同名的新注册。
- 运行时状态：`NEW → STARTING → RUNNING → STOPPING → CLOSED`。`start()` 失败后回到 `NEW`，仍可修复配置后重试；关闭后的运行时拒绝再次启动。
- 生命周期方法不支持并发调用，宿主应串行化 `start()` 与 `aclose()`。

## 公共 API

| API | 用途 |
|---|---|
| `PluginRuntime(config, *, catalog=..., host_services=...)` | 用已验证文档或 JSON 形状的 mapping 创建运行时 |
| `PluginRuntime.from_yaml(path, ...)` | 读取 YAML 文件创建运行时 |
| `await runtime.start()` | 预检、排序并启动全部启用插件 |
| `await runtime.aclose()` | 逆序关闭并汇总清理失败 |
| `runtime.require(key)` | 解析插件或宿主服务，仅在 `RUNNING` 状态可用 |
| `runtime.plugins` | 上次成功启动的实例元数据（`instance_id`、`name`、`version`、`spec`） |
| `runtime.state` / `runtime.config` | 当前状态与已校验配置 |
| `EntryPointCatalog` | 从 `agent_platform.plugins` 组发现已安装插件 |
| `MappingCatalog` | 用静态工厂映射嵌入插件，主要用于测试 |
| `parse_config` / `parse_yaml` / `load_yaml_config` | 文档校验与 YAML 读取 |

错误码：

| 异常 | 码 |
|---|---|
| `ConfigurationError` | `plugin_runtime.config` |
| `DiscoveryError` | `plugin_runtime.discovery` |
| `MissingServiceError` | `plugin_runtime.missing_service` |
| `ServiceConflictError` | `plugin_runtime.service_conflict` |
| `DependencyCycleError` | `plugin_runtime.dependency_cycle` |
| `LifecycleError` | `plugin_runtime.lifecycle` |
| `UndeclaredServiceError` | `plugin_runtime.undeclared_service` |

SDK 自己的错误（`PluginCompatibilityError`、`RegistrationConflictError`、`ServiceClosedError`、`ServiceUnavailableError`）保持原样抛出。

## 后端接入

后端通过 `backend/plugin_host.py` 装配**单轨**工具运行时：

- `tools-default` 总是被加载（配置里没写时自动补上），它是唯一的 `tools.v1` 注册表。
- MCP 工具实现位于 [`packages/tools/`](../tools/README.md)；backend 启动后会把 `mcp_servers` 表里的每个 server 自动转换成 `agent-platform.mcp-client` 插件实例，由插件连接 server 并注册工具。`PLUGIN_MCP_AUTO=false` 可关闭自动装配。
- sandbox / skill 等原生工具在启动时注册进同一个注册表；后续动态注册/注销（如沙箱能力开关、远程 MCP 懒加载）通过 Registry 变更监听同步。插件已注册的同名 MCP 工具优先，未被插件覆盖的原生 MCP 工具仍走 `backend.native` 兜底。
- AgentLoop 的 `ToolScheduler`、系统提示词的 `_platform_tool_provider`、`/api/mcp/tools/*` 都只使用单轨运行时；backend 的 `ToolRegistry` 只作为原生工具来源，由单轨运行时同步，不再是 agent-facing 的第二份注册表。
- backend 的沙箱策略、审批通道和事件出口通过 `ToolContext.host_context` 传给原生 executor；该字段不参与序列化，插件工具不应依赖它。
- 插件配置按以下顺序发现：`PLUGIN_CONFIG` → `./plugins.yaml` → `./config/plugins.yaml`；都没有时只加载 `tools-default`。
- 依赖缺失或装配失败时记录 warning，回退到旧的原生 ToolRuntime。
- 插件工具会出现在 `/api/mcp/tools/all`，来源标签为 `plugin`；通过 `PUT /api/tools/bindings/{agent_key}` 绑定后，模型下一轮就能看到它。

Docker 镜像已经安装 SDK、runtime、tools-default 和示例插件，可以直接启用：

```bash
PLUGIN_CONFIG=/app/packages/plugin-runtime/examples/plugins.yaml \
  docker compose up -d backend
```

本地直接运行后端时，先安装 `packages/plugin-sdk`、`packages/plugin-runtime`、`packages/plugins/tools-default` 与插件包。

当前后端适配的边界：

- 单轨注册表包含直接注册的工具；tools-default 的 provider 懒加载/scope 发现工具可以执行，但暂不进入 `/api/mcp/tools/all` 的静态列表。
- 插件工具是进程内可信扩展，不经过沙箱和审批；需要这些能力的工具仍应走 `sandbox` / MCP。
- 插件启停是进程级的，暂不支持按租户启用/禁用。
- 插件工具必须先手工绑定到 Agent，不会自动授予权限。

## 当前限制

- 不支持热重载、运行时增删条目或配置更新。
- 不负责安装、升级、市场或注册表操作。
- 运行时本身不提供 `tools.v1` 默认实现；默认实现是独立插件包 `tools-default`，也可以由宿主注入。
- 不读取嵌套 group/include，不实现参考项目的模块热替换。
- 不执行沙箱、审批或租户权限判断；这些仍由宿主和具体能力实现负责。插件与宿主同进程，属于可信扩展，不是代码沙箱。
- 包尚未发布到索引，开发时使用仓库内的 editable 安装。
