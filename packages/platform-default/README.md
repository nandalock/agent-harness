# Default composition

`plugins.yaml` is the default application assembly. Backend loads this package,
adds host configuration such as database MCP servers, and starts PluginRuntime.
It does not enumerate individual tools.

A plugin package is a lifecycle and assembly unit. Each configured instance may
publish services, register zero or many tools, and own cleanup effects:

| Package entry | Services | Tools per instance |
| --- | --- | --- |
| tools-default | tools.v1, tools.catalog.v1 | 0 of its own; hosts registrations |
| mcp-manager | mcp.manager.v1 | 0 at setup; manages dynamic server tool groups |
| mcp-client | MCP connection lifecycle | 0–N discovered server tools |
| skill-tools | consumes tools.v1 and agents.v1 | skill, skill_install |
| sandbox-tools | consumes tools.v1 and settings.v1 | bash, python when enabled |

Library packages such as skills, sandbox, and tool-system provide reusable
implementations. A package is discoverable as a plugin only when it exports a
plugin entry point. This composition package is a preset, not a runtime plugin.

`compose(user_config)` fills absent defaults. Override by package name or default
instance id. Explicit `disabled: true` is respected, including for tools-default;
disabling a required service without a replacement fails dependency validation.
Multiple explicit mcp-client instances each own their server's whole tool group.
