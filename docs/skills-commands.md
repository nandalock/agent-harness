# 技能与斜杠命令

平台采用技能目录、按需加载工具和执行前注入机制。工作区输入 `/` 可查看当前智能体的技能与命令；选择条目后填写参数并发送。运行中的输入也会在下一步经过同一处理。

## 调用方式

- 用户调用：消息开头的 `/技能名 参数` 会加载完整指令，`$ARGUMENTS` 替换为名称后面的文本。未知名称仍作为普通消息发送。参数只用于文本展开，不会被平台作为 shell 求值。
- 模型调用：可调用的技能摘要进入会话目录，模型用 `skill` 工具加载正文；附属文本用 `skill(name=技能名, resource=相对路径)` 读取。
- Markdown 命令默认只允许用户显式调用；技能默认允许用户和模型调用。`user-invocable: false` 隐藏用户入口，`disable-model-invocation: true` 禁止模型加载。
- 所需工具未绑定时，菜单显示缺少的工具，模型目录省略该条目。加载指令不会改变工具绑定或沙箱权限。

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
---
检查 $ARGUMENTS，先阅读 references/style.md，再提出修改建议。
```

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

内置四个上游技能和 `/overleaf-login`、`/overleaf-status` 两个命令，来自 `overleaf-mcp-rt` 2.2.0。原文、来源和许可证保留在 `packages/skills/builtin/overleaf_rt/`。

新后端镜像安装固定版本的 Node.js 服务。Compose 默认启用 `OVERLEAF_RT_ENABLED=true`，启动时独立登记 `overleaf-rt`；不覆盖已有 MCP 服务配置和智能体工具绑定。

1. 按 `.env.overleaf-rt.example` 配置 `OVERLEAF_RT_URL` 与 `OVERLEAF_RT_SESSION_COOKIE`。
2. 执行 `docker compose build backend` 和 `docker compose up -d backend`。
3. 在 MCP 页面确认 `overleaf-rt` 的工具可用。在智能体配置页绑定需要的工具；状态和登录命令至少需要 `overleaf_list_hosts`、`overleaf_list_projects`。
4. 在工作区发送 `/overleaf-status`，或 `/overleaf-login https://www.overleaf.com overleaf`。

登录命令会指导用户在自己的电脑运行浏览器登录，平台不会在后端容器中代替用户登录。宿主机 CLI 的凭据文件不会自动出现在容器中；容器可通过 `OVERLEAF_RT_SESSION_COOKIE` 使用登录后的会话。不要在聊天消息中提交 Cookie。

实时 MCP 的 stdio 进程按租户、会话和服务配置隔离复用，保证先读后改的服务内状态可用。默认闲置 1800 秒后关闭，可通过 `MCP_SESSION_IDLE_SECONDS` 调整；关闭、超时或取消后不自动重试写操作。连接重建后应重新读取文档再修改。

## 会话记录

用户原消息保持原样。目录与展开后的指令作为带来源元数据的 `user/message` 写入 Session，在模型调用前使用现有检查点落盘。技能指令记录名称、参数、内容摘要值和对应用户消息序号。

恢复会话时保留当时展开的正文；修改技能文件仅影响后续加载。前端根据来源元数据显示简短的“已加载技能”行，不把完整指令展示为用户聊天气泡。运行中系统注入和工具输出不触发命令。

## 验证

```bash
docker compose exec -T backend python -m unittest backend.skills.test_skills backend.skills.test_installer -v
```

前端交互测试：在 `frontend/` 运行 `npm run test:skills`。本机未安装 Playwright Chromium 时可设置 `PLAYWRIGHT_CHANNEL=msedge` 使用已安装的 Edge。
