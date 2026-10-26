# Agent Platform Plugin SDK

独立 Python 包，定义插件与宿主、能力实现与消费者之间的公共协议。发行包名为 `agent-platform-plugin-sdk`，导入名为 `agent_platform_plugin_sdk`，Python 版本为 3.12 及以上。

这是 SDK API 1 的第一版，包含插件生命周期、声明式配置、类型化服务引用和 `tools.v1`。SDK 不依赖 `backend`，不加载插件、不连接数据库、不解析 YAML，也不启动 Agent。YAML 读取、entry point 发现、依赖排序和生命周期编排位于独立包 [`packages/plugin-runtime`](../plugin-runtime/README.md)；默认工具实现仍由后续包提供。现有后端类型与 SDK 类型尚未迁移互通；适配时需显式转换并保留当前沙箱、审批和租户约束。

## 安装与验证

在仓库根目录执行：

```powershell
python -m pip install -e "./packages/plugin-sdk[dev]"
python -m unittest discover -s packages/plugin-sdk/tests -v
```

在 `packages/plugin-sdk` 下执行：

```powershell
python -m mypy
python -m build
```

包携带 `py.typed`，供其他独立插件包进行类型检查。[Echo 示例](examples/tool_plugin.py)只依赖 SDK，可由宿主加载，不在导入时启动工作。

## 两层契约

| 层次 | 公共类型 | 用途 |
|---|---|---|
| 插件生命周期 | `Plugin[ConfigT]`、`PluginSpec`、`PluginContext`、`Registration` | 声明依赖与配置、初始化、记录归属与清理 |
| 服务引用 | `ServiceRef`、`ServiceKey[T]`、`ServiceRequirement` | 按作用域解析相同能力协议的实现 |
| 工具能力 | `ToolsService`、`ToolProvider`、`ToolExecutor`、`TOOLS` | 替换工具服务、接入来源和执行器 |
| 数据边界 | `ExecutionScope`、`ToolCall`、`ToolContext`、`ToolResult` | 验证身份、参数对象、结果和错误结构 |

`ServiceRef(name="tools", api_version=1)` 标识 `tools.v1`。`TOOLS` 是它的规范类型化引用；消费者从 SDK 导入同一个 key，通过 `ctx.require(TOOLS)` 得到 `ToolsService`，不得导入默认实现。`ServiceKey` 的泛型保持不变性，防止静态类型推导将错误实现放宽成 `object`。

SDK 不使用 `runtime_checkable` 冒充完整兼容性检查。`Protocol` 靠 mypy 等工具检查签名，Pydantic 检查数据，行为还需要共享契约测试及实现自己的测试。

## 声明与包入口

```python
from agent_platform_plugin_sdk import TOOLS, PluginSpec, ServiceRequirement

spec = PluginSpec(
    name="example.echo",
    version="0.1.0",
    requires=(ServiceRequirement(service=TOOLS.ref),),
)
```

提供 `tools.v1` 的实现将 `provides=(TOOLS.ref,)` 放入声明。依赖项可以标为 `optional=True`；缺失允许返回 `None`，不兼容、失败或未声明的依赖不能被伪装成正常缺失。同一宿主作用域内，相同 `ServiceRef` 只允许一个提供者。

插件包通过自己的 `pyproject.toml` 提供无参数插件类入口：

```toml
[project.entry-points."agent_platform.plugins"]
"example.echo" = "example_echo:EchoPlugin"
```

入口名称必须与 `spec.name` 一致。以下配置可用 `PluginConfiguration.model_validate(...)` 校验；YAML 文件读取与 entry point 发现属于未来的 runtime：

```yaml
version: 1
plugins:
  - id: tools
    name: agent-platform.tools-default
    config: {}
  - id: echo
    name: example.echo
    disabled: false
    config:
      prefix: "收到："
```

