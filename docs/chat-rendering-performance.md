# 聊天懒加载与虚拟滚动

## 参考实现

参考本机 `D:/jk/Code/github/deepseek-harness` 的 `d743267388` 版本：

- `packages/client/ui-trajectory/src/client/TrajectoryTable.tsx`：TanStack Virtual、稳定行键、动态行高、底部跟随及历史插入锚点。
- `packages/client/ui-chat/src/client/chat/TurnNavigator.tsx`：只渲染可见范围及少量预取行。
- `packages/client/ui-primitives/src/markdown/useViewportHighlighting.ts`：共用 IntersectionObserver，代码块进入视口后再高亮。
- `packages/client/ui-sidebar-documentpreview/src/client/pdf/LazyPdfBody.tsx`：动态导入较重的预览组件。

参考项目的轨迹表和回合导航使用虚拟列表，不能据此称其整个聊天正文也用了同一套虚拟列表。本次在本项目里独立实现共享组件，借鉴上述设计，没有直接复制 Cordis 插件代码。

## 已实现

工作区聊天和 `/agents/[id]` 测试页共用 `VirtualTranscript`：

- 首次加载最近 50 条消息，点击“加载更早的消息”再取上一页。
- 新接口 `GET /api/chat/conversations/{id}/messages/window?size=50&before_id=...` 按消息 ID 做游标分页，每页按阅读顺序返回。旧的 page/size 接口保持兼容。
- 分页查询带租户和会话条件；新增 `(tenant_id, conversation_id, id)` 索引。查询多取一条判断是否还有历史，不因新消息插入而产生 offset 偏移。
- 只挂载可见消息及上下各 4 条预取行，实际行高由 ResizeObserver 测量。插入旧消息保留可见消息的位置；在底部时跟随追加内容，上翻后显示“最新消息”按钮。
- 服务端消息 ID、运行中回合 ID 和 steer ID 保持稳定。展开状态保存在列表级，虚拟行卸载再挂载不会丢失工具/思考卡的展开状态。
- SSE 请求和轨迹数据由父组件持有，卸载虚拟行不会中止任务。历史回合使用 memo，避免每个流式增量都重新解析正文。

消息窗口使用顶部/底部占位空间保留虚拟化，已挂载消息按正常文档流排列。
此前每条消息分别绝对定位，容器宽度观察器晚于消息观察器执行时，会清空刚更新的高度，
长消息便按 160px 的估算高度定位并互相覆盖。现在宽度变化后会立即补测已挂载行；
即使测量尚未完成，正常文档流也会把后一条消息排在前一条实际内容之后。

历史接口只返回本页消息对应的回合轨迹，不再让浏览器另取整场 trajectory：

- 新回复的 trace 保存 `session_id` 与 `turn_start_seq`，直接定位对应事件区间。
- 投影指定区间时保留原始回合编号和节点 ID，每条消息只携带自己的 usage。
- 遗留消息缺少事件指针时，仅在完成回合数与会话 agent 消息数一致时按全局消息序号兼容，并排除早于回合开始的历史回复；无法确认的情况保留 thinking/trace 兜底，避免随便取最后一轮工具记录。

代码与文件预览：

- `LazyCode` 共用一个 IntersectionObserver，在视口周围 200px 内才激活高亮。高亮核心和语言语法动态导入并复用 Promise；不再静态引入所有语言或运行 highlightAuto。
- 未知语言、未标语言及超过 100,000 字符的代码块显示经过 React 转义的纯文本。
- 右侧预览仅在面板打开且选中“预览”标签时挂载、加载文件；Markdown 预览按需加载。切换/关闭预览会取消在飞请求并回收 Blob URL。
- 超过 500 行的代码/文本文件按每块 80 行虚拟显示，保留水平滚动；为保证跨块注释/字符串不被错误着色，超长文件显示纯文本源码。

## 验证与范围

浏览器测试使用 2,000 条模拟历史，连续加载到 500 条后，挂载的消息行仍少于 25 个（1440×900 视口）。验证了插入历史后的锚点误差小于 5px、展开状态恢复、失败重试、流式阅读不被打断、代码高亮按视口激活，以及 10,000 行文件预览的 DOM 范围限制。这些是功能/DOM 规模验证，不是生产延迟或内存百分比的性能基准。

后端使用真实 PostgreSQL 的独立测试 schema，验证并发追加后历史分页无丢失/重复、租户隔离与参数校验；同时回归 Session 和检查点测试。最终通过 31 项后端测试、6 项浏览器测试、TypeScript 检查和 Next.js 生产构建。

当前冷恢复仍读取完整 Session Event Log，随后只投影本页需要的回合；没有实现数据库事件日志的按回合范围查询。聊天虚拟化单位是消息，一条消息内部极长的 Markdown 或大量工具节点仍需要单独优化。客服聊天管理页及其他业务列表不在本次改造范围。

消息重叠修复的浏览器回归位于 `packages/client/tests/transcript.spec.ts`，使用实际的
VirtualTranscript、AgentTurn 和 Markdown 样式。5 项测试覆盖侧栏宽度变化、观察器回调
顺序交错、正文与展开面板增高、历史插入锚点，以及上翻阅读后回到最新消息；
其中回调顺序交错场景在修复前稳定出现 404px 的消息重叠。

运行检查：

```powershell
# 前端浏览器测试；Windows 已安装 Edge 时可指定通道
cd packages/client
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e

# 或安装测试 Chromium 后直接运行
npx playwright install chromium
npm run test:e2e

# TypeScript 检查与 Vite 生产构建
npm run build
```

```powershell
# 在项目根目录；DSN 必须指向你明确选择的测试 PostgreSQL
$env:CHECKPOINT_TEST_DSN = 'postgresql://user@127.0.0.1:55432/postgres'
python -m pytest backend/services/chat/test_history.py backend/services/chat/test_history_postgres.py backend/agents/runtime/session/tests/test_session.py backend/agents/runtime/session/tests/test_checkpoint.py -q
```
