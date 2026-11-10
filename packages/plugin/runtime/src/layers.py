"""Include files and apply instance patches to a composed configuration."""

from pathlib import Path

from .models import PluginConfiguration

from .config import load_yaml_config
from .errors import ConfigurationError


def merge_layers(base: PluginConfiguration, layer: PluginConfiguration) -> PluginConfiguration:
    entries = {entry.id: entry for entry in base.plugins}
    replacements = {entry.id: entry for entry in layer.plugins}
    entries.update(replacements)
    return PluginConfiguration(
        plugins=tuple(entries.values()), groups={**base.groups, **layer.groups},
        patches=tuple(patch for patch in base.patches if patch.id not in replacements) + layer.patches,
    )


def load_layers(path: str | Path, *, document: PluginConfiguration | None = None) -> PluginConfiguration:
    def expand(file: Path, chain: tuple[Path, ...], override: PluginConfiguration | None = None) -> PluginConfiguration:
        file = file.resolve()
        if file in chain:
            cycle = " -> ".join(map(str, (*chain, file)))
            raise ConfigurationError(f"plugin include cycle: {cycle}", source=str(file))
        current = override if override is not None else load_yaml_config(file)
        base = PluginConfiguration()
        for include in current.includes:
            base = merge_layers(base, expand(file.parent / include, (*chain, file)))
        return merge_layers(base, current)

    return expand(Path(path), (), document)


def apply_patches(config: PluginConfiguration) -> PluginConfiguration:
    if config.includes:
        raise ConfigurationError("plugin includes need a file path; load them with load_layers()")
    entries = {entry.id: entry for entry in config.plugins}
    for patch in config.patches:
        entry = entries.get(patch.id)
        if entry is None:
            raise ConfigurationError(f"plugin patch targets unknown instance {patch.id!r}")
        entries[patch.id] = entry.model_copy(update={
            "disabled": entry.disabled if patch.disabled is None else patch.disabled,
            "config": {**entry.config, **patch.config},
        })
    return PluginConfiguration(plugins=tuple(entries.values()), groups=config.groups)
