<div align="center">

# minidsh

**一个可本地部署、按插件装配的 AI Agent 工作台。**

在同一个工作区里对话、使用工具、加载技能、浏览文件，并把智能体连接成工作流。

[快速开始](#快速开始) · [界面演示](#界面演示) · [插件架构](#插件架构) · [学习与开发文档](docs/README.md)

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-149ECA?logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)

</div>

![minidsh 会话工作区：项目会话、对话记录和文件面板](docs/images/workspace.png)

<p align="center"><sub>当前界面截图，使用固定演示数据；新安装不预置图中的 Agent 和会话。</sub></p>

minidsh 把 Agent 执行循环、模型接入、工具、技能、记忆、会话持久化和 HTTP API 拆成可以组合的包。
通过 YAML 选择插件，由 `PluginLoader` 导入，再由 `minidsh-cordis` 管理服务依赖与生命周期。
默认提供浏览器工作台，也可以使用无 HTTP 的命令行入口执行 Agent。

项目参考 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的插件与客户端模块设计，
使用 Python 实现服务端，React + Vite 实现默认前端。

## 能做什么

| 能力 | 使用方式 |
| --- | --- |
| 会话工作区 | 按项目组织会话，查看对话与工具轨迹，浏览、上传和预览文件 |
| 自定义 Agent | 配置模型、系统提示词、工具和技能；新安装由使用者创建自己的 Agent |
| 工具执行 | 通过统一工具服务调用 PowerShell、bash、Python 及 MCP 工具，支持超时、并发和审批 |
| 渐进式技能加载 | 初始展示技能摘要；任务匹配后读取 `SKILL.md`，再按需加载参考资料 |
| 会话持久化与恢复 | 以事件日志记录执行事实，从日志派生历史、轨迹和恢复状态 |
| 智能体记忆 | 自动压缩较早的对话，按智能体和会话维护 Markdown 笔记，在工作区查看上下文用量 |
| 可视化工作流 | 在 React Flow 画布上连接 Agent、路由和条件节点，保存、预览与运行流程 |
| MCP 集成 | 管理外部 MCP 服务，接入论文、Overleaf 等独立配置的集成 |
| 知识库与缓存 | 管理 FAQ，按需启用向量检索、重排和 Redis 缓存 |
| 插件化前端 | 页面功能通过客户端插件和 slots 组合，功能包可同时携带后端和页面 |

> 仓库正在持续进行插件化与 RPC 迁移。Workspace、Agent 配置、部分 Session 操作和工作流
> 已接入插件服务（工作流通过 `workflow.v1` / `workflow.nodes.v1`）；聊天流、文件传输及
> 部分管理接口仍使用 HTTP/SSE。当前边界见 [RPC API 文档](docs/rpc-api.md)。

## 界面演示

以下图片由当前 React 前端实际渲染，使用固定演示数据截取。图中的 Agent、会话、回复和工作流均为示例，
不代表新安装预置这些内容，也不代表截图过程调用过在线模型或外部 MCP 服务。

### 工作区：对话与文件放在一起

左侧按 Agent 和项目组织会话，中间查看对话，右侧浏览会话目录中的文件。
可以切换执行权限模式，并在同一页面上传、预览和处理资料。

### 自己创建需要的智能体

在管理页维护不同用途的 Agent，分别设置模型、提示词和能力。

![Agent 管理演示：研究助手、代码助手和知识库助手](docs/images/agents.png)

### 技能与工具按 Agent 配置

启用技能后自动关联其声明的工具；工具是否可执行，仍取决于对应插件、连接及权限。
技能说明可以按需读取，安装技能不会自动安装外部服务。

![智能体配置演示：技能绑定与工具配置](docs/images/agent-settings.png)

### 用画布组织处理步骤

将多个处理节点连接成工作流，并从编辑器中保存草稿、预览或运行。

![工作流演示：开始、资料整理、检查与归纳、结束](docs/images/workflow.png)

截图与复现方式见 [演示图片说明](docs/images/README.md)。

## 快速开始

### 用发布包运行

