# Agent 插件

参考本地 DeepSeek Harness 的 `dsh-agent` / `dsh-agent-loop` 分层：公共 Agent 服务和具体循环实现分别由插件提供。

| 包 | 入口 | 职责 |
| --- | --- | --- |
| `core/` | `agent-platform.agents` | 提供 `agent.runs.v1`，管理工厂、活动句柄、会话单飞和运行作用域 |
| `loop/` | `agent-platform.agent-loop` | 注册默认工厂，实现 inbox、LLM → 工具 → LLM、流式装配、重试、取消和执行限制 |
| `runtime/` | `agent-platform.agent-runtime` | 提供 `agent.runtime.v1` 和 `agent.extensions.v1`；装配提示词、技能等扩展、LLM 和 Loop，管理一次 reply 的完整生命周期 |

默认装配在 `packages/plugin/default/src/plugins.yaml`，本地和 Docker 都加载它们。现有安装更新一次：

```bash
python -m pip install -r requirements-plugins.txt
python minidsh.py web
```

循环实现位于 `loop/src/agent_loop.py`，运行时实现位于 `runtime/src/runtime.py`。三个插件均使用平铺 `src/` 和 `pyproject.toml` 的包名映射，不导入 `backend`。依赖的 LLM 公共类型位于 `packages/llm/core`；会话事件、消息派生、trace 投影和工具事实记录位于 `packages/session/core`。

实际调用链：

```text
后端请求 → runtime.require(AGENT_RUNTIME).reply(...)
         → 运行时插件装配提示词 / 工具 / 扩展钩子 / LLM 客户端
         → ctx.require(AGENT_RUNS).open(...)
         → 插件工厂绑定 LoopContext(ctx, llm, policy)，创建循环
         → followup → when_idle → answer_text
         → loop_ctx.tools 执行工具，Session 记录事实
         → 运行时插件等待宿主检查点保存、清理监听器
         → 退出运行作用域，释放活动句柄
```

后端通过 `packages/agent/runtime/src/runtime.py` 查公共服务，不再收集 pre-step 钩子或创建 LoopHooks。
`runtime/src/extensions.py` 的扩展注册表由运行时插件创建；skill-tools 通过 `ctx.require(AGENT_EXTENSIONS).register(...)` 登记扩展。
运行时插件收集这些扩展，把合并后的 pre-step 钩子交给循环。注册表按 Loader 隔离，卸载后撤销。

提示词、LLM、会话恢复/标题、沙箱策略和智能体配置都由各自插件通过服务表提供，
Runtime 在 `ctx.require(...)` 中解析；所有服务都由插件运行时注入
这类中转适配器。所有工具仍来自同一个 `tools.v1` 注册表。

`loop/src/context.py` 定义 `LoopContext`，保留插件启动时收到的原生 Cordis `Context`。
`tools`、`tool_catalog`、`approval` 属性在使用时从这个上下文的服务表解析，
没有复制注册表，也不把服务分别塞进 Loop 构造参数。
LLM 客户端和会话策略由运行时服务为每次运行创建，绑定到该次运行的上下文，避免不同会话串配置。

对照 DSH `agent.ts` 保存 `loopCtx`、`tool-calls.ts` 访问 `ctx.tools` 的方式：

```python
# 插件启动：工厂保存原始 ctx
runs.register_factory(LoopFactory(ctx, config))

# 工厂创建：绑定本次运行的客户端，传入循环
loop_ctx = LoopContext(plugin_ctx=ctx, llm=client)
loop = AgentLoop(loop_ctx, ...)

# AgentLoop.__init__
self.loop_ctx = ctx

# 循环请求模型
response = await self.loop_ctx.llm.complete(request)

# tool_calls.py：调度器持有同一个 loop_ctx，通过工具服务派发
return await ToolsExecutionAdapter(self.loop_ctx.tools).execute(tool_name, args, context)
```

调度器仍负责并发、独占屏障和结果顺序；`ToolsExecutionAdapter` 负责 SDK 调用上下文与工具生命周期事件的转换。
工具执行、审批和沙箱策略都从 `loop_ctx` 访问。Loop 构造函数只接收这个上下文及运行参数；
`llm`、`approval`、`tool_runtime`、`tool_mode_resolver` 不再是单独的构造参数。

插件消费者声明对 `AGENT_RUNS.ref` 的依赖，然后取得服务：

```python
from agent_platform_agents import AGENT_RUNS

runs = ctx.require(AGENT_RUNS)
async with runs.open(
    key="assistant", tenant_id=1, session=session,
    llm=client, model="your-model", llm_params={}, tool_schemas=[],
) as agent:
    agent.followup("你好")
    await agent.when_idle()
    answer = agent.answer_text()
```

`runs.get(session_id)` 返回同一个活动句柄，可调用 `steer`、`followup`、`inject` 或 `cancel`。同一运行时内，同一会话只能有一个运行作用域；作用域覆盖宿主的检查点清理，避免上一轮尚未保存时下一轮进入。不同运行时各自持有服务实例，没有进程级循环登记表。

`config/plugins.yaml` 可覆盖默认实例：

```yaml
version: 1
plugins:
  - id: agent-loop
    name: agent-platform.agent-loop
    config:
      max_parallel_tools: 2
```

智能体自身显式设置的 `max_parallel_tools` 优先，否则使用插件配置，默认 4。把该条设为 `disabled: true` 后没有循环工厂，对话会报告服务不可用。替换实现时，禁用默认循环、加载自己的插件，并通过 `runs.register_factory(factory)` 注册；工厂返回满足 `Agent` 协议的对象，不需要修改后端。

插件必须把工厂注册交给生命周期：

```python
registration = runs.register_factory(factory)
ctx.on_quiesce(registration.aclose, label="stop custom driver")
ctx.track(registration)
```

运行时关闭或 setup 回滚时，先执行所有 `on_quiesce`：禁止创建和投递新工作，取消活动循环，等待工具收口和宿主作用域退出；之后才逆序释放各插件的工具、服务和其他效果。离开作用域的旧句柄不能重新唤醒循环。

验证：

```bash
python -m unittest discover -s packages/agent/loop/tests -v
python -m unittest discover -s packages/agent/runtime/tests -v
python -m unittest discover -s packages/framework/loader/tests -v
python -m pytest tests/integration/agent_runtime/test_agent_loop.py -q
python -m pytest tests/integration/agent_runtime/test_agent_runtime_prompt.py -q
python -m pytest tests/integration/session/test_checkpoint.py -q
```
