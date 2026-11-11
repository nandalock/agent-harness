# minidsh 插件 Loader

Loader 合并 YAML、导入 `use` 指定的模块导出，并通过插件自己的 `config_model` 校验参数。随后把原生 Cordis 插件交给根 `Context`。Fiber 等待依赖服务可用后启动，并在订阅的服务变化时重新装配。

## 最小清单

```yaml
version: 1
plugins:
  - id: tools
    name: agent-platform.tools-default
    use: agent_platform_tools_default:ToolsDefaultPlugin
  - id: echo
    name: example.echo
    use: example_echo_plugin:plugin
    config:
      prefix: "收到："
```

`id` 标识当前装配中的实例，`name` 对应插件自身名称，`use` 定位类、工厂或插件定义。相同实现可以在一个清单中有多个实例。需要实例级可变状态时，把状态建在 `setup()` 中，或导出类、工厂。

```python
from minidsh_cordis_plugin_loader import Loader
from agent_platform_plugin_sdk import TOOLS

loader = Loader.from_yaml("plugins.yaml")
await loader.start()
try:
    tools = loader.ctx.require(TOOLS)
finally:
    await loader.aclose()
```

`Loader.validate()` 可以在修改 profile 时提前检查导出、参数和服务依赖声明。Web 在 YAML 更新后调用 `reconfigure()`，由 Loader 找出配置变化的条目，再由 Cordis 按服务订阅传播变更。应用通过 Loader 的清单读取活跃插件的名称、版本和浏览器资源。

[分层配置和分组](../../../docs/startup.md) · [可运行的 Echo 示例](../../plugin/examples/README.md) · [Cordis 内核](../cordis/README.md)
