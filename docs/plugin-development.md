# 插件开发指南

[文档首页](README.md) · [启动与插件运行](startup.md) · [安装和管理插件](plugin-management.md)

## 从 Echo 工具开始

可以复制 [Echo 示例](../packages/plugin/examples/echo-plugin)。目录里的 `pyproject.toml` 声明发行包和源码位置，`src/__init__.py` 实现插件类。

```toml
[tool.setuptools.package-dir]
example_echo_plugin = "src"
```

配置涉及这些名字。

| 名字 | 出现在哪里 |
| --- | --- |
| `agent-platform-example-echo` | pip 安装和卸载的发行包名 |
| `example.echo` | YAML 的 `name`，对应 Cordis 插件声明的名称 |
| `example_echo_plugin:plugin` | YAML 的 `use`，对应 Python 模块与导出对象 |
| `echo` | 示例实例 ID，也可单独指定工具名 |

在 [示例源码](../packages/plugin/examples/echo-plugin/src/__init__.py) 里，Cordis 插件的 `requires` 声明依赖工具服务，`config_model` 校验用户配置。`setup()` 获取 `TOOLS`，登记 executor 与工具描述符，并将注册句柄交给 `ctx.track()`。给 Agent 绑定 `echo` 后，工具调用会通过统一注册表分派到该 executor。

## 作为服务或前后端包发布

服务型插件可以定义 `ServiceKey`，在 `provides` 声明它并在 `setup()` 里发布。调用者通过 `requires` 与 `ctx.require()` 注入服务。先看 [插件 SDK](../packages/plugin/sdk/README.md) 和 [运行时示例](../packages/plugin/examples/README.md)。

如果包也有界面，参考 [工作区包](../packages/api/workspace)。Python 的 Cordis 插件的 `web_package` 指向浏览器资源所属的导入包。浏览器入口的 `setup(ctx)` 用 `ctx.nav.add()`、`ctx.router.add()` 和 `ctx.slots.register()` 贡献界面。用 [客户端打包流程](../packages/client/README.md#browser-entries-in-python-packages) 生成 `web/client.js` 和 `web/client.json`，再把它们作为 wheel 的包数据。

## 构建与试装

```powershell
python -m pip wheel --no-deps -w .data/plugins ./packages/plugin/examples/echo-plugin
minidsh plugin install .data/plugins/agent_platform_example_echo-0.1.0-py3-none-any.whl --use example_echo_plugin:plugin --id echo
minidsh plugin list
```

重启 Web，在 Agent 配置页绑定 `echo`，然后请智能体调用它。排查时先确认 `list` 中实例已启用，再看 `/api/plugins`、工具绑定和服务端启动日志。

[下一篇：开发、测试和发布](development.md)
