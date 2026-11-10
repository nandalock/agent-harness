# minidsh 插件 SDK

SDK 定义工具、Agent 扩展、数据库、设置和审批等业务接口。服务键使用 `minidsh_cordis.ServiceKey`，由业务接口所属的包导出。相同名字和主版本的键指向同一个服务。

```python
from minidsh_cordis import Context, Plugin
from agent_platform_plugin_sdk import SdkModel, TOOLS

class ExamplePlugin(Plugin[SdkModel]):
    name = "example.plugin"
    version = "0.1.0"
    requires = (TOOLS,)
    config_model = SdkModel

    async def setup(self, ctx: Context, config: SdkModel) -> None:
        tools = ctx.require(TOOLS)
        # 注册工具后，用 ctx.track(registration) 将注册绑定到插件生命周期。
```

服务提供者用 `provides` 声明服务并在 `setup()` 调用 `ctx.provide(key, service)`。消费者用 `requires` 或 `optional` 声明依赖。可选服务不存在时，`ctx.get(key)` 返回 `None`。

[工具协议源码](src/tools.py) · [工具协议测试套件](src/testing.py) · [可运行的工具插件](../examples/README.md) · [插件开发指南](../../../docs/plugin-development.md)
