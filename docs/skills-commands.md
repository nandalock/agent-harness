# 技能与斜杠命令

平台采用技能目录、按需加载工具和执行前注入机制。工作区输入 `/` 可查看当前智能体的技能与命令；选择条目后填写参数并发送。运行中的输入也会在下一步经过同一处理。

## 调用方式

智能体配置页 `/agents/<agent_key>` 的“技能绑定”可控制当前 Agent 的技能开关和白名单，
修改后点击“保存配置”：

- “全部技能包（含新增）”保存为 `enabled_skills: null`，允许当前作用域可见的全部技能包。
- “指定技能包”按包标识保存，例如 `enabled_skills: ["@package/overleaf-rt"]`，一次启用包内全部技能与命令，也包含该包后续新增的内容。独立安装的单个技能仍使用自己的完整标识；清空选择保存为 `[]`。
- 取消“启用技能”保存为 `skills_enabled: false`，保留原选择以便恢复。
- `overleaf` 只有一个 `SKILL.md` 入口和一个绑定复选框；评论、编辑、编译等是 `references/` 中的参考资料，不是独立技能或命令。保存选择后，技能插件自动关联入口声明的工具，无需再手动勾选工具。
- 工具面板标出“技能自动绑定”，取消技能后自动解除；用户手动绑定的工具和其他技能仍需要的工具会保留。自动关联按当前租户、智能体和所选技能动态计算，不写入手动绑定表。
- 未启动或连接失败的工具不会出现在模型工具列表，工具面板列出尚未加载的自动关联工具。
- 来源暂不可用的已选技能保留在配置中，可手动取消。
- 旧的 Overleaf 子项名称作为兼容别名指向统一入口；其他技能包的部分选择仍保持原有范围。读取配置不写回数据库。

配置页读取 `GET /api/agents/{agent_key}/skills/catalog`，因此白名单为空或技能停用时
仍能重新选择。该接口只放宽当前 Agent 的目录筛选，保留租户和来源归属限制，只返回
摘要；聊天继续使用 `/skills` 接口，工具执行仍检查已保存的开关与白名单。

- 用户调用：消息开头的 `/技能名 参数` 会加载完整指令，`$ARGUMENTS` 替换为名称后面的文本。未知名称仍作为普通消息发送。参数只用于文本展开，不会被平台作为 shell 求值。
- 模型调用：可调用的技能摘要进入会话目录，模型用 `skill` 工具加载正文；附属文本用 `skill(name=技能名, resource=相对路径)` 读取。
- Markdown 命令默认只允许用户显式调用；技能默认允许用户和模型调用。`user-invocable: false` 隐藏用户入口，`disable-model-invocation: true` 禁止模型加载。
- 所需工具未加载时，菜单和模型目录都保留已启用技能并标明不可用原因。模型可以解释“有这个技能，但依赖尚未就绪”，不会把未就绪误报为未安装；正文加载和执行仍会拒绝。工具就绪后目录状态自动更新。自动绑定不改变沙箱模式或工具插件的部署状态。

## 渐进式披露

1. 文件系统来源扫描各入口的 YAML 元数据，返回 `SkillSummary`，不读取正文或参考资料。模型初始只看到已启用技能的名称、描述和状态。
2. 模型选择 `skill(name="overleaf")`，或用户发送 `/overleaf 任务`，才读取唯一入口 `overleaf/SKILL.md`。入口包含任务路由表，不包含六份完整说明。
3. 涉及评论时调用 `skill(name="overleaf", resource="references/comments.md")`，只读取该参考文件；编辑、编译等资料在对应任务需要时另行读取。

模型目录使用 `<system-reminder>` / `<available_skills>` 包装名称和描述列表，
任务匹配时要求先加载完整指令；只有未就绪或调用受限的条目附简短状态说明。
首次介绍目录，发生变化时发送替换目录，空目录会明确清除旧名称。旧会话中的 JSON 目录会在下一步更新一次。