`id` 是配置实例标识；`name` 是实现入口标识。同一实现可以有不同实例，但服务提供仍受作用域唯一性约束。`config` 先校验为 JSON 对象，再由插件的 `config_model` 校验具体字段。

包发布版本、`PluginSpec.sdk_api_version`、`ServiceRef.api_version` 分别管理，不能互相替代。包版本采用 PEP 440。当前 SDK API 和服务协议都按正整数主版本精确匹配：宿主在 setup 前调用 `ensure_sdk_compatible()`，并检查服务引用；未来服务主版本可并存，但不自动回退或跨版本转换。

## 宿主必须兑现的生命周期

1. 验证入口、SDK API、插件配置和声明的服务依赖，再执行 `setup()`；检查重复实例、缺失依赖、冲突和依赖环。
2. `ctx.provide()` 自动记录服务撤销。外部注册句柄通过 `ctx.track()` 归属到插件；连接等资源通过 `ctx.on_dispose()` 登记同步或异步清理。插件导入时不得注册能力或启动后台任务。
3. setup 失败或被取消时回滚所有已登记效果。关闭时先拒绝新工作，等待或取消在途工作，再按逆序清理；某项清理失败也要继续尝试其余清理，并汇总报告失败。
4. 句柄关闭必须幂等；过期句柄不得删除同名的新注册。清理完成后不能遗留后台写入。卸载不删除用户配置、凭据或持久会话。

插件上下文管理可信的同进程扩展，不是代码沙箱。运行时的全局加载、租户启用和 Agent 绑定需要分别处理，scope 也不代表访问已被授权。

## 工具行为契约

- `ToolsService` 管注册、调用时的可见性校验、解析、派发和超时；调度器负责并发池与独占屏障，AgentLoop 负责 Session 事实记录。`execution_mode` 必须保留给调度器。
- 工具注册不自动授予 Agent 权限。执行上下文由宿主构造；模型参数中的 `tenant_id` 等字段不能覆盖 `ExecutionScope`。空可见集合拒绝所有工具，Provider 的发现、懒加载也必须使用同一 scope。
- 已知执行失败返回 `ToolResult(status="error", error=ToolError(...))`；业务错误码可扩展。标准码包括 `tool.denied`、`tool.not_found`、`tool.timeout`、`tool.unavailable`，参数不符合 schema 使用 `tool.invalid_arguments`。
- `approval.v1` / `settings.v1` / `agents.v1` 是正式的宿主服务契约（`APPROVAL` / `SETTINGS` / `AGENTS`），插件通过 `ctx.require()` 取用；实现留在宿主。
- `ToolContext.host_context` 是不参与序列化的宿主桥，当前只用于把**沙箱策略/事件出口**传给 native-capability 适配器；模型参数永远不能提供它。正式的 `sandbox.v1` 策略契约仍需后续定义。
- `asyncio.CancelledError` 必须传播。工具超时与调用方的 `time.monotonic()` 绝对 deadline 取较早者，超时后等待执行器清理再返回。不得自动重试可能已产生副作用的调用。
- `aclose()` 阻止新调用并清理在途执行；关闭后调用返回 `tool.unavailable`，新增注册抛 `ServiceClosedError`。重复注册抛 `RegistrationConflictError`。
- Pydantic 模型只做浅冻结；跨异步边界前由宿主制作 JSON 快照。这里的数据模型不定义持久 Session 格式，不将 Provider 凭据放进工具描述或错误详情。

实现包可运行 SDK 自带的基线验证器：

```python
from agent_platform_plugin_sdk.testing import verify_tools_service

# factory(scope) 每次创建独立服务，并在测试绑定仓库允许 contract.* 测试工具。
passed = await verify_tools_service(factory)
```

它验证上下文、可见性、查找、重复注册、句柄所有权、取消、deadline 和关闭语义。实现还需要自己的 Provider 作用域、JSON Schema、并发关闭、审批、沙箱和故障测试；基线通过不代表所有行为已被证明兼容。
