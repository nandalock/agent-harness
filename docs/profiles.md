# Profile 与配置

[文档首页](README.md) · [插件管理](plugin-management.md) · [启动与插件运行](startup.md)

一个 profile 是一套可单独启动的应用环境。默认名称是 `web`。可用 `MINIDSH_HOME` 改变用户目录位置，缺省为 `~/.minidsh`。

```text
~/.minidsh/profiles/web/
├─ .venv/              Python 和实际安装的插件
├─ cordis.yml          根配置，声明插件实例和 Include
├─ cordis.patch.yml    按实例 ID 覆盖配置或启用状态
├─ local.env           数据库连接和可选的模型或集成配置
├─ runtime.lock        初始化时安装的运行时包和版本
├─ requirements.lock   当前虚拟环境里的包版本快照
├─ skills/             本 profile 的安装技能
└─ workspaces/         默认的沙箱工作区根目录
```

Windows 插件包在 `.venv/Lib/site-packages`，Linux 和 macOS 在 `.venv/lib/python3.12/site-packages` 一类的平台目录中。进程环境变量优先于 `local.env`。启动器把所选 profile 的两个配置路径传给 app-boot。已有 profile 可把同目录的 `plugins.yaml` 改名为 `cordis.yml`。只有旧文件时仍可读取。

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

## 在 cordis.patch.yml 写一项覆盖

```yaml
- id: memory
  disabled: true
```

`id` 对应根配置或默认清单里的实例。Web 默认监测两个配置文件。保存后，Loader 会校验更新并重装受影响的插件。

源码和发布入口都用 `--profile` 选择运行配置。源码入口使用仓库 `.venv`，并可单独用 `--frontend` 选择前端。发布入口使用所选 profile 的 `.venv`。
