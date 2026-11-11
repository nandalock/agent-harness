# CLAUDE.md

## 启动与插件

- 发布入口 `minidsh web --profile web` 使用 `~/.minidsh/profiles/web` 的 Python 环境和插件清单。
- 源码入口 `python minidsh.py web` 使用仓库环境。开发、打包和阅读顺序见 [docs/README.md](docs/README.md)。

## 前端

- `packages/client/`：默认前端，DSH 风格的浏览器端插件壳，端口 4000（独立开发时 4100）。
  `window.__DSH_BOOT__` 启动图 + lazy CommonJS loader + slots。Shell 和首页在
  `packages/client/plugins/*`。工作区、Agent、聊天等功能的浏览器入口在各自 Python
  包的 `client/src/client.tsx`，编译后作为包资源交付。后端 `/api/plugins` 提供已启动
  插件的浏览器入口。打开 `/` 直接进入 `/dashboard`。
- `packages/client/legacy/`：迁移页面的源码（`@/` alias 指向这里）。旧的根目录
  `frontend/` 已移除，Docker Compose 的 `frontend` 服务也改为构建 `packages/client`。
- 前端 profile 由前端包自己的 `package.json` 声明 `dsh.frontend`（和 DSH 的
  `dsh.client` 同为包自描述）。`minidsh` 扫描 `packages/*/package.json`；
  `python minidsh.py web --frontend web2` 按目录名/包名选择，`--dir` 指向仓库外目录。
  `minidsh.py` 不 import 前端代码，也不使用中心化前端配置文件。
- 后端 API 仍由 Python/FastAPI 提供；`packages/client` 在开发/预览时把 `/api` 代理到
  `BACKEND_URL`（默认 `127.0.0.1:8000`）。前端不实现登录/登出，也不依赖 cookie；
  后端保留的 `/api/auth/login` 是可选接口。

## 插件运行时（服务注入）

- 服务实例只存在于 `PluginRuntime`：插件 `setup()` 用 `ctx.require` / `ctx.get`
  取依赖、`ctx.provide` 发布服务；禁止模块级 `get_*` / `set_*` 服务单例。
- 导入包不得创建服务实例或注册任何东西；契约、错误、纯函数可以正常 import。
- session 能力拆在 `packages/session/*`：`SESSIONS`、`SESSION_PERSISTENCE`、
  `SESSION_TITLE`、`SESSION_RECOVERY`、`SESSION_PROJECTION`。
  `SessionRecoveryService` / `SessionTitleService` 由插件构造并注入 store、
  persistence、LLM；后端只剩 `tests/integration/session/` 集成测试。
- `AgentRuntime` 只依赖 `AGENTS`、`AGENT_RUNS`、`RUNTIME_PROMPTS`、`LLM`、
  `AGENT_SANDBOX`、`SESSION_RECOVERY`、可选 `SESSION_TITLE`，不再引用 backend
  适配器或全局单例。细节见 `docs/plugin-architecture.md`。
- HTTP 由 `packages/host/http-api` 插件提供；REST/SSE/WebSocket 路由定义都在
  `packages/host/http-api/src/routes/`。`apps/server` 只是 ASGI carrier，启动 runtime
  后转交 `http.app.v1`。无 HTTP 入口：`python -m agent_platform_cli --agent default "..."`。
- 业务接口走 `POST /api/rpc`：`packages/api/gateway`（方法登记/校验）、
  `packages/api/connection`（JSON-RPC 2.0）、`packages/api/{workspace,agents,sessions}`
  （Controller 插件）。前端用 `packages/client/legacy/lib/remote/`，TS 类型由
  `scripts/generate_rpc_contracts.py` 生成。旧 REST 路由（已迁移部分）只转发同一个
  Controller；聊天 SSE、文件传输保留独立 HTTP。详见 `docs/rpc-api.md`。

## 参考代码：DeepSeek Harness

本地有一份 DeepSeek Harness 源码，作为前端插件化（client modules / slots）的参考实现：

- 路径：`D:\jk\Code\github\deepseek-harness`
- 远端：https://github.com/deepseek-ai/deepseek-harness
- 当前 checkout：`d743267388`
- License：MIT
- 仓库使用 pnpm workspace，要求 Node 22+（构建 Web 前端：`pnpm install && pnpm build:web`）

关键包：

| 包 | 作用 |
| --- | --- |
| `packages/client/modules` | 扫描 `dsh.client`、组合 `window.__DSH_BOOT__` 启动图、提供 `/plugins` combo bundle 与浏览器 lazy CommonJS module loader |
| `packages/client/web` | 浏览器启动内核、Cordis loader、静态 module table |
| `packages/client/ui-slots` | typed slot registry、component factories、derived props |
| `packages/client/ui-renderer` | 唯一把 observable 绑定到 React 的 renderer |
| `packages/host/webserver` | 浏览器 HTTP carrier、命名路由、index injection |
| `packages/host/frontend-static` | SPA dist fallback / 静态资源服务 |
| `packages/client/ui-*` | 各类 feature UI 插件示例（chat、trajectory、settings、sidebar 等） |

注意：

- DeepSeek Harness 提供参考代码。本项目的插件框架位于 `packages/framework`，业务契约位于 `packages/plugin/sdk`。
- DSH 的 client modules 需要 Node 侧 web server + 浏览器模块加载器；`packages/client` 是按其协议实现的精简版（boot graph + lazy CJS + slots），不是直接依赖 DSH 包。
- 移植目标是让前端按 DSH 的方式“一切皆插件”：插件包声明 client 入口，Host 组合启动图，浏览器懒加载 bundle，UI 通过 slots 组合。
