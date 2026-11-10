# minidsh-cordis

可独立安装的 Python 插件内核。`Context` 是运行入口，`Fiber` 管理一个插件实例。每次激活都创建新的插件上下文，服务和回调跟随这次激活释放。

```powershell
python -m pip install -e ./packages/cordis
python -m unittest discover -s ./packages/cordis/tests -v
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

## 生命周期

- `await root.plugin(...)` 登记插件并等待本次可运行的实例完成启动。依赖缺失时，Fiber 保持 `PENDING`，可以用 `waiting_for` 查看缺少的服务。
- `setup()` 成功并提供全部声明的服务后，Fiber 进入 `ACTIVE`。启动失败时，内核清理已经登记的回调，失败实例的 `error` 保留原始异常。
- 关闭提供方时，受影响的插件先停止接收新的 waterfall 调用，然后执行 `on_quiesce`、等待在途回调、逆序执行 `on_dispose`。依赖者先清理，服务随后撤销。重新登记提供方后，依赖者使用新的上下文再次启动。
- 同一根上下文的装卸串行执行。一旦装卸开始，调用方取消等待也会先让状态转换完成。由宿主发起装卸，生命周期回调和事件处理器可以登记自身的回调与清理。

## 为什么内核不用 entry point

Python entry point 解决的是**从已安装的发行包发现插件**。这里的 `Context` 接收一个已经找到的 `Plugin` 对象，负责实例、依赖和清理。这样同一个内核可以接收测试里的本地插件，也可以接收宿主加载的已安装模块。

DSH 的 Loader 先按配置导入模块，再把导出的插件交给 Cordis Registry。在后续 minidsh Loader 中也可以用明确的 `模块:导出对象` 定位插件。比如 `example_plugin:plugin` 表示导入 `example_plugin`，再取它的 `plugin` 对象。这样配置文件本身就是启动清单。当前 minidsh 的宿主继续使用原有的 entry point 加载路径，这个独立包可以先单独验证。

## 设计来源

- DSH 的 Cordis 用 Fiber 管插件状态与清理，Loader 单独负责导入和装配。参见 [Fiber](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388/vendor/cordis/src/fiber.ts) 与 [Loader Entry](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388/vendor/loader/src/config/entry.ts)。
- Python 侧对照了 [cordis-py](https://github.com/geohotstan/cordis-py) 和 [learn-cordis4py](https://github.com/Asukayanamii/learn-cordis4py) 的上下文、生命周期与可逆注册。这个包使用 Python 标准库 `asyncio` 和 `graphlib`，沿用 minidsh 的 `setup(ctx, config)` 和先停止接单、再清理资源的约定。