目录接口与会话来源元数据中的 `available` 表示入口满足最低依赖、可以读取；`tools_ready` 表示全部声明工具已就绪。
Overleaf 的 `required-tools` 为空，因此未连接时仍可读取设置和登录指南；其业务工具通过 `tools` 声明并自动关联，实际操作仍需等待对应工具加载。
参考资料不能独立绑定，资源路径不得越出该技能目录。

## 技能文件

支持 `<目录>/<名称>/SKILL.md` 和 `<目录>/<名称>.md`。YAML 元数据示例：

```yaml
---
name: review-notes
description: 按项目约定检查笔记并提出修改建议
user-invocable: true
disable-model-invocation: false
argument-hint: "[检查范围]"
required-tools: [read_file]
tools: [write_file]
---
检查 $ARGUMENTS，先阅读 references/style.md，再提出修改建议。
```

`required-tools` 声明该技能可用的最低工具依赖；`tools` 可声明额外执行工具。
选择技能后两者都会自动关联，只有已经在插件注册表中就绪的工具会进入模型请求。
平台不会从技能正文里猜测或提取工具权限。

自定义来源在后端环境变量 `SKILL_SOURCES` 中配置，使用 JSON 数组。路径为后端可读取的绝对路径，目录需挂载进后端容器；每个自定义来源必须声明租户归属。

```json
[
  {
    "name": "team",
    "path": "/opt/team-skills",
    "kind": "skill",
    "tenant_ids": [1],
    "agent_keys": ["assistant"]
  }
]
```

`kind` 可选 `skill` 或 `command`。来源内名称必须唯一；不同来源重名时用 `/来源名:技能名` 调用。默认来源仅包含仓库中的 Overleaf 公开指令，不会扫描服务器用户的个人技能目录。

多份指令属于同一下载包时，可在来源配置中声明相同的 `package_key` 与 `package_name`，
例如 `"package_key": "overleaf-rt", "package_name": "overleaf"`；技能目录与命令目录可以共享这两个字段。
YAML 的 `skills-filesystem.config.sources` 同样支持这两个字段。未声明包归属的条目独立绑定，
不会仅因为同在 `installed` 或某个扫描目录下就被合并。

智能体配置支持 `skills_enabled: false` 停用技能，以及 `enabled_skills: ["来源名:技能名"]` 限定目录；空列表停用全部技能，省略时允许所有符合来源范围和工具依赖的技能。

## 在聊天中安装外部技能

内置 `/skill-installer` 提供聊天安装入口，也支持消息开头的 `$skill-installer`。智能体可通过技能目录发现安装能力；无需预先在工具页绑定安装工具。

```text
/skill-installer
/skill-installer gh-fix-ci
$skill-installer https://github.com/anthropics/skills/tree/main/skills/pdf
```

不带参数时，安装器用 `skill_install(action="list")` 列出 `openai/skills` 仓库 `skills/.curated` 中的技能；名称安装也使用该推荐目录。GitHub 安装支持公开仓库的技能目录（`tree`）或 `SKILL.md` 文件（`blob`）地址。仓库根本身是技能时可以传仓库地址；集合仓库应提供具体子目录。分支名含 `/` 时，工具需额外提供与地址一致的 `ref`。当前不支持私有仓库、任意下载 URL 或插件市场安装。

安装先解析提交号，再下载该提交的 ZIP，只提取指定技能子目录，校验 `SKILL.md` 后原子发布。完整保留脚本、参考资料、二进制资源，并记录仓库、路径、版本和提交号。安装不执行任何包内代码、不自动安装依赖或连接 MCP；脚本也不会因安装而自动挂载到执行沙箱。

技能归属固定为执行上下文中的租户和智能体，调用参数不能指定归属或磁盘位置。安装源标识为 `installed`，例如 `/installed:pdf`。已安装同名技能会返回错误并保留原包。安装工具走既有工具调度与 Session 日志，使用独占执行模式；模型下一步可发现新技能，前端重新打开 `/` 菜单也会读取最新目录，无需重启后端。

