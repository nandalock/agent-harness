"""Introspection executed inside a profile's interpreter."""
import json
import sys
from importlib import metadata
from importlib.machinery import EXTENSION_SUFFIXES

from packaging.utils import canonicalize_name

from agent_platform_app_boot.config import load_config, resolve_config_path
from minidsh_cordis_plugin_include import PluginConfiguration, EntryOptions, Include, load_yaml_config
from minidsh_cordis_plugin_loader import Loader, load_module_plugin


def owns_export(files: set[str], target: str) -> bool:
    module = target.partition(":")[0].replace(".", "/")
    return any(
        path + suffix in files
        for path in (module, f"{module}/__init__")
        for suffix in (".py", *EXTENSION_SUFFIXES)
    )


def main():
    action = sys.argv[1]
    if action == "inventory":
        result = [
            {
                "distribution": canonicalize_name(dist.metadata["Name"]),
                "version": dist.version,
                "requires": dist.requires or [],
            }
            for dist in metadata.distributions()
        ]
    elif action == "config":
        result = load_config().model_dump(mode="json")
    elif action == "validate":
        config = load_config(PluginConfiguration.model_validate_json(sys.stdin.read()))
        Loader(config).validate()
        return
    elif action in ("describe", "owned"):
        distribution = metadata.distribution(sys.argv[2])
        files = {path.as_posix() for path in distribution.files or ()}
        if action == "describe":
            target = sys.argv[3]
            if not owns_export(files, target):
                raise ValueError(f"{target!r} is outside {distribution.metadata['Name']}")
            plugin = load_module_plugin(target)
            entry = EntryOptions(id=plugin.name, name=plugin.name, use=target)
            result = entry.model_dump(mode="json")
        else:
            def owned(config: PluginConfiguration) -> list[str]:
                return [entry.id for entry in config.plugins
                        if entry.use is not None and owns_export(files, entry.use)]

            path = resolve_config_path()
            included = []
            if path is not None:
                document = load_yaml_config(path).model_copy(update={"plugins": (), "patches": ()})
                included = owned(Include(path).read(document=document))
            result = {"configured": owned(load_config()), "included": included}
    else:
        raise ValueError(f"Unknown profile operation: {action}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
