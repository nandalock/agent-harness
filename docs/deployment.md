# 部署方式

参考 DeepSeek Harness 的 CLI/profile 启动方式，本项目使用根目录 `minidsh.py`
统一安装、环境检查、进程启动和关闭。插件仍由同一个 PluginRuntime 装配。

| 方式 | 前后端 | PostgreSQL / Redis | 命令 |
| --- | --- | --- | --- |
| 本地 | 宿主机进程 | 自建本地或远程服务 | `python minidsh.py dev` |
| 混合 | 宿主机进程 | Docker Compose | `python minidsh.py dev --mode hybrid` |
| Docker | 容器 | Docker Compose | `python minidsh.py docker` |

## 本地安装

Windows、Linux、macOS 均使用 Python 3.12+ 和 Node.js 20+（建议 22）。
在仓库根目录运行，无需手动激活虚拟环境：

```sh
python minidsh.py setup
python minidsh.py doctor
python minidsh.py dev
```

`setup` 创建/复用 `.venv`，安装后端及所有插件包，执行前端 `npm ci`，
从 `.env.local.example` 创建 `.env.local` 并生成随机 JWT 密钥。已有配置不覆盖。
请在 `.env.local` 中设置数据库连接。命令行环境变量优先。
CLI 不读取 Docker Compose 使用的 `.env`，也不会输出连接密码或 API 密钥。

本地 PostgreSQL 需要安装 pgvector、pg_trgm 扩展文件，创建用户及数据库。
首次启动自动建表、迁移、初始化演示数据，因此数据库用户需要建表和创建扩展权限。
数据库创建示例（按实际账号修改）：

```sql
CREATE USER saas WITH PASSWORD 'saas';
CREATE DATABASE saas OWNER saas;
-- 连接 saas 后由管理员执行：
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

默认数据库地址为 `postgresql://saas:saas@localhost:5432/saas`。
Redis 默认 `redis://localhost:6379/0`，用于缓存；未配置时缓存不可用，主对话仍可运行。
FAQ 的向量检索还需要配置 Ollama 和 `bge-m3`；普通工具对话不需要它。
LLM API Key / Base URL / Model 仍在智能体配置页设置。

开发模式自动重载后端，启动 Next.js dev。前端 `http://localhost:4000`，
后端文档 `http://localhost:8000/docs`，就绪检查 `/health`。
Ctrl+C 关闭本次启动的前后端进程树，不关闭数据库。

## 混合部署

```sh
python minidsh.py setup
python minidsh.py dev --mode hybrid
```

只执行 `docker compose -f deploy/compose.infra.yaml up -d --wait db redis`，不会构建后端镜像。
数据库卷沿用现有 Compose 配置。也可先单独执行 `python minidsh.py infra`。
如果 Docker 的前后端已占用 8000/4000，先手动执行
`docker compose stop backend frontend`，或者换端口：

```sh
python minidsh.py dev --mode hybrid --backend-port 18000 --frontend-port 14000
```

CLI 会检查端口冲突，不会自动关闭已有服务。不要同时用多个应用进程修改同一会话。

## 本地生产模式

```sh
python minidsh.py build
python minidsh.py start
# 使用容器数据库：python minidsh.py start --mode hybrid
# 仅启动后端：python minidsh.py start --backend-only
```

生产模式关闭自动重载；前端构建在 `.next-local-build`，开发产物在 `.next-local`，
与容器的 `.next` 分开。构建和启动应使用相同的前端/API 地址参数与环境变量，
因为 `NEXT_PUBLIC_API_URL` 在构建时写入前端资源。
CLI 默认只监听回环地址，适合本地部署。公网服务应由进程管理器和反向代理接管，
配置 HTTPS、正式数据库账号和认证密钥；原有 Docker 部署不受影响。

## 可选功能

- 重排模型：`python minidsh.py setup --rag`，会额外安装 sentence-transformers/PyTorch。
  默认安装不下载大模型；未安装或模型加载失败时按候选原顺序返回。
- 沙箱默认宿主机执行，受限模式使用操作系统限制，Windows 支持 PowerShell。
  Windows runner 由 setup 安装；Linux 需要 bubblewrap，macOS 使用 Seatbelt。
  `SANDBOX_BACKEND=docker` 可切回容器。默认权限仍为 workspace-write；
  只有 danger-full-access 才直接运行。详见[宿主机沙箱](native-sandbox.md)。
- 数据根默认 `~/.minidsh`，可通过 `MINIDSH_HOME` 统一指定。
  工作区为 `<MINIDSH_HOME>/workspaces`、技能为 `skills`、论文缓存为 `cache/paper-mcp`。
  可通过 `.env.local` 覆盖 `SANDBOX_WORKSPACE_ROOT`、`SKILL_INSTALL_ROOT`。
  原 `.agent-harness` 目录不会被自动删除；需要沿用旧数据时显式设置 `MINIDSH_HOME`
  或相应子目录变量。`harness.py` 仅保留为兼容入口，新部署使用 `minidsh.py`。
- 本地内置 MCP 默认监听 19001/19002，以避开 Windows 常见的端口保留范围。
  如需更改，设置 `BUILTIN_MCP_PORT`、`PAPER_MCP_PORT`。插件宿主在内存中映射旧种子
  URL，不修改数据库里的 MCP 配置。
- Overleaf 默认关闭。启用时设置 `OVERLEAF_ENABLED=true`，另外创建隔离 Python 环境，
  安装 `overleaf-mcp-plus[compile]` 和 python-dotenv，通过 `OVERLEAF_MCP_PYTHON` 指定解释器。
  主后端使用 MCP SDK 1，不能把 SDK 2 服务装入同一个 `.venv`。
  Overleaf RT 使用 `OVERLEAF_RT_ENABLED=true`，另需 Node/npx 和相应凭据。
- 自定义插件继续使用根目录 `plugins.yaml` 或环境变量 `PLUGIN_CONFIG`。
  内置/论文 MCP 与 Overleaf 的启动、连接和关闭现由 managed-mcp 插件包负责，
  不再由 backend/main.py 逐项启动。可按插件实例设置 disabled 或 config.enabled。
  `MANAGED_MCP_ENABLED=false` 可整体关闭这些集成；`PLUGIN_MCP_AUTO` 仅控制其他数据库 MCP 的自动发现。

## 保留 Docker 部署

```sh
docker compose up -d --build
# 等价入口：python minidsh.py docker
```

本地新增包已经包含在 `requirements-plugins.txt`，镜像构建会一起安装。
`doctor` 只做检查，不修改数据库，也不启动服务。

## Agent 配置

新安装没有内置 Agent。在界面的“Agent 管理”创建 Agent，填写模型与提示词并绑定工具。
后端启动只读取数据库定义，普通 Agent 使用 AgentRuntime，路由类型使用通用 RouterRuntime。
升级时旧版本附带的 FAQ、订单、工单、Supervisor、人工转接和论文示例只归档一次，
不删除定义、模型配置、工具绑定或历史对话。之后用户创建的同名 Agent 不会再次归档。
