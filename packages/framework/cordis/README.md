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

## 生命周期

- `await root.plugin(...)` 登记插件并等待本次可运行的实例完成启动。依赖缺失时，Fiber 保持 `PENDING`，可以用 `waiting_for` 查看缺少的服务。
- `setup()` 成功并提供全部声明的服务后，Fiber 进入 `ACTIVE`。启动失败时，内核清理已经登记的回调，失败实例的 `error` 保留原始异常。
- 关闭提供方时，受影响的插件先停止接收新的 waterfall 调用，然后执行 `on_quiesce`、等待在途回调、逆序执行 `on_dispose`。依赖者先清理，服务随后撤销。重新登记提供方后，依赖者使用新的上下文再次启动。
- 同一根上下文的装卸串行执行。一旦装卸开始，调用方取消等待也会先让状态转换完成。由宿主发起装卸，生命周期回调和事件处理器可以登记自身的回调与清理。

## 设计来源

- 上游 Cordis 提供了 Context、Fiber、服务依赖和可逆注册的设计参考。 [Cordis](https://github.com/cordiverse/cordis)
- DeepSeek Harness 展示了如何用 Cordis 组织插件生命周期，并由独立的 Loader 处理配置装配。 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)

项目内版本 `0.1.0+minidsh.3` 基于独立仓库的 `7c594aae632a7a67b3d2a87ba2903b77ccee6d24`，加入了宿主服务、可选依赖、批量启动和局部重装。 [独立仓库](https://github.com/nandalock/minidsh-cordis)
