# Agent 长任务检查点与恢复修改方案

本方案基于 2026-10-12 的本地源码：Agent Harness `4ca8233`，DeepSeek Harness `d743267388`。目标是让任务中途崩溃后保留已确认保存的执行记录，并在用户点击“继续任务”后恢复上下文、核实未知结果，再继续原任务。

当前已实施第一阶段：严格检查点、PostgreSQL 写入所有权、修复先提交、状态与继续 API、前端继续按钮和恢复提示。恢复来源直接记录在新 `turn/start.resumed_from`，与继续输入同批提交，无需再增加单独的 turn/resume 事件。任务上下文通过 task/input 保存。第二阶段的后台自动接管仍是可选后续设计。

## 1. 采用 DeepSeek 的哪些设计

DeepSeek 将“保存数据”和“决定何时必须保存”分开：持久化后端保存 Session Event Log，`session-checkpoint-policy` 在关键位置等待 `flush` 成功，AgentLoop 在恢复时补齐中断日志。

| 本地参考 | 已核实的行为 |
| --- | --- |
| [检查点策略](D:/jk/Code/github/deepseek-harness/packages/session/session-checkpoint-policy/src/index.ts:63) | 模型请求前、顶层工具执行前、下一步开始前等待日志持久化；失败就阻止后续动作。 |
| [恢复入口](D:/jk/Code/github/deepseek-harness/packages/core/agent-loop/src/index.ts:875) | 先获得写入所有权，再读日志、生成修复事件、写回修复事件、构造会话。 |
| [中断结果与收尾](D:/jk/Code/github/deepseek-harness/packages/core/session/src/repair.ts:32) | 未配对工具调用补成“未开始”或“结果未知”，随后关闭旧步骤和旧轮次；不自动重试未知操作。 |
| [持久化能力限制](D:/jk/Code/github/deepseek-harness/packages/session/session-persistence/README.md:155) | 恢复会关闭中断的旧轮次，没有从旧轮次内部直接续执行的机制。 |
| [跨进程写入所有权](D:/jk/Code/github/deepseek-harness/packages/session/session-persistence-jsonl/src/lease.ts:1) | JSONL 后端使用操作系统锁保护写入，进程退出后释放。 |
| [真实崩溃验证](D:/jk/Code/github/deepseek-harness/packages/session/session-checkpoint-policy/tests/crash-recovery.e2e.ts:91) | 子进程在模型派发后或工具产生副作用后被杀，再读取日志检查恢复结果；该文件的测试在 Windows 跳过。 |

建议沿用 PostgreSQL 和现有事件格式，实现相同的检查点和恢复语义。“继续任务”通过新轮次执行，旧轮次保留为 `interrupted`，步骤编号不伪装成旧轮次的继续。

## 2. 实施前的问题（基线 4ca8233）

1. [Session.append](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/session.py:124) 只写内存；[Runtime](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/agent_runtime.py:206) 主要在轮末调用数据库保存。需要补上执行过程中的持久化位置。
2. [flush_session_events](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/persistence/base.py:31) 会吞掉保存异常。这种“尽力保存”适合原有收尾，不能作为工具执行前的持久化确认。
3. [LoopHooks](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/llm/hooks.py:15) 的约定是异常后按默认行为继续；[工具派发](D:/jk/Code/github/agent-low-code-platform/backend/tool_system/runtime/scheduler.py:296)、[轮次处理与 driver](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/loop/agent_loop.py:357) 也有通用异常捕获。检查点失败必须作为独立错误传播，不能被这些路径吞掉后继续。
4. 当前写入去重只防止重复行；`ON CONFLICT DO NOTHING` 无法阻止不同进程使用相同 `seq` 写入不同事件。需要在恢复之前取得会话写入所有权。
5. [轨迹读取](D:/jk/Code/github/agent-low-code-platform/backend/api/agents.py:590) 会将未修复的冷 Session 放进热缓存；Runtime 热命中后可能绕过冷恢复修复。需要统一写入前的会话准备流程，不能把“已经在缓存里”当成“已经适合执行”。
6. 普通聊天的 conversation/session 映射主要在回复完成后保存。首次请求中途崩溃可能留下数据库 Session，却没有完成映射。必须在第一个模型请求前保存身份关联。

## 3. 第一阶段：持久化检查点与点击继续

### 3.1 新增严格的检查点服务

建议新增 `D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/checkpoint.py`，定义异步 `SessionCheckpoint`，由 Runtime 注入 Loop 和工具调度器。

