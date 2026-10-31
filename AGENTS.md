# AGENTS.md

## 前端

- `packages/client/`：默认前端，DSH 风格的浏览器端插件壳，端口 4000（独立开发时 4100）。
  `window.__DSH_BOOT__` 启动图 + lazy CommonJS loader + slots；插件在
  `packages/client/plugins/*`，每个包的 `package.json` 声明 `dsh.client`，入口是
  `src/client.tsx`。聊天、Agent、知识库、集成、MCP、记忆、工作流、工作区、
  `/agents/*` 均已迁移；前端**没有登录页**，打开 `/` 直接进入 `/dashboard`。
- `packages/client/legacy/`：迁移页面的源码（`@/` alias 指向这里）。旧的根目录
  `frontend/` 已移除，Docker Compose 的 `frontend` 服务也改为构建 `packages/client`。
- 前端 profile 由前端包自己的 `package.json` 声明 `dsh.frontend`（和 DSH 的
  `dsh.client` 同为包自描述）。`minidsh` 扫描 `packages/*/package.json`；
  `python minidsh.py web --profile web2` 按目录名/包名选择，`--dir` 指向仓库外目录。
  `minidsh.py` 不 import 前端代码，也不使用中心化前端配置文件。
- 后端 API 仍由 Python/FastAPI 提供；`packages/client` 在开发/预览时把 `/api` 代理到
  `BACKEND_URL`（默认 `127.0.0.1:8000`）。前端不实现登录/登出，也不依赖 cookie；
  后端保留的 `/api/auth/login` 是可选接口。

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

- 这是**参考实现**，不是本项目的运行时依赖。本项目的后端插件系统在 `packages/plugin/sdk` / `packages/plugin/runtime`。
- DSH 的 client modules 需要 Node 侧 web server + 浏览器模块加载器；`packages/client` 是按其协议实现的精简版（boot graph + lazy CJS + slots），不是直接依赖 DSH 包。
- 移植目标是让前端按 DSH 的方式“一切皆插件”：插件包声明 client 入口，Host 组合启动图，浏览器懒加载 bundle，UI 通过 slots 组合。
