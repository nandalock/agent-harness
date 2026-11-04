# agent-platform.skill-tools

Publishes the `skill` and `skill_install` tools into `tools.v1`.

It requires `skills.v1`, `tools.v1`, `agents.v1` (effective agent config), and
`agent.extensions.v1`. Skill execution calls the injected skills service; no
directory discovery or process-level skill registry is created here.

The plugin also registers an agent extension for tool exposure, the model-facing
catalog, and explicit `/name` invocation. Disabling the plugin removes these
hooks and its tools together. Installation remains available when permitted by
the agent configuration; newly installed files are discovered by the filesystem
provider on the next lookup. There is no backend import.

Sources live directly in `src/`. `pyproject.toml` maps the existing Python import
name `agent_platform_skill_tools` to this directory, for editable and wheel installs.