接口示意：

```python
await checkpoint.flush(reason="before_model")
await checkpoint.flush(reason="before_tool", tool_call_id=call_id)
await checkpoint.flush(reason="after_step")
await checkpoint.flush(reason="turn_end")
```

`flush` 返回只表示目标事件前缀的数据库事务已经提交。提交失败抛出结构化 `CheckpointError`，携带会话、位置和调用编号，不包含凭据。临时 Session 使用明确的非持久化模式；启用可靠检查点时必须装配真正的持久化后端，不能通过 Noop 后端报告保存成功。

每个 Session 使用一个串行 writer，记录 `durable_seq`。调用时在事件循环内截取需要保存的事件前缀，由 writer 串行提交，提交成功才推进游标。数据库阻塞 I/O 可以通过 `asyncio.to_thread` 执行，但不能将现有可变 `pending` 缓冲直接交给多个线程并发 flush。

后台标题保存、轮末保存、手动修改会话设置等所有事件写入，都经同一个 writer；恢复后以数据库最大 `seq` 重新建立游标，不用事件数量推算，因为旧 seed 事件在恢复时会被过滤。

每次只提交游标之后的新事件，保持事件日志为唯一执行事实源，不再维护一份可能与日志不同步的“完成步骤列表”。检查点名称用于诊断，恢复依据仍是已提交的事件。

### 3.2 设置检查点的位置

| 位置 | 需要确认保存的记录 | 失败后的行为 |
| --- | --- | --- |
| 会话首次执行前 | Session header、conversation/session 关联 | 不启动模型或工具，返回结构化错误。 |
| 模型请求前 | 本轮用户输入、轮次/步骤边界、请求相关状态 | 不发模型请求。 |
| 顶层工具正文前 | 完整 assistant 工具请求以及该调用的 `tool/call` | 不进入该工具正文。 |
| 步骤结束后、下一步开始前 | 已提交的模型回复、按顺序提交的工具结果、`step/end` | 不进入下一步。 |
| 轮次结束后 | `turn/end`、最终回复及必要的会话事件 | 保存确认后才发送“完成”；保存失败显示失败状态。 |
| 修复后、恢复执行前 | 合成工具结果、旧步骤结束、旧轮次中断结束 | 不发布可执行 Session，不启动续跑。 |

Loop 的改动集中在 `D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/loop/agent_loop.py`：请求构造后、真正调用模型之前等待检查点；步骤完成后保存结果；结束轮次后保存最终事件。严格检查点使用单独的接口，不能复用“异常后继续”的观察 listener 或现有重试 hook。

新增 log-only `request/header` 事件，记录本次请求的 `agent_key`、模型、非敏感调用参数、工具 schema 和渲染后的 system prompt。对话内容沿用既有事件派生，避免每一步保存整份 messages。上游任务输入若影响恢复，也应作为可序列化、经筛选的任务输入事件保存。不要记录 API key、Authorization 或连接凭据。恢复时重新使用当前配置和当前工具定义；历史快照用于解释上次请求，不用于恢复过期凭据或自动复用旧授权。

### 3.3 保留工具并发，执行正文前等待保存

在 `D:/jk/Code/github/agent-low-code-platform/backend/tool_system/runtime/scheduler.py` 增加可选的 `before_dispatch` 异步回调，仍保持“先同步记 tool/call，再创建任务”的顺序。

```python
# 示意：调用记录仍由现有 start() 写入。
async def dispatch(plan):
    await before_dispatch(plan)  # 该调用记录提交成功后才能继续。
    if canceled():
        return aborted_before_dispatch()
    return await execute_tool_body(plan)
```

回调放在现有 `_dispatch` 的通用工具异常捕获之外。`CheckpointError` 导致整批停止派发新工具；已经进入正文的工具按现有取消/排空路径收尾，结果不确定时保留未知状态。取消发生在检查点等待期间且正文未进入时，返回 `ABORTED_BEFORE_DISPATCH`，不能报告工具已经执行。

多个工具可以并发等待 writer，提交串行；工具正文仍使用现有滚动并发池和 exclusive 屏障。保留按模型顺序提交 `tool/result` 的规则。并行调用的后一个结果若还在内存 slots 等待前一个结果提交，硬崩溃后仍可能变成“结果未知”；第一阶段不承诺保留尚未进入日志的结果。

