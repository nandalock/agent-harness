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

Sources can declare `package_key` and `package_name` to identify one downloaded
bundle across its skill and command directories. Bundled Overleaf has one entry,
`src/builtin/overleaf_rt/skills/overleaf/SKILL.md`, selected with
`@package/overleaf-rt`. Its six `references/*.md` files are resources, never
independently discovered skills. Legacy Overleaf names resolve to this entry.
Sources without package metadata retain separate
selectors for each skill, including unrelated installations in the same directory.

`list()` reads frontmatter only and returns summaries without instructions.
`get()` reads the chosen entry body. Reference files are opened only through an
explicit `skill(name="overleaf", resource="references/comments.md")` request.
