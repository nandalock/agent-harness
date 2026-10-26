# Agent Platform Skills

技能与 Markdown 命令的发现、加载、安装和会话注入。发行包名为 `agent-platform-skills`，导入名为 `agent_platform_skills`。

这个包不导入 `backend`：

- `registry.py`：从内置/自定义目录发现技能，解析 YAML front matter；
- `runtime.py`：渲染技能正文、生成目录、`SkillPreStep` 会话注入；
- `installer.py`：从公开 GitHub 仓库安装技能包（不执行其中的代码）；
- `builtin/`：平台内置技能与命令（`platform`、`overleaf_rt`）。

内置数据默认从包目录加载；可用 `SKILL_PACKAGES_ROOT` 指向其他目录，用 `SKILL_SOURCES` 追加自定义来源，用 `SKILL_INSTALL_ROOT` 指定安装目录。

工具入口由独立插件包 `agent-platform-skill-tools` 提供：

- `agent_platform_skill_tools` 通过 `agents.v1` 读取生效配置，把 `skill` /
  `skill_install` 注册进 `tools.v1`；
- backend 只保留宿主适配：`backend/agents/runtime/agent_runtime.py` 在会话注入
  路径上构造 `SkillScope`，`backend/host_services.py` 实现 `agents.v1`。
