# Agent Platform Skills

技能服务契约与共享库。发行包名为 `agent-platform-skills`，导入名为 `agent_platform_skills`。

这个包不导入 `backend`：

- `registry.py`：`SKILLS` / `skills.v1`、provider 接口及按运行时隔离的注册中心；
- `document.py`：共享的技能文档校验，供目录扫描和安装暂存校验使用；
- `runtime.py`：作用域、渲染、目录视图和受控资源读取；
- `installer.py`：从公开 GitHub 仓库安装技能包（不执行其中的代码）；

本库不自动扫描目录，也不持有进程级技能单例。`skills-default` 插件创建服务，
`skills-filesystem` 贡献来源和内置内容，`skill-tools` 提供工具和对话扩展。

工具入口由独立插件包 `agent-platform-skill-tools` 提供：

- 工具插件通过 `ctx.require(SKILLS)` 获取服务；
- AgentRuntime 只调用通用 `agent.extensions.v1`，不导入本库或技能工具插件。

源码直接放在 `src/`；`pyproject.toml` 的 `package-dir` 把 Python 导入名映射到它。
