"""Introspection executed inside a profile's interpreter."""
import json
import sys
from importlib import metadata

from packaging.utils import canonicalize_name

from agent_platform_app_boot.config import compose_plugins, load_config
from agent_platform_plugin_runtime.catalog import EntryPointCatalog
from agent_platform_plugin_runtime.dependencies import resolve
from agent_platform_plugin_runtime.loader import load_plugins
from agent_platform_plugin_sdk import PLUGIN_CATALOG, PLUGIN_ENTRY_POINT_GROUP, PluginConfiguration


def main():
    action = sys.argv[1]
    if action == "inventory":
        result = [
            {
                "distribution": canonicalize_name(dist.metadata["Name"]),
                "version": dist.version,
                "entries": [ep.name for ep in dist.entry_points if ep.group == PLUGIN_ENTRY_POINT_GROUP],
                "requires": dist.requires or [],
            }
            for dist in metadata.distributions()
        ]
    elif action == "config":
        result = load_config().model_dump(mode="json")
    elif action == "validate":
        config = compose_plugins(PluginConfiguration.model_validate_json(sys.stdin.read()))
        resolve(load_plugins(config, EntryPointCatalog()), {PLUGIN_CATALOG: None})
        return
    else:
        raise ValueError(f"Unknown profile operation: {action}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
