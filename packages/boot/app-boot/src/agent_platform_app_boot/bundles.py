"""Compose the installed Web bundle layers with user configuration."""
from importlib.resources import files

from minidsh_cordis_plugin_include import PluginConfiguration, apply_entry_patches, merge_layers, parse_yaml


def read_bundle(package: str) -> PluginConfiguration:
    resource = files(package).joinpath("plugins.yaml")
    return parse_yaml(resource.read_text(encoding="utf-8"), source=f"{package}/plugins.yaml")


def compose(config: PluginConfiguration, *, sandbox_backend: str = "local") -> PluginConfiguration:
    """Supply absent default packages while preserving explicit overrides.

    An explicit entry (including disabled entries) replaces a default by id or
    package name. Multiple explicitly configured instances remain independent.
    PluginConfiguration validates the final instance identities.
    """
    defaults = merge_layers(
        read_bundle("agent_platform_bundle_base"),
        read_bundle("agent_platform_bundle_web_app"),
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
    # Keep the tool service first in the displayed configuration.
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
    base = defaults.model_copy(update={"plugins": tuple(missing)})
    explicit = config.model_copy(update={"plugins": tuple(overrides)})
    merged = merge_layers(base, explicit)
    return apply_entry_patches(merged.model_copy(update={"plugins": (*services, *overrides, *features)}))