新增 `persistence_error` 停止原因。Loop 的 `_turn` 和 `_kick` 都要单独处理 `CheckpointError`，让 `when_idle()` 将失败传到 Runtime/Gateway；检查点失败期间不能因 `wake_requested` 自动开启新轮次，也不能把失败转换成正常工具错误交给模型继续跑。已发生的事件仍尽力收尾，但失败后不发送普通成功 `done`。

### 3.4 统一写入所有权和会话准备

建议新增 `D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/recovery.py`，统一新建、恢复、修复、缓存刷新和发布流程。

```text
验证租户和会话归属
→ 获取该 Session 的写入所有权
→ 从数据库确认最新事件前缀
→ 重建 Session，检查是否存在中断尾巴
→ 追加修复事件并严格提交
→ 放入执行用缓存，构造 Loop
→ 执行，排空 writer，释放所有权
```

PostgreSQL 版本建议使用基于 session_id 的 advisory lock，由专用连接持有，锁的作用域覆盖恢复、运行和最终 drain。未拿到锁返回已有的忙碌错误，不并行修复。锁连接失效时停止放行新模型/工具请求，已发出的外部操作按未知结果处理。该锁不替代外部服务的幂等机制。

`RunRegistry` 继续用于运行中投递和取消，不能替代跨进程锁。进程内占用也应在读取和修复之前建立，避免两个恢复请求先各自修复，最后才争用 Loop 登记。

后台标题与会话设置写入同样遵守会话所有权：运行中经当前 writer；空闲时短暂取得所有权，重新读取最新序号再写入。其他进程已经更新日志时，旧热缓存必须刷新。新事件序号冲突且内容不同应报错，不能继续通过 `ON CONFLICT DO NOTHING` 静默丢弃。

只读状态和轨迹读取不写修复事件，也不把未准备的对象混入执行缓存。Runtime 不论热命中还是冷恢复，取得写入所有权后都重新检查尾巴。

### 3.5 复用修复器，兼容旧日志

`D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/repair.py` 继续负责补结果、补步骤结束、补 `turn/end(interrupted)`，不执行工具。

新轮次的 `turn/start` 增加 `durability_policy: "semantic-v1"`。只有严格执行了工具前检查点的轮次，才能根据缺失 `tool/call` 判断调用未开始。历史轮次没有该标记时，缺失开始记录也可能只是没有及时落库，应使用保守的未知结果提示，不能宣称工具一定没执行。

修复成功后必须先保存，再交给模型；修复失败则停止恢复，不能沿用当前“按原样继续”的放行方式。修复保持确定性：追加序号、沿用最后真实事件时间、二次执行不重复追加。

### 3.6 增加状态查询与继续入口

建议在 `D:/jk/Code/github/agent-low-code-platform/backend/api/agents.py` 增加：

```text
GET  /api/agents/sessions/{session_id}/recovery
POST /api/agents/{agent_key}/chat/resume/stream
```

查询返回 `status`、`last_durable_seq`、`source_turn_start_seq`、`unknown_tool_calls`、`can_resume`。运行状态来自当前持有者和日志：仍有活跃所有者时不能把开放轮次判定为已崩溃。查询仅做读取，恢复写入由 POST 在持有锁后执行。

继续请求包含 `conversation_id`、`session_id`、`source_turn_start_seq`；租户来自既有请求身份。由于 session_headers 没有 tenant 字段，必须通过 conversations 或既有 workspace 会话归属验证 tenant、session 和 agent 的对应关系。

收到继续请求后恢复原任务的已保存输入及历史，关闭中断旧轮次，追加一条真实可重放的继续指令，开始新轮次。使用 log-only `turn/resume` 记录来源轮次，将其与新 `turn/start`、继续输入在首个检查点一起提交，避免只有“已受理”标记却没有可恢复的新轮次。

相同来源轮次的重复 POST 不重复投递：仍在运行就返回忙碌状态，已处理就返回对应状态。新的续跑再次中断时，以新的来源轮次标识继续。正常完成的轮次不展示恢复按钮；取消的轮次只在用户明确点击继续时恢复。

首次创建会话时，在模型请求前完成数据库 header 和 conversation/session 关联，并尽早向前端发送 `session/ready`。不能等到最终 `done` 才告诉前端 session_id。

### 3.7 给模型和用户的回复

对模型，通过已保存的工具结果和继续输入说明中断事实，不把恢复提示仅塞进本次临时 prompt。

工具未开始，新策略轮次可用：

> 上次运行在执行该工具前中断，该调用尚未进入工具执行。若原任务仍需要这个操作，可以重新调用。

工具结果未知，或历史日志缺少执行前持久化保证：

