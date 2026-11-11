# minidsh-cordis

可独立安装的 Python 插件内核。`Context` 是运行入口，`Fiber` 管理一个插件实例。每次激活都创建新的插件上下文，服务和回调跟随这次激活释放。

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

## 从两个插件开始

```python
import asyncio

from minidsh_cordis import Context, EventKey, FiberState, Plugin, ServiceKey

PREFIX: ServiceKey[str] = ServiceKey("prefix")
BEFORE_SEND: EventKey[str] = EventKey("before-send")


def consumer(ctx, config):
    prefix = ctx.require(PREFIX)
    ctx.on(BEFORE_SEND, lambda text: prefix + text)


def provider(ctx, config):
    ctx.provide(PREFIX, config)


async def main():
    root = Context()
    try:
        use = await root.plugin(Plugin(consumer, requires=(PREFIX,)), id="consumer", config=None)
        assert use.state is FiberState.PENDING

        source = await root.plugin(Plugin(provider, provides=(PREFIX,)), id="provider", config="Hello, ")
        assert use.state is FiberState.ACTIVE
        assert await root.waterfall(BEFORE_SEND, "Cordis") == "Hello, Cordis"

        await source.aclose()
        assert use.state is FiberState.PENDING
        assert await root.waterfall(BEFORE_SEND, "Cordis") == "Cordis"
    finally:
        await root.aclose()


asyncio.run(main())
```

## 事件

插件通过 `ctx.on(event, handler)` 注册监听器。注册返回可调用 `aclose()` 的句柄，Fiber 卸载时也会自动注销。使用 `ctx.once()` 时，监听器在首次执行前就会注销。

| 调用 | 行为 |
| --- | --- |
| `ctx.emit(event, value)` | 按注册顺序同步通知，忽略返回值 |
| `await ctx.parallel(event, value)` | 并发执行，等待所有监听器结束后汇总异常 |
| `await ctx.serial(event, value)` | 按顺序等待，返回第一个既非 `None` 也非 `False` 的结果 |
| `ctx.bail(event, value)` | 同步按顺序执行，使用与 `serial()` 相同的提前结束规则 |
| `await ctx.waterfall(event, value)` | 把每个监听器的返回值交给下一个监听器 |
| `await ctx.waterfall_next(event, value, terminal)` | 调用通过 `ctx.on_middleware()` 注册的中间件，由 `next()` 推进 |

`emit()` 和 `bail()` 要求同步监听器。中间件可以在 `await next_step()` 前后执行逻辑，也可以直接返回以截断后续调用。每层中间件须在当前任务内等待 `next_step()`，且最多调用一次。所有中间件都继续时，最后执行 `terminal(value)`。

```python
def setup(ctx, config):
    async def wrap(text, next_step):
        return f"[{await next_step()}]"

    ctx.on_middleware(BEFORE_SEND, wrap)

# 注册插件后，派发端可以调用
assert await root.waterfall_next(BEFORE_SEND, "hello", str.upper) == "[HELLO]"
```

现有变换链可以继续使用。需要中间件语义时，按事件迁移，把监听逻辑改写为 `on_middleware()`，再把派发端切换到 `waterfall_next()` 并传入默认处理函数。两种注册可以暂时共用一个事件键，切换完成后再删除对应的旧注册。

## 生命周期

[`Context`](src/context.py) 提供插件使用的 `ctx` 接口并检查作用域。
[`RegistryService`](src/registry.py) 管理插件实例，并串行处理启动、卸载和回滚。
[`Fiber`](src/fiber.py) 检查所需服务是否可用，执行单个实例的 `setup()`，并管理这次激活的资源清理。
[`ReflectService`](src/reflect.py) 按服务键索引提供方与订阅者，在 `setup()` 成功后发布服务，并把变化交给相关 Fiber 处理。

- `await root.plugin(...)` 登记插件并等待本次可运行的实例完成启动。依赖缺失时，Fiber 保持 `PENDING`，可以用 `waiting_for` 查看缺少的服务。
- 服务发布会唤醒订阅它的 Fiber。必需服务撤销时，使用它的实例回到 `PENDING`。服务恢复后，同一个 Fiber 会用新的上下文再运行一次 `setup()`。可选服务变化时，消费者用更新后的绑定重启。
- `setup()` 成功并提供全部声明的服务后，Fiber 进入 `ACTIVE`。启动失败时，内核清理已经登记的回调，失败实例的 `error` 保留原始异常。
- 关闭提供方时，受影响的插件先停止接收新的事件调用，然后执行 `on_quiesce`、等待在途回调、逆序执行 `on_dispose`。依赖者先清理，并可以在清理期间读取本次激活使用的服务。
- `root.start()` 用于启动完整配置，会先检查缺失声明、服务冲突和循环依赖。HMR 更新配置时按受影响的服务传播，失败后尝试恢复原配置。
- 同一根上下文的装卸串行执行。一旦装卸开始，调用方取消等待也会先让状态转换完成。由宿主发起装卸，生命周期回调和事件处理器可以登记自身的回调与清理。

## 设计来源

- 上游 Cordis 提供了 Context、Fiber、服务依赖和可逆注册的设计参考。 [Cordis](https://github.com/cordiverse/cordis)
- DeepSeek Harness 展示了如何用 Cordis 组织插件生命周期，并由独立的 Loader 处理配置装配。 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)

项目内版本 `0.1.0+minidsh.3` 基于独立仓库的 `7c594aae632a7a67b3d2a87ba2903b77ccee6d24`，加入了宿主服务、可选依赖、批量启动和局部重装。 [独立仓库](https://github.com/nandalock/minidsh-cordis)