安装包默认保存在项目 `.data/skills/`，可以由部署者设置 `SKILL_INSTALL_ROOT`。Compose 使用 `skill_data` 持久卷，挂载到 `/var/lib/agent/skills`；首次启用需执行 `docker compose up -d --no-deps --force-recreate backend` 更新容器配置，后续安装不需要重启。

智能体配置 `skill_install_enabled: false` 关闭聊天安装；`skills_enabled: false` 或不包含 `skill-installer` / `platform:skill-installer` 的 `enabled_skills` 白名单也会关闭入口。安装不会绕过现有白名单；安装结果的 `visible` 和 `unavailable_reason` 分别说明可见性与工具依赖。`platform`、`installed` 为保留来源名。

下载压缩包最多 32 MiB，仓库最多 20,000 个 ZIP 条目，所选技能包解压最多 64 MiB / 2,048 个文件。路径穿越、符号链接、特殊文件和大小写冲突文件会拒绝安装；下载和整体安装分别有超时限制。

## Overleaf 实时服务

内置一个 `overleaf` 技能，入口在 `packages/skills/filesystem/src/builtin/overleaf_rt/skills/overleaf/SKILL.md`。
六份参考资料由 `overleaf-mcp-rt` 2.2.0 的技能和命令改编，来源和许可证保留在 `overleaf_rt/`。

新后端镜像安装固定版本的 Node.js 服务。Compose 默认启用 `OVERLEAF_RT_ENABLED=true`，启动时独立登记 `overleaf-rt`；不覆盖已有 MCP 服务配置和智能体工具绑定。

1. 按 `config/docker.env.example` 配置 `OVERLEAF_RT_URL` 与 `OVERLEAF_RT_SESSION_COOKIE`。
2. 执行 `docker compose build backend` 和 `docker compose --env-file config/docker.env up -d backend`。
3. 在 MCP 页面确认 `overleaf-rt` 的工具可用。在智能体配置页启用 `overleaf`，工具会自动关联。
4. 在工作区发送 `/overleaf 检查连接状态`，或 `/overleaf 登录 https://www.overleaf.com`。

登录命令会指导用户在自己的电脑运行浏览器登录，平台不会在后端容器中代替用户登录。宿主机 CLI 的凭据文件不会自动出现在容器中；容器可通过 `OVERLEAF_RT_SESSION_COOKIE` 使用登录后的会话。不要在聊天消息中提交 Cookie。

实时 MCP 的 stdio 进程按租户、会话和服务配置隔离复用，保证先读后改的服务内状态可用。默认闲置 1800 秒后关闭，可通过 `MCP_SESSION_IDLE_SECONDS` 调整；关闭、超时或取消后不自动重试写操作。连接重建后应重新读取文档再修改。

## 会话记录

用户原消息保持原样。目录与展开后的指令作为带来源元数据的 `user/message` 写入 Session，在模型调用前使用现有检查点落盘。技能指令记录名称、参数、内容摘要值和对应用户消息序号。

恢复会话时保留当时展开的正文；修改技能文件仅影响后续加载。前端根据来源元数据显示简短的“已加载技能”行，不把完整指令展示为用户聊天气泡。运行中系统注入和工具输出不触发命令。

## 验证

```bash
docker compose exec -T backend python -m pytest tests/integration/skills/test_skills.py tests/integration/skills/test_installer.py -q
```

前端交互测试位于 `packages/client/tests/skill-bindings.spec.ts`；元数据与按需读取回归测试位于 `packages/skills/tests/test_progressive.py`。

## 插件装配

技能系统由三个插件组成：`agent-platform.skills-default` 提供 `skills.v1`，
`agent-platform.skills-filesystem` 登记本地目录，`agent-platform.skill-tools`
注册工具和对话扩展。内置内容属于文件系统插件。源码结构见
[packages/skills](../packages/skills/README.md)。

AgentRuntime 通过通用的 `agent.extensions.v1` 接收工具和 pre-step 钩子，不再
直接导入技能实现。禁用 skill-tools 会一并移除工具、目录注入和 `/技能名` 处理。
保留 `skills_enabled`、`enabled_skills`、`skill_install_enabled` 的 Agent 配置语义。
