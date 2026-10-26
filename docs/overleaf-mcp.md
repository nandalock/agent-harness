# Overleaf MCP

接入上游 [rangehow/overleaf-mcp](https://github.com/rangehow/overleaf-mcp)，固定安装
`overleaf-mcp-plus[compile]==0.3.1`，支持项目列表、LaTeX 文件读写、编译、PDF 下载和版面查询。

## 项目内使用

后端镜像将服务安装在 `/opt/overleaf-mcp` 独立 Python 环境中，同时安装 Git。
项目继续使用 MCP SDK 1，Overleaf 服务使用 SDK 2，两者通过 stdio 通信。
启动时自动登记名为 `overleaf` 的 MCP 服务，已有同名服务的配置会保留。
凭据不写入 MCP 数据库记录；在项目根目录被 Git 忽略的 `.env` 中填写：

```dotenv
OVERLEAF_SESSION=你的_overleaf_session2_cookie
OVERLEAF_GIT_TOKEN=你的_Git_Integration_token
```

Cookie 在登录 Overleaf 后，通过浏览器开发者工具的 Application → Cookies →
`https://www.overleaf.com` → `overleaf_session2` 获取。Git Token 可选，在 Overleaf
账户设置的 Git Integration 中创建；上游说明 Git 编辑功能需要支持 Git Integration 的套餐。
不填凭据仍可发现工具，但访问账户时会返回缺少凭据的提示。
完整变量示例见 [`.env.overleaf.example`](../.env.overleaf.example)。

```powershell
docker compose build backend
docker compose up -d backend
```

打开 `/dashboard/mcp` 可查看 `overleaf` 工具组，在 Agent 编辑页的工具绑定中选择需要的工具。
不会自动把工具绑定到现有 Agent。已有安装的环境可用 [`mcp/overleaf.json`](mcp/overleaf.json)
通过工具页面手动导入；已自动登记时无需重复导入。
编译等工具设置 300 秒执行超时；同一批调用串行执行，避免共享 Git 缓存冲突。
缓存保存在 Compose 的 `overleaf_cache` 卷，重建后端容器时仍保留。
下载路径使用后端容器内的绝对路径，例如工作区中的 `/srv/agent/workspaces/...`。

## 本机 Codex

本机安装位于 `~/.codex/mcp/overleaf/venv`，全局 MCP 配置位于
`~/.codex/config.toml` 的 `[mcp_servers.overleaf]`，启动入口位于
`~/.codex/mcp/overleaf/entrypoint.py`。入口仅从本项目的 `.env` 读取 Overleaf
账户变量，已有进程环境变量优先。缓存位于 `~/.codex/mcp/overleaf/cache`。
修改 `.env` 后，重连 Overleaf MCP；初次安装后重启 Codex 或新开聊天加载工具。

其他电脑可按同样方式创建独立环境：

```powershell
python -m venv "$env:USERPROFILE/.codex/mcp/overleaf/venv"
& "$env:USERPROFILE/.codex/mcp/overleaf/venv/Scripts/python.exe" -m pip install 'overleaf-mcp-plus[compile]==0.3.1' python-dotenv
```

本机直接运行后端时，launcher 默认查找上述 Windows 环境；其他路径可通过
`OVERLEAF_MCP_PYTHON` 指定。容器内默认查找 `/opt/overleaf-mcp/bin/python`。

官方 Codex MCP 配置说明：[OpenAI documentation](https://developers.openai.com/codex/mcp/)。
