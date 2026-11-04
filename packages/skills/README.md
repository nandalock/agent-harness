# Skill plugins

Three independently owned runtime plugins:

| Package | Entry point | Responsibility |
| --- | --- | --- |
| `default` | `agent-platform.skills-default` | Provides `skills.v1` |
| `filesystem` | `agent-platform.skills-filesystem` | Registers local, bundled and installed sources |
| `tools` | `agent-platform.skill-tools` | Registers `skill`, `skill_install` and agent conversation extensions |

`core` is a shared library, not a fourth plugin. It contains contracts,
scope/document validation and installation helpers. Each package maps its Python
import name to `src/` using `pyproject.toml`; no repeated module directory is needed.

The default composition enables all three. Configure sources or disable consumers
in `config/plugins.yaml`; see `filesystem/README.md` and `config/plugins.yaml.example`.

```text
filesystem → skills.v1 ← skill-tools → tools.v1 + agent.extensions.v1
```

AgentRuntime executes generic plugin contributions and does not import skill
implementations. Registrations, tools, providers and hooks are removed through
plugin context disposal. Skills do not grant permissions to their referenced tools.
