# Agent Harness 项目经历与面试准备

适用岗位：AI Agent / 大模型应用开发。项目性质：个人项目。
本稿依据当前仓库代码、设计文档和公开资料编写；项目起止时间需按实际经历填写。

## 项目名称的公开参考

推荐名称：**智能体运行平台（Agent Harness）**。这是结合官方术语和本项目实现范围整理的中文简历名称。

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 官方直接将项目定位为开源 agent harness。
- [LangChain Deep Agents](https://github.com/langchain-ai/deepagents) 官方将其定位为 agent harness，提供文件系统、上下文管理、工具和人工介入等能力。
- [Microsoft Agent Harness](https://learn.microsoft.com/en-us/agent-framework/concepts/harness) 将 Harness 定义为驱动模型及工具调用、管理对话状态与上下文、应用审批策略的运行支撑层。
- [Letta](https://docs.letta.com/) 使用构建有状态智能体的平台这一定位。

本项目具有执行循环、工具调度、会话持久化、权限审批和管理界面，因此采用“运行平台”描述交付形态，并用“Agent Harness”说明技术核心。

## 可直接放入简历的版本

**智能体运行平台（Agent Harness）｜个人项目｜独立开发**

**技术栈：** Python、FastAPI、asyncio、PostgreSQL、MCP、Docker、Next.js、TypeScript、React Flow。

**项目描述：** 面向智能客服、知识问答及工具执行场景，独立开发智能体运行平台（Agent Harness），围绕执行循环、工具调度、会话管理和权限控制，支持多步任务执行、过程追踪与人工干预，并提供可视化工作流及会话工作区。

- **Agent 运行时：** 实现事件驱动的 LLM–Tool 执行循环，解耦模型适配、请求重试与循环控制；支持流式输出、有限重试、取消传播，以及步数、调用次数、总时长和重复调用限制，约束异常与失控执行。
- **工具接入与调度：** 设计 Registry / Runtime / Executor 分层，通过统一工具描述接入 MCP 与内置工具；基于 asyncio 实现有界并发、独占屏障及按调用顺序提交结果，在并行执行的同时维持会话事件与工具消息顺序。
- **会话持久化与恢复：** 以 Event Log 统一记录执行事实，派生模型上下文、执行轨迹和 Token 用量；实现 PostgreSQL 幂等写入、按需冷恢复及中断日志修复，补齐缺失的工具结果与轮次结束事件，支持恢复后的多轮对话。
- **执行权限控制：** 实现 Bash / Python 工具的 Docker 临时容器执行，设计只读、工作区可写和完全访问三种文件权限模式；结合路径解析、资源限制与人工升权审批，在沙箱或审批不可用时拒绝执行。
- **运行中人工干预：** 基于双队列实现当前步骤指令修正与下一轮任务追加，在步骤边界注入上下文；通过会话级运行登记防止同进程内重复执行，并贯通投递 API、SSE 认领回执与前端待投递状态。
- **上下文与提示词工程：** 实现按身份、角色、工具指导和运行上下文分段组装 System Prompt，由同一次工具求值生成 Schema 与使用指导；支持严格变量校验、配置逐轮生效与提示词预览，保持工具定义和提示词同步。

## 简历空间紧张时的压缩版

**智能体运行平台（Agent Harness）｜个人项目｜独立开发**

**技术栈：** Python / FastAPI / asyncio / PostgreSQL / MCP / Docker / Next.js。

独立开发面向知识问答与工具执行的智能体运行平台（Agent Harness），提供执行循环、工具调度、会话恢复与人工干预能力。

- 实现事件驱动的 LLM–Tool 执行循环，支持流式响应、有限重试、取消传播及执行预算限制，并解耦模型适配与循环控制。
- 统一接入 MCP 和内置工具，实现有界并发、独占屏障与结果按序提交，兼顾工具执行并行性和会话顺序。
- 基于 Event Log 派生上下文与执行轨迹，实现 PostgreSQL 幂等持久化、冷恢复和中断日志修复。
- 构建 Docker 工具沙箱、三种文件权限模式与人工升权审批；通过双队列和 SSE 回执支持运行中指令修正及任务追加。
- 按轮组装 System Prompt，同源生成工具 Schema 与使用指导，支持变量校验、配置更新和提示词预览。

## 根据岗位要求替换的补充条目

不要把所有条目同时塞进简历。若岗位突出 RAG 或业务落地，可用以下条目替换推荐版中相关度较低的一条。

- **知识检索与意图路由：** 构建 pg_trgm 匹配、bge-m3 向量召回和 CrossEncoder 重排序的 FAQ 检索链路，结合 LLM 生成答案；实现关键词、向量匹配与 Function Calling 级联路由，支持按置信度逐级选择处理 Agent。
- **平台交付：** 基于 Next.js 与 React Flow 实现工作流配置界面，将节点与连线转换为 LangGraph 执行图；提供智能体配置、知识库管理、MCP 工具绑定、会话文件浏览与预览，并使用 Docker Compose 编排部署。
- **异常场景验证：** 为执行循环、工具调度、日志修复和沙箱设计边界测试，覆盖限流重试、流式截断、取消、调用结果配对、并发屏障与权限拒绝等场景。

## 为什么这样写

北卡州立大学计算机科学职业服务的简历指南建议：用动作动词描述个人工作，突出与岗位相关的经历，并把任务写成能说明实现方法和影响的成果。这份稿件据此采用“解决的问题 → 实现方法 → 可确认的能力”的组织方式；有实测数据再量化，没有数据时写清工程结果。

来源：[NC State 技术简历指南](https://leslierp.wordpress.ncsu.edu/files/2020/08/resume-tips-202_11751972-1.pdf)。

Anthropic 的 Agent 工程文章讨论了 Agent 与预定义工作流的区别，并强调工具接口设计和实现透明度；其 Harness 文章进一步讨论跨会话状态、进度交接与验证。结合你的代码，本稿将运行时、工具、状态、权限和人工干预作为主要亮点。这是对项目定位的归纳，不表示项目已经实现文章中所有长任务能力。

来源：[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)、[Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。

## 面试时约一分钟的介绍

这个项目是我独立开发的智能体运行平台（Agent Harness），应用场景包括智能客服、知识问答和工具执行。我主要解决的是模型开始调用工具以后，执行过程怎么受控、状态怎么保存，以及用户怎么在运行中纠正方向。

运行时采用事件驱动的 LLM–Tool 循环，加入重试、取消和执行预算。工具层统一接入 MCP 与内置工具，允许并行执行，同时通过独占屏障处理共享工作区操作，并按调用顺序提交结果。会话以事件日志为事实来源，上下文和轨迹都从它派生，支持持久化、冷恢复和中断修复。执行侧还实现了 Docker 沙箱和人工升权审批，前端支持在 Agent 运行中追加指令。

我认为这个项目最有代表性的设计是工具调度与会话恢复：既要让任务执行有效率，也要保证异常、取消和重启以后，工具调用记录与模型上下文仍然可以被解释和继续使用。

## 面试追问与代码依据

| 追问 | 回答重点 | 代码依据 |
| --- | --- | --- |
| 为什么说这是 Harness？ | 平台实现了模型外部的执行循环、工具调度、状态记录、权限控制和运行中干预；可视化工作流是另一个配置入口。 | `backend/agents/runtime/agent_runtime.py`、`backend/agents/runtime/loop/agent_loop.py` |
| 为什么并发执行还要按序提交？ | 区分实际执行顺序与日志提交顺序；结果先进入缓冲，再按模型给出的调用顺序提交，使上下文和轨迹顺序稳定。不要把“所有模型协议都禁止乱序工具结果”说成通用结论。 | `backend/tool_system/runtime/scheduler.py` |
| 独占屏障用来解决什么？ | Bash / Python 等工具可能共享会话工作区；独占调用启动前排空在途任务，并在执行期间阻止新任务进入。 | `backend/tool_system/registry/descriptor.py`、`backend/tool_system/runtime/scheduler.py` |
| 重启后怎么恢复？ | 读取持久化事件并回放；若日志尾部存在未结束轮次，补记工具结果未知或未执行的事件，再闭合步骤和轮次。恢复不等于重新启动原来被中断的工具进程。 | `backend/agents/runtime/session/persistence/postgres.py`、`backend/agents/runtime/session/repair.py` |
| 用户中途发消息怎么办？ | 当前步骤修正进入 next-step 队列，追加任务进入 next-turn 队列；在步骤边界认领并追加 user/message 事件，使用 msg_id 将 SSE 回执与前端气泡对齐。 | `backend/agents/runtime/loop/inbox.py`、`backend/api/agents.py` |
| 提示词与工具定义怎么同步？ | 一次求值获得实际可见的工具 Schema 和 guidance，先确定工具集合，再组装工具指导段，避免分别维护两份工具说明。 | `backend/agents/runtime/system_prompt/assembler.py` |

## 当前实现边界与数据口径

- 这是个人项目。项目起止时间按实际开发时间填写，不把 Git 首次提交时间自动等同于项目开始时间。
- 本稿没有写用户量、成功率、P95 延迟或成本下降比例，当前查看的材料不足以证明这些指标。
- 会话恢复覆盖已经持久化的事件。主链路在轮次结束时批量写入，不能据此宣称执行中崩溃绝不丢状态。
- 双队列和运行登记表目前在进程内存中；待投递输入的持久化队列尚未实现，同会话互斥也不是分布式锁。
- 长期记忆模块存在，但 README 将“接入主 Agent Runtime”列为未完成项；不要写成主链路已实现长期记忆或自动上下文压缩。
- Docker 默认使用 bridge 网络；三种模式主要表达文件访问效果，不表示已经实现断网隔离或绝对安全。完全访问模式具有更宽的执行权限。
- 仓库中的 `test_agent_loop.py`、`test_scheduler.py`、`test_repair.py`、`test_sandbox.py` 分别定义 44、32、12、85 个测试函数，共 173 个。数字表示静态统计的测试函数数，不表示全部测试已通过、测试覆盖率或业务成功率。
- 本次尝试运行 AgentLoop 自检时，本机 Python 缺少 aiohttp，因此未完成测试执行。本文依据代码和已有测试内容描述能力，不作本次运行通过的声明。

后续若要补充量化成果，优先测量：固定任务集成功率、相同工具集的串行/并行耗时、故障注入后的消息闭合与恢复情况。记录任务集、样本数、模型、配置和测量方式后，再将真实结果写进简历。
