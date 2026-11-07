# Agent Platform Skills

技能服务契约与共享库。发行包名为 `agent-platform-skills`，导入名为 `agent_platform_skills`。

这个包不导入 `backend`：

- `registry.py`：`SKILLS` / `skills.v1`、provider 接口及按运行时隔离的注册中心；
- `document.py`：共享的技能文档校验，供目录扫描和安装暂存校验使用；
- `runtime.py`：作用域、渲染、目录视图和受控资源读取；
- `installer.py`：从公开 GitHub 仓库安装技能包（不执行其中的代码）；

本库不自动扫描目录，也不持有进程级技能单例。`skills-default` 插件创建服务，
`skills-filesystem` 贡献来源和内置内容，`skill-tools` 提供工具和对话扩展。

`provider.list(scope)` 只返回 `SkillSummary`（没有 `content` / `content_hash`）；
`provider.get(summary, scope)` 才读取完整 `Skill`。注册中心保留 provider 归属，
按名称解析入口后委托对应 provider 加载。文件目录扫描只解析 YAML 头部，
`load(name, scope, resource)` 只读取该技能目录内明确指定的附属文本。

工具入口由独立插件包 `agent-platform-skill-tools` 提供：

- 工具插件通过 `ctx.require(SKILLS)` 获取服务；
- AgentRuntime 只调用通用 `agent.extensions.v1`，不导入本库或技能工具插件。

源码直接放在 `src/`；`pyproject.toml` 的 `package-dir` 把 Python 导入名映射到它。

技能目录摘要包含 `package_key`、`package_name`、`binding_key`，供配置页按下载包绑定。
`enabled_skills` 支持 `@package/<package_key>` 选择整包，同时继续接受旧的技能全名或短名。
来源范围、工具依赖和用户/模型调用限制仍逐项检查；包选择不会合并技能正文。
`required-tools` 与 `tools` 声明的工具由 skill-tools 自动关联，取消选择后撤销自动关联。
这不修改用户的手动工具绑定，也不启动关闭的工具插件或改变沙箱模式。
