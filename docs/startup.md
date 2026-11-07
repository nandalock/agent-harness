# 从命令跟到插件运行

[文档首页](README.md) · [Profile 与配置](profiles.md) · [插件架构](plugin-architecture.md)

## 启动链路

```text
minidsh web --profile web
  → 选择 ~/.minidsh/profiles/web/.venv 的 Python
  → Uvicorn 导入 agent_platform_server:app
  → app-boot 合并默认清单和 profile/plugins.yaml
  → PluginRuntime 发现 entry points、验证依赖、逐个 setup()
  → HTTP 插件发布 FastAPI 应用
  → 服务端挂载 wheel 里的浏览器壳
  → 浏览器请求 /api/plugins，并运行已启动插件的浏览器入口
```

读代码时可以按这个顺序打开：

1. [发布 CLI](../apps/cli/src/agent_platform_cli/profiles.py) 选择 profile，显式指定配置文件，启动子进程。
2. [服务端入口](../apps/server/src/agent_platform_server/__init__.py) 接到 ASGI 启动事件，创建运行时并拿到 HTTP 应用。
3. [配置读取](../packages/boot/app-boot/src/agent_platform_app_boot/config.py) 与 [默认清单](../packages/plugin/default/src/plugins.yaml) 决定有效插件列表。
4. [入口发现](../packages/plugin/runtime/src/catalog.py) 用 Python 安装记录定位插件类。
5. [运行时](../packages/plugin/runtime/src/runtime.py) 按服务依赖排序，依次执行 `setup(ctx, config)`，关停时逆序清理。
6. [浏览器启动](../packages/client/kernel/boot.ts) 读取宿主公布的入口，注册菜单、路由和插槽。

## 跟踪一个真实插件

工作区的 [pyproject.toml](../packages/api/workspace/pyproject.toml) 将 `agent-platform.api-workspace` 映射到 `WorkspaceControllerPlugin`。它的 [setup](../packages/api/workspace/src/plugin.py) 取数据库、会话服务和 RPC Gateway，再注册 `workspace.*` 方法。浏览器从同一个包加载 [页面入口](../packages/api/workspace/client/src/client.tsx)。点击「工作区」菜单后，页面通过 [RPC 客户端](../packages/client/legacy/lib/remote/index.ts) 请求会话和文件。

YAML 决定要启动哪个插件实例。`ctx.require(KEY)` 查找本次运行的服务，`ctx.provide(KEY, instance)` 发布服务。一个插件可以提供多个工具，也可以只发布服务。用 `ctx.track(...)` 跟踪注册句柄，运行时会在关闭或启动失败时撤销这些注册。

[下一篇：自己写一个工具插件](plugin-development.md)
