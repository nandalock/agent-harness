# skills-filesystem

Contributes local skills to `skills.v1`; does not register tools or agent hooks.
Sources are bundled skills (`src/builtin`), configured local directories and
tenant/agent-scoped installations. Files are re-read on lookup, so installation
and edits appear without restarting. This is lookup-based discovery, not a watcher.

```yaml
plugins:
  - id: skills-filesystem
    name: agent-platform.skills-filesystem
    config:
      builtin: true
      include_installed: true
      sources:
        - name: local
          path: /absolute/path/to/skills
          tenant_ids: [1]
          agent_keys: [assistant]
```

Custom sources require an absolute path and tenant ownership. `agent_keys` is
optional. Existing `SKILL_PACKAGES_ROOT`, `SKILL_SOURCES`, `SKILL_INSTALL_ROOT`
environment configuration remains supported. Local minidsh deployment defaults
installations to `~/.minidsh/skills/<tenant>/<agent-hash>`.

Disable with `disabled: true` to unregister the whole provider. Other provider
plugins can still contribute to `skills.v1`. Disabling `skills-default` requires
a replacement service or disabling both its consumers as well.

`pyproject.toml` maps `agent_platform_skills_filesystem` directly to `src/` and
includes bundled Markdown, notices and licenses in wheels.
