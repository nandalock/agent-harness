# 从命令跟到插件运行

[文档首页](README.md) · [Profile 与配置](profiles.md) · [插件架构](plugin-architecture.md)

## 启动链路

```text
minidsh web --profile web
  → 选择 ~/.minidsh/profiles/web/.venv 的 Python
  → Uvicorn 导入 agent_platform_server:app
  → app-boot 合并默认清单和 profile/plugins.yaml
  → Loader 导入插件、校验配置，把插件交给 Cordis
  → Cordis 为各插件创建 Fiber 和 ctx，启动插件并持有服务及清理动作
  → HTTP 插件发布 FastAPI 应用
  → 服务端挂载 wheel 里的浏览器壳
  → 浏览器请求 /api/plugins，并运行已启动插件的浏览器入口
```

读代码时可以按这个顺序打开：

1. [发布 CLI](../apps/cli/src/agent_platform_cli/profiles.py) 选择 profile，显式指定配置文件，启动子进程。
2. [服务端入口](../apps/server/src/agent_platform_server/__init__.py) 接到 ASGI 启动事件，创建运行时并拿到 HTTP 应用。
3. [配置读取](../packages/boot/app-boot/src/agent_platform_app_boot/config.py) 与 [默认清单](../packages/plugin/default/src/plugins.yaml) 决定有效插件列表。
4. [入口发现](../packages/framework/loader/src/catalog.py) 按配置导入 Python 模块和导出对象。
5. [Loader](../packages/framework/loader/src/loader.py) 将原生插件交给 [Cordis 内核](../packages/framework/cordis/src/context.py)。每个 Fiber 在必需服务可用后启动。关停时先收口运行中的任务，再清理消费者和它们的提供方。
6. [浏览器启动](../packages/client/kernel/boot.ts) 读取宿主公布的入口，注册菜单、路由和插槽。

## 跟踪一个真实插件

默认清单中的 `api-workspace` 实例通过 `use: agent_platform_api_workspace:WorkspaceControllerPlugin` 找到插件。它的 [setup](../packages/api/workspace/src/plugin.py) 取数据库、会话服务和 RPC Gateway，再注册 `workspace.*` 方法。浏览器从同一个包加载 [页面入口](../packages/api/workspace/client/src/client.tsx)。点击「工作区」菜单后，页面通过 [RPC 客户端](../packages/client/legacy/lib/remote/index.ts) 请求会话和文件。

YAML 决定要启动哪个插件实例。`ctx.require(KEY)` 查找本次运行的服务，`ctx.provide(KEY, instance)` 发布服务。一个插件可以提供多个工具，也可以只发布服务。用 `ctx.track(...)` 跟踪注册句柄，运行时会在关闭或启动失败时撤销这些注册。

## 叠加配置与热更新

默认清单提供模块路径。用户配置可以通过 `includes` 引用其他 YAML，路径相对于声明它的文件。同 ID 的插件条目由较高层替换，`patches` 则按 ID 覆盖 `config` 的顶层字段或 `disabled` 状态。

```yaml
includes: [tools.local.yaml]
groups:
  demos:
    disabled: false
plugins:
  - id: echo
    name: example.echo
    use: example_echo_plugin:plugin
    group: demos
patches:
  - id: echo
    config: {prefix: "收到："}
```

`use` 指向已安装模块的 Cordis 插件类、工厂或 `plugin` 对象，`name` 对应插件声明的名称。覆盖内置插件时可沿用默认清单里的 `use`。自定义插件需要显式填写 `use`。把 `demos.disabled` 设为 `true` 可整组停用。

用 `minidsh web --plugin-patch override.yaml` 临时叠加一层配置。源码版使用 `python minidsh.py web --plugin-patch override.yaml`。最终顺序为内置清单、Include 文件、用户配置和命令行覆盖。

Web 进程默认检测配置变化。通过依赖校验后，Cordis 只重装变更实例及受影响的依赖者。启动失败会尝试恢复旧装配，结果会写入后端日志。涉及宿主绑定的 HTTP 或工具服务需要重启进程。可用 `MINIDSH_CONFIG_RELOAD=false` 停用监听。源码开发的 Python 变更由 Uvicorn 重启后端进程。

[Include 和 Patch](../packages/framework/include/src/layers.py) 负责合并配置，[Group](../packages/framework/group/src/group.py) 提供分组启停规则。[app-boot](../packages/boot/app-boot/src/agent_platform_app_boot/lifecycle.py) 在插件启动后运行 [HMR](../packages/framework/hmr/src/hmr.py)，并提供配置读取和更新回调。HMR 轮询配置，将变化交给 [Loader.reconfigure()](../packages/framework/loader/src/loader.py) 校验并重装受影响的插件。启动、热更新和关闭都由同一个生命周期任务执行。Python 源码修改需要重启。

[下一篇：自己写一个工具插件](plugin-development.md)
