# 快速开始

[文档首页](README.md) · [部署方式](deployment.md) · [Profile 与配置](profiles.md)

## 用发布 wheel 运行

准备 Python 3.12+、带 pgvector 与 pg_trgm 的 PostgreSQL，以及一套 minidsh 发布 wheel 目录。发布目录的构建步骤见 [开发指南](development.md#构建发布-wheel)。

Windows PowerShell 示例：

```powershell
$wheelhouse = 'D:/minidsh-release'
python -m pip install --user --find-links "$wheelhouse" agent-platform-cli==0.1.0
minidsh profile init --profile web --wheelhouse "$wheelhouse"
```

如果终端还没找到 `minidsh`，把 Python 的用户脚本目录加入 PATH，或用 `python -m agent_platform_cli.profiles` 代替命令。Linux 和 macOS 可用相同的 pip 命令，将 wheel 目录换成绝对路径。

编辑 `~/.minidsh/profiles/web/local.env`，填写自己的 PostgreSQL 连接。然后从任意目录执行：

```powershell
minidsh web
```

打开 `http://127.0.0.1:4000`。该端口同时服务浏览器和 API。浏览器资源已随发布 wheel 交付。Windows 上需要受限沙箱时，参见 [宿主机沙箱依赖](native-sandbox.md)。

1. 在「Agent 管理」创建智能体并填写模型配置。
2. 为智能体勾选需要的工具和技能。
3. 在「工作区」创建会话并发送第一条消息。

同一个启动器也可以从终端运行一轮：

```powershell
minidsh run --agent my-agent "列出当前可用的工具"
```

## 从源码运行

在仓库根目录执行 `python minidsh.py setup`，编辑 `config/local.env`，再执行 `python minidsh.py web`。源码模式使用仓库虚拟环境和 Vite 开发服务器。选择混合部署、Docker 或独立前端时，见 [部署文档](deployment.md)。

下一步可按 [插件管理](plugin-management.md) 安装一个示例工具。
