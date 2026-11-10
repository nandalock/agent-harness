"""Default assembly, analogous to a harness bundle rather than a tool plugin."""
from importlib.resources import files

from agent_platform_plugin_runtime import apply_patches, parse_yaml
from agent_platform_plugin_runtime import PluginConfiguration


def compose(config: PluginConfiguration, *, sandbox_backend: str = "local") -> PluginConfiguration:
    """Supply absent default packages while preserving explicit overrides.

    An explicit entry (including disabled entries) replaces a default by id or
    package name. Multiple explicitly configured instances remain independent.
    PluginConfiguration validates the final instance identities.
    """
    defaults = parse_yaml(
        files(__package__).joinpath("plugins.yaml").read_text(encoding="utf-8"),
        source="agent-platform-default/plugins.yaml",
    )
    if sandbox_backend not in ("local", "docker"):
        raise ValueError("SANDBOX_BACKEND must be local or docker")
    defaults = defaults.model_copy(update={"plugins": tuple(
        entry.model_copy(update={
            "name": f"agent-platform.sandbox-{sandbox_backend}",
            "use": f"agent_platform_sandbox.plugin:{sandbox_backend.capitalize()}SandboxPlugin",
        })
        if entry.id == "sandbox-provider" else entry for entry in defaults.plugins
    )})
    ids = {entry.id for entry in config.plugins}
    names = {entry.name for entry in config.plugins}
    has_sandbox = bool(names & {"agent-platform.sandbox-local", "agent-platform.sandbox-docker"})
    missing = [
        entry for entry in defaults.plugins
        if entry.id not in ids and entry.name not in names
        and not (entry.id == "sandbox-provider" and has_sandbox)
    ]
    # Keep the service provider first for readable diagnostics; the runtime
    # still resolves the actual dependency graph before starting any plugin.
    services = [entry for entry in missing if entry.id == "tools"]
    features = [entry for entry in missing if entry.id != "tools"]
    default_by_id = {entry.id: entry for entry in defaults.plugins}
    default_by_name = {entry.name: entry for entry in defaults.plugins}
    # The Docker and local variants can also be explicitly selected by name.
    sandbox = default_by_id["sandbox-provider"]
    other = "docker" if sandbox_backend == "local" else "local"
    other_name = f"agent-platform.sandbox-{other}"
    default_by_name[other_name] = sandbox.model_copy(update={
        "name": other_name, "use": f"agent_platform_sandbox.plugin:{other.capitalize()}SandboxPlugin",
    })
    # The client is bundled, and individual servers are opt-in.
    extra_exports = {"agent-platform.mcp-client": "agent_platform_mcp_client:McpClientPlugin"}
    overrides = []
    for entry in config.plugins:
        original = default_by_name.get(entry.name)
        if original is not None:
            entry = entry.model_copy(update={
                "use": entry.use or original.use,
                "group": entry.group or (original.group if entry.id == original.id else None),
            })
        elif entry.use is None and entry.name in extra_exports:
            entry = entry.model_copy(update={"use": extra_exports[entry.name]})
        overrides.append(entry)
    return apply_patches(PluginConfiguration(
        plugins=(*services, *overrides, *features), groups={**defaults.groups, **config.groups},
        patches=(*defaults.patches, *config.patches),
    ))
