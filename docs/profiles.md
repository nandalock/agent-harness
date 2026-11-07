# Profile 与配置

[文档首页](README.md) · [插件管理](plugin-management.md) · [启动与插件运行](startup.md)

一个 profile 是一套可单独启动的应用环境。默认名称是 `web`。可用 `MINIDSH_HOME` 改变用户目录位置，缺省为 `~/.minidsh`。

```text
~/.minidsh/profiles/web/
├─ .venv/              Python 和实际安装的插件
├─ plugins.yaml        默认插件清单的覆盖项，以及额外插件实例
├─ local.env           数据库连接和可选的模型或集成配置
├─ runtime.lock        初始化时安装的运行时包和版本
├─ requirements.lock   当前虚拟环境里的包版本快照
├─ skills/             本 profile 的安装技能
└─ workspaces/         默认的沙箱工作区根目录
```

Windows 插件包在 `.venv/Lib/site-packages`，Linux 和 macOS 在 `.venv/lib/python3.12/site-packages` 一类的平台目录中。进程环境变量优先于 `local.env`；发布模式显式从选中的 profile 读取 `plugins.yaml`。

## 开一套研究环境

```powershell
minidsh profile init --profile research --wheelhouse D:/minidsh-release
minidsh plugin list --profile research
minidsh web --profile research --port 4200
```

每个 profile 单独安装依赖。要隔离聊天、Agent 和知识库的数据，为每个 profile 配置自己的 PostgreSQL 数据库。并行启动时也需要不同的 Web 和内置 MCP 端口，后两者在 `local.env` 中分别用 `BUILTIN_MCP_PORT`、`PAPER_MCP_PORT` 设置。

## 选择浏览器壳

默认使用发布包中的 Web 壳。要给某个 profile 换壳，在它的 `local.env` 中设置
`MINIDSH_WEB_ROOT=D:/my-web/dist`，指向带 `index.html` 的构建产物。
兼容的壳可从同源 `/api/plugins` 读取该 profile 的浏览器插件。

## 写一项覆盖

```yaml
version: 1
plugins:
  - id: memory
    name: agent-platform.memory
    disabled: true
```

`id` 是这条实例配置的名字，`name` 匹配安装包声明的插件入口。同 ID 的记录覆盖默认实例。重启后，禁用的记忆插件会从启动图退出，浏览器也不会加载它的页面。

源码启动器 `python minidsh.py web` 仍面向仓库开发。用 `--frontend` 选仓库前端，旧 `--profile` 参数保留为别名。发布命令 `minidsh web --profile` 选择整套应用环境。