> 上次运行中断，无法确认这次调用的实际结果。查询类或已确认幂等的操作可以按需要重试；修改文件、创建订单等操作先检查当前状态，再决定是否重新执行。不要仅因为缺少结果就重复操作。

继续指令：

> 请继续上次未完成的任务，依据已有结果决定下一步。结果未知的工具先核实实际状态，不要重复已经确认完成的操作。

文件检查是模型结合工具语义作出的后续动作；框架不硬编码所有未知调用的重试。后续可增加工具的重试安全元数据，未知或缺失声明默认保守；业务工具支持幂等键时优先使用稳定的业务操作键，不能依赖新轮次随机生成的调用编号去重。

前端在 `D:/jk/Code/github/agent-low-code-platform/frontend/app/dashboard/workspace/_components/WorkspaceChat.tsx` 和 `D:/jk/Code/github/agent-low-code-platform/frontend/app/agents/[id]/page.tsx` 接入状态与继续按钮：

| 情况 | 用户可见文案 |
| --- | --- |
| 发现可恢复的中断轮次 | 上次任务中断了，已保存的进度可以继续。 |
| 已恢复，存在未知结果 | 已恢复上次进度，我会先确认中断时的操作是否完成，再继续任务。 |
| 检查点保存失败 | 进度保存失败，任务已停止。请稍后重试继续。 |
| 工具正文前取消 | 已停止，该操作尚未执行。 |

完成按钮/状态只在最终提交确认后更新。断线的取消行为第一阶段沿用现有语义：断线触发取消收尾，重连后由用户点击继续；中途落库并不意味着关闭网页后任务仍自动运行。

## 4. 用一个例子验收第一阶段

原任务：“修复登录接口的 Bug，然后跑测试。”

```text
读文件，记录读取结果
→ 模型决定修改文件
→ 提交 assistant 请求和 tool/call(c1)
→ 修改文件成功
→ 进程在保存 tool/result 之前被杀

用户重新打开会话，点击继续
→ 取得写入所有权，读取已提交日志
→ c1 有调用记录但没结果，补 TOOL_OUTCOME_UNKNOWN
→ 关闭旧轮次，严格保存修复记录
→ 新轮次收到继续指令
→ 读取当前文件或 git diff，确认修改已经存在
→ 继续跑测试，保存测试结果与最终回复
```

如果修改结果已经提交，则新轮次可以依据成功结果直接决定测试步骤；框架不强制模型无意义地重复修改。如果修改前检查点失败，修改工具正文必须从未进入。这些行为通过测试验证，不用最终回复中的一句“已恢复”代替执行证据。

## 5. 第二阶段：服务重启后自动继续

如果还需要“用户不点击，服务重启后自己接着跑”，在第一阶段基础上新增持久化任务和恢复调度。DeepSeek 上述 session resume 代码本身不提供这一层自动任务接管。

建议在 `D:/jk/Code/github/agent-low-code-platform/backend/core/schema.py` 增加 `agent_runs`：保存 run_id、租户、会话、conversation、agent、原任务引用、恢复来源、状态、重试次数、累计预算与请求幂等键。任务状态与本批事件在同一数据库事务提交；Event Log 继续提供执行事实，任务表只承担调度和查询。

后台 worker 扫描可恢复任务，在拿到同一 Session 的写入锁后重新确认状态，通过同一个恢复服务接管任务，不再实现第二份修复逻辑。用户主动取消的任务、等待人工确认的任务、预算用尽的任务不自动重启；检查点存储不可用时不循环派发工具。

自动恢复需要累计步数/工具调用/时间预算和最大恢复次数，不能每次重启都重置成无限的新任务。含未知副作用的调用仍先核实，无法确认就等待用户。SSE 改为订阅运行事件，断开订阅不取消后台任务；停止按钮改为显式取消请求。这部分连同 durable inbox 才能避免恢复后的输入再次因进程退出丢失。

第一阶段交付“检查点持久化与手动恢复”；第二阶段验收后再描述为“服务重启后的自动任务恢复”。Supervisor 的 MemorySaver 和自定义 workflow 的节点恢复是独立范围，本方案首先覆盖 AgentRuntime 工具执行循环。

## 6. 文件改动清单

