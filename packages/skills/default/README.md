# skills-default

Service-only plugin providing `skills.v1`. Each Loader receives a fresh
registry. It has no dependency on tools, agents or filesystem discovery.

Providers register through `ctx.require(SKILLS).register_provider(provider)` and
track the returned registration in their context. The registry merges skill
catalogs, respects the agent whitelist and rejects duplicate qualified keys or
ambiguous unqualified names. Shutdown clears and closes the registry.

`pyproject.toml` maps `agent_platform_skills_default` directly to `src/`.
