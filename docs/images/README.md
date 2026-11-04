# README 演示图片

这里的 PNG 是当前项目 React 前端的实际浏览器截图，使用隔离的固定演示响应。
截图中的 Agent、会话、工作流与回复均为示例数据；截图不访问真实数据库、不调用在线模型，也不连接外部 MCP。
它们用于展示界面和配置方式，不作为模型执行成功或集成连接状态的证明。

| 文件 | 页面 |
| --- | --- |
| `workspace.png` | 会话列表、Markdown 对话与工作区文件 |
| `agents.png` | 自定义智能体管理 |
| `agent-settings.png` | 智能体的工具与技能配置 |
| `workflow.png` | React Flow 工作流画布 |

演示数据和截图步骤统一位于根目录 `scripts/capture-readme.mjs`。

安装默认前端依赖后，在第一个终端运行：

```sh
cd packages/client
npm run dev -- --host 127.0.0.1 --port 4176 --strictPort
```

第二个终端在仓库根目录运行：

```sh
# Windows 上默认使用已安装的 Microsoft Edge
node scripts/capture-readme.mjs
```

其他环境可安装 Playwright Chromium，并指定通道：

```sh
# 在 packages/client 中安装浏览器
npx playwright install chromium
# 回到仓库根目录
PLAYWRIGHT_CHANNEL=chromium node scripts/capture-readme.mjs
```

PowerShell 设置通道：`$env:PLAYWRIGHT_CHANNEL='chromium'`。
通过 `README_BASE_URL` 可指定其他前端地址。API 响应由浏览器上下文拦截，截图不会向目标服务保存配置或示例数据。
脚本检查关键内容已出现及页面运行错误，再输出四张图片；完成后自动关闭浏览器。