| 文件 | 修改职责 |
| --- | --- |
| 新增 `D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/checkpoint.py` | 严格异步提交、串行 writer、持久化游标、结构化失败。 |
| 新增 `D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/recovery.py` | 获取所有权、最新日志恢复、修复持久化、恢复摘要。 |
| [persistence/base.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/persistence/base.py) 与 [postgres.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/persistence/postgres.py) | 严格保存接口、能力声明、锁持有、增量事务和序号冲突检查；迁移所有旧写入入口。 |
| [agent_runtime.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/agent_runtime.py) | 前移所有权获取、统一准备 Session、注入检查点、最终提交后报告完成。 |
| [agent_loop.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/loop/agent_loop.py) | 请求/步骤/轮次检查点、请求记录、检查点失败传播与恢复来源事件。 |
| [scheduler.py](D:/jk/Code/github/agent-low-code-platform/backend/tool_system/runtime/scheduler.py) | 正文前异步确认，取消与失败分类，保留并发和有序提交。 |
| [repair.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/repair.py) 与 [events.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/events.py) | 新策略标记、历史日志保守修复、新增事件和停止原因。 |
| [title/service.py](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/title/service.py) | 标题提交使用同一 writer/所有权规则，避免并发丢事件。 |
| [gateway/service.py](D:/jk/Code/github/agent-low-code-platform/backend/gateway/service.py) 与 [errors.py](D:/jk/Code/github/agent-low-code-platform/backend/gateway/errors.py) | 继续入口及结构化持久化/恢复错误，保持 Gateway 不直接执行工具。 |
| [api/agents.py](D:/jk/Code/github/agent-low-code-platform/backend/api/agents.py) | 状态/继续 API、提前绑定会话、只读查询与写入准备分离、SSE 失败和恢复提示。 |
| [WorkspaceChat.tsx](D:/jk/Code/github/agent-low-code-platform/frontend/app/dashboard/workspace/_components/WorkspaceChat.tsx) 与 [Agent 页面](D:/jk/Code/github/agent-low-code-platform/frontend/app/agents/[id]/page.tsx) | session/ready、恢复状态、继续按钮、失败状态展示。 |
| [session/session.md](D:/jk/Code/github/agent-low-code-platform/backend/agents/runtime/session/session.md) 与 [agent-loop-design.md](D:/jk/Code/github/agent-low-code-platform/docs/agent-loop-design.md) | 更新持久化时机、异常行为和恢复范围。 |

## 7. 测试与完成标准

以下是实施时新增/更新的验收，不是本次已经运行的测试。

| 验证 | 必须满足的行为 |
| --- | --- |
| 检查点未完成 | 模型和工具执行计数均为零；提交确认后才放行对应动作。 |
| 检查点失败 | 不进入对应正文、不派发后续步骤；错误经 when_idle/Gateway 到达 API，UI 不报告成功完成。 |
| 检查点期间取消 | 正文执行计数为零，结果为 ABORTED_BEFORE_DISPATCH。 |
| 工具产生副作用后硬杀 | 独立进程重启，数据库保留调用意图；修复为未知结果，文件修改次数保持一次。 |
| 结果提交后硬杀 | 重启能重建已成功的工具结果，修复不重复生成该调用结果。 |
| 模型流中途硬杀 | 保留已提交请求状态；未收敛的流式分片允许丢失，不能宣称恢复半个模型生成过程。 |
| 重复恢复与两个进程争抢 | 同一来源只产生一个续跑；另一请求收到忙碌或既有处理状态，不重复执行。 |
| 轨迹读取后再继续 | 先 GET 轨迹、再 POST 继续，仍完成正确修复；只读请求不偷偷写日志。 |
| 首次请求中断 | 模型派发前 conversation/session 关联已保存，刷新后能找到恢复入口。 |
| 标题与运行同时保存 | 新事件不因 pending 清空被丢弃，seq 不冲突，游标只在提交后推进。 |
| 旧日志兼容 | 无 semantic-v1 标记时不凭缺失开始记录宣称工具未执行；重复修复幂等。 |
| 并发调度回归 | 并发上限、exclusive 屏障、模型顺序结果提交和取消排空保持正确。 |

沿用已有 Session/repair/AgentLoop/ToolScheduler 测试替身做局部测试；持久性与跨进程所有权增加真实 PostgreSQL 集成测试。崩溃测试使用就绪信号后硬终止子进程，验证重启后的数据库和实际文件，不只测试异常抛出；Windows 需选择可用的子进程终止方式，不能直接复制 DeepSeek 在 Windows 跳过的用例。

建议分三次实施：严格 writer 与检查点；统一恢复与继续入口、前端提示；最后增加后台自动接管。每次提交按上述行为验收后，再更新简历中的能力描述。
