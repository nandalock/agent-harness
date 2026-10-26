"""Default assembly, analogous to a harness bundle rather than a tool plugin."""
from importlib.resources import files

from agent_platform_plugin_runtime import parse_yaml
from agent_platform_plugin_sdk import PluginConfiguration


def compose(config: PluginConfiguration) -> PluginConfiguration:
    """Supply absent default packages while preserving explicit overrides.

    An explicit entry (including disabled entries) replaces a default by id or
    package name. Multiple explicitly configured instances remain independent.
    PluginConfiguration validates the final instance identities.
    """
    defaults = parse_yaml(
        files(__package__).joinpath("plugins.yaml").read_text(encoding="utf-8"),
        source="agent-platform-default/plugins.yaml",
    )
    ids = {entry.id for entry in config.plugins}
    names = {entry.name for entry in config.plugins}
    missing = [
        entry for entry in defaults.plugins
        if entry.id not in ids and entry.name not in names
    ]
    # Keep the service provider first for readable diagnostics; the runtime
    # still resolves the actual dependency graph before starting any plugin.
    services = [entry for entry in missing if entry.id == "tools"]
    features = [entry for entry in missing if entry.id != "tools"]
    return PluginConfiguration(plugins=(*services, *config.plugins, *features))