安装发布目录中的 CLI wheel 后，按 [快速开始](docs/quickstart.md) 初始化 profile。发布目录可按 [构建指南](docs/development.md#构建发布-wheel) 生成。

```powershell
minidsh profile init --profile web --wheelhouse D:/minidsh-release
# 在 ~/.minidsh/profiles/web/local.env 填写 PostgreSQL 连接
minidsh web
```

从任意目录启动后，打开 **http://127.0.0.1:4000**。额外插件装在
`~/.minidsh/profiles/web/.venv`，启用状态写入同一个 profile 的 `plugins.yaml`。

```powershell
minidsh plugin install D:/downloads/agent_platform_example_echo-0.1.0-py3-none-any.whl --use example_echo_plugin:plugin --id echo
minidsh plugin list
```

启用、停用、卸载和编写插件，见 [插件管理](docs/plugin-management.md) 与 [插件开发](docs/plugin-development.md)。

### 从源码运行

- **Python 3.12+**：运行服务端及插件。
- **Node.js 20+ 与 npm**：安装、构建和运行默认前端。
- **PostgreSQL**：需要 `pgvector` 和 `pg_trgm` 扩展；Compose 使用 PostgreSQL 16。
- **模型服务配置**：在 Agent 配置页填写 API Key、Base URL 和模型名。

Redis 用于缓存；Ollama 与重排模型用于可选检索能力，普通模型与工具对话不要求先安装这些模型。

```sh
git clone https://github.com/nandalock/agent-harness.git minidsh
cd minidsh
python minidsh.py setup
```

`setup` 创建或复用 `.venv`，安装插件与前端依赖，并生成 `config/local.env`。
后续命令由启动器调用虚拟环境，无需手动激活。请在仓库根目录执行。

### 选择一种部署方式

| 方式 | 应用运行位置 | 数据库与缓存 | 启动命令 |
| --- | --- | --- | --- |
| 本地 | 宿主机 Python / Node 进程 | 自行配置本地或远程 PostgreSQL | `python minidsh.py web` |
| 混合 | 宿主机 Python / Node 进程 | Docker 提供 PostgreSQL 和 Redis | `python minidsh.py web --mode hybrid` |
| Docker | 前后端均在容器内 | Compose 提供 | `python minidsh.py docker` |

**本地部署**：编辑 `config/local.env`，填写自己的数据库连接，例如：

```dotenv
DATABASE_URL=postgresql://saas:your_password@127.0.0.1:5432/saas
REDIS_URL=redis://127.0.0.1:6379/0
```

数据库与扩展的安装、初始化权限说明见 [部署文档](docs/deployment.md)。然后启动：

```sh
python minidsh.py doctor
python minidsh.py web
```

**混合部署**：安装 Docker 后，确认 `config/local.env` 的数据库连接与
[基础设施配置](deploy/compose.infra.yaml) 一致，再运行：

```sh
python minidsh.py web --mode hybrid
```

它只为数据库和 Redis 启动容器，应用与工具仍可在宿主机运行。

**Docker 部署**：从模板创建配置，调整环境变量与宿主目录挂载：

```sh
# Linux / macOS
cp config/docker.env.example config/docker.env
# Windows PowerShell：Copy-Item config/docker.env.example config/docker.env

python minidsh.py docker
# 等价于：docker compose --env-file config/docker.env up -d --build
```

当前根目录 Compose 含 Windows 示例挂载（如 `D:/jk/Nexus` 和整盘路径），部署到其他电脑时请按实际目录修改。
仅需容器数据库时，使用混合部署的跨平台基础设施配置即可。

### 打开工作台，完成第一次对话

1. 访问 **http://localhost:4000**，进入「Agent 管理」，创建自己的智能体。
2. 填写模型 API Key、Base URL、Model 和系统提示词，选择工具与技能，保存配置。
3. 进入「工作区」，新建会话并选择项目目录，发送第一条消息。
4. 需要外部能力时，再配置 MCP 服务、技能来源或知识库。

应用 API 默认使用 **http://localhost:8000**，就绪检查为 `/health`。
前端独立执行 `npm run dev` 时默认端口为 **4100**。

初次启动没有截图中的演示 Agent。Redis 缓存、论文总结、Overleaf 登录与 FAQ 向量检索各有自己的配置，
详见 [部署文档](docs/deployment.md) 与 [配置目录](config/README.md)。

### 常用命令

```sh
python minidsh.py doctor                 # 检查环境
python minidsh.py web                    # 开发模式，启动前后端
python minidsh.py web --prod             # 构建前端后启动，关闭后端自动重载
python minidsh.py build                  # 仅构建前端
python minidsh.py start                  # 使用已有构建启动
python minidsh.py dev --backend-only     # 仅启动服务端
python minidsh.py infra                  # 仅启动容器数据库与 Redis
```

`web --prod` / `start` 的前端由 Vite preview 提供。正式对外部署时，应另行配置反向代理、HTTPS 和进程管理。

更换端口或前端：

```sh
python minidsh.py web --backend-port 18000 --frontend-port 14000
python minidsh.py web --frontend web2      # 需要先准备声明了该 profile 的前端包
python minidsh.py web --dir /path/to/your/frontend
```

无 HTTP 入口：先在工作台创建并保存 Agent，再用虚拟环境解释器执行一轮任务。

```sh
# Windows
.venv/Scripts/python.exe -m agent_platform_cli run --agent your_agent_key "请介绍当前可用的技能"
# Linux / macOS
.venv/bin/python -m agent_platform_cli run --agent your_agent_key "请介绍当前可用的技能"
```

## 插件架构

```mermaid
flowchart TB
    CLI["minidsh 启动器"] --> LOADER["PluginLoader<br/>合并 YAML、导入模块、校验参数"]
    LOADER --> CTX["minidsh-cordis 根 Context<br/>服务注册、依赖顺序、启动和清理"]
    CTX --> WEB["HTTP API 插件"]
    CTX --> AR["Agent Runtime / Loop"]
    CTX --> CAP["模型 / 会话 / 工具 / 技能 / 记忆 / 数据库插件"]
    UI["React + Vite 客户端插件壳"] -->|JSON-RPC / HTTP / SSE| WEB
    WEB --> GW["RPC Connection / Gateway"]
    GW --> CT["Agent / Session / Workspace Controller"]
    CT --> AR
    CT --> CAP
    WEB --> HTTP["聊天流 / 文件 HTTP 接口"]
    HTTP --> AR
    HTTP --> CAP
    AR -->|通过 ctx 获取服务| CAP
    CAP --> LOG["Session 事件日志"]
    LOG --> VIEW["历史 / 执行轨迹 / 恢复状态"]
```

- **服务端插件**通过 YAML 的 `use: 模块:导出对象` 指定。Cordis 按必选和可选依赖启动插件。
  插件在 `setup(ctx, config)` 中用 `ctx.provide()` 发布服务、用 `ctx.require()` 获取依赖，
  用 `ctx.track()` 绑定工具、扩展等注册的生命周期。SDK 定义这些服务的业务契约。
- **Agent Runtime 与 Loop**：Runtime 装配一次请求与插件扩展，Loop 执行模型与工具循环；
  skill-tools 提供 pre-step 钩子，向模型按需注入技能目录和指令。
- **统一工具服务**：tools-default 持有模型侧工具注册表。一个插件可以提供零个或多个工具，
  MCP、沙箱和技能工具都接入这条调用链。
- **技能的渐进式披露**：摘要目录 → `SKILL.md` → 指定参考资料。Overleaf 的说明与其实际 MCP 连接分别配置。
- **会话事件日志**：用户消息、模型输出、工具调用和结果构成执行事实；历史、轨迹与恢复状态由其派生。
- **客户端插件**：前端包通过 `dsh.client` 声明入口，Host 组合启动图，浏览器懒加载模块并通过 slots 组合 UI。

所有 HTTP/SSE/WebSocket 路由都归 HTTP 插件（`packages/host/http-api/src/routes/`），
RPC 已覆盖的操作见 [接口清单](docs/rpc-api.md)。
完整设计见 [插件运行时架构](docs/plugin-architecture.md)。

### 配置插件

默认实例定义在 [默认插件清单](packages/plugin/default/src/plugins.yaml)。
源码版的覆盖配置写到 `config/plugins.yaml`，发布版写到当前 profile 的 `plugins.yaml`。
例如把 Agent Loop 的工具并发上限改为 2。

```yaml
version: 1
patches:
  - id: agent-loop
    config:
      max_parallel_tools: 2
```

用 `includes` 引入其他 YAML，用 `groups` 批量启停，用 `patches` 按实例 ID 覆盖配置。
启动时还可以传 `--plugin-patch override.yaml` 叠加一层。
Web 运行中会读取 YAML 变更，重装受影响的插件。涉及宿主绑定的 HTTP 或工具服务时需要重启。

源码版可以从 [配置示例](config/plugins.yaml.example) 开始。外部插件先安装到目标 Python 环境，
再在 YAML 中声明 `use`。发布版的安装命令会把入口写进 profile。旧第三方插件需要改为导出
Cordis 插件，并补上 `use`。 [分层配置与热更新](docs/startup.md#叠加配置与热更新) · [插件开发](docs/plugin-development.md)

## 配置与数据放在哪里

| 位置 | 用途 |
| --- | --- |
| `config/local.env` | 本地进程配置，由 setup 生成 |
| `config/docker.env` | Docker Compose 配置，从模板复制 |
| `config/plugins.yaml` | 默认插件实例的覆盖或追加配置 |
| `.venv/` | 仓库中的 Python 虚拟环境 |
| `packages/client/node_modules/` | 默认前端的 npm 依赖 |
| `~/.minidsh/workspaces/` | 本地会话工作目录 |
| `~/.minidsh/skills/` | 本地安装的技能 |
| `~/.minidsh/cache/paper-mcp/` | 本地论文缓存 |
| PostgreSQL | Agent 配置、会话持久化和其他业务数据 |
| Docker volumes | 容器部署的数据与缓存，见 Compose 配置 |

本地数据根目录可用 `MINIDSH_HOME` 修改，子目录也可单独配置；Windows 下 `~` 表示当前用户目录。
`config/local.env`、`config/docker.env` 和用户插件配置不应包含在提交中。

本地默认使用宿主机沙箱 provider，示例配置为 `workspace-write`；支持只读、工作区可写和完全访问模式，
也可设置 `SANDBOX_BACKEND=docker` 使用容器。模式、审批与操作系统支持见 [原生沙箱](docs/native-sandbox.md)。

## 开发与文档

从 [文档导航](docs/README.md) 选择阅读路径。想跟代码可以从 [启动与插件运行](docs/startup.md) 开始，随后读 [Profile 与配置](docs/profiles.md)、[插件开发指南](docs/plugin-development.md) 和 [开发与发布](docs/development.md)。

```text
minidsh.py             统一安装与启动入口
apps/
  server/              ASGI carrier（uvicorn 入口）
  cli/                 agent-platform run / serve
packages/
  plugin/              SDK、加载器与默认插件清单
  boot/app-boot/       合并配置并启动 Cordis
  agent/               配置、运行时、Loop 与系统提示词
  api/                 RPC Connection、Gateway 与业务 Controller
  host/http-api/       FastAPI 应用与 HTTP 适配
  host/plugin-inventory/ 已启动插件投影
  session/             事件、存储、持久化、标题、恢复与投影
  memory/              上下文压缩、会话笔记与智能体记忆
  llm/                 模型公共契约与 provider
  tools/               工具服务、调度与宿主适配
  skills/              技能中心、文件来源与 skill 工具
  workflow/            工作流服务、节点注册表与响应缓存
  faq/                 FAQ 服务、匹配与向量化
  integrations/        渠道集成（闲鱼）
  sandbox/             沙箱 provider、策略与工具
  mcp/                 MCP 连接与各类集成
  client/              React + Vite 插件壳与页面
vendor/cordis/         Python 插件内核 minidsh-cordis
tests/integration/     跨包集成测试
config/                环境与插件配置模板
docs/                  部署、架构与使用说明
```

| 文档 | 内容 |
| --- | --- |
| [部署方式](docs/deployment.md) | 本地、混合、Docker、前端 profile 和排查方式 |
| [配置说明](config/README.md) | 配置文件与覆盖规则 |
| [插件架构](docs/plugin-architecture.md) | 服务契约、依赖、生命周期与宿主边界 |
| [RPC API](docs/rpc-api.md) | 方法清单、请求格式、客户端与迁移范围 |
| [Agent 插件](packages/agent/README.md) | Runtime、Loop、上下文与运行生命周期 |
| [智能体记忆](docs/memory.md) | 上下文用量、压缩摘要、SESSION.md 与 MEMORY.md |
| [技能与命令](docs/skills-commands.md) | 技能绑定、安装和按需加载 |
| [客户端](packages/client/README.md) | 启动图、模块加载与 slots |
| [原生沙箱](docs/native-sandbox.md) | 宿主机执行与受限模式 |
| [Overleaf](docs/overleaf-mcp.md) | 可选的 Overleaf 工具集成 |

前端构建与交互检查：

```sh
cd packages/client
npm run build
npm run test:e2e
```

后端示例测试（使用已安装插件的虚拟环境）：

```sh
python -m pytest packages/api/gateway/tests packages/agent/runtime/tests -q --import-mode=importlib
```

Playwright 需要可用的浏览器；可安装 Chromium，或通过 `PLAYWRIGHT_CHANNEL` 指定已安装的浏览器。
截图脚本的使用见 [演示图片说明](docs/images/README.md)。

## 致谢

插件装配、Agent Loop 与客户端模块设计参考 DeepSeek Harness。Python 插件内核参考
[Cordis](https://github.com/cordiverse/cordis)。界面使用 React、Vite、React Flow 等开源项目。
各包附带的第三方技能与集成遵循其来源许可，详见对应目录中的 NOTICE / LICENSE。
