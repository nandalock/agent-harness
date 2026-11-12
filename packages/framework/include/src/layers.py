"""Include files and apply instance patches to a composed configuration."""

from collections.abc import Iterable
from pathlib import Path

from .models import PluginConfiguration

from .config import load_yaml_config, load_yaml_patch
from .errors import ConfigurationError


def merge_layers(base: PluginConfiguration, layer: PluginConfiguration) -> PluginConfiguration:
    entries = {entry.id: entry for entry in base.plugins}
    replacements = {entry.id: entry for entry in layer.plugins}
    entries.update(replacements)
    return PluginConfiguration(
        plugins=tuple(entries.values()), groups={**base.groups, **layer.groups},
        patches=tuple(patch for patch in base.patches if patch.id not in replacements) + layer.patches,
    )


class Include:
    """Read a root YAML document and its relative includes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self, *, document: PluginConfiguration | None = None) -> PluginConfiguration:
        return self._expand(self.path, (), document)

    def read_patch(self, *, document: PluginConfiguration | None = None) -> PluginConfiguration:
        layer = document if document is not None else load_yaml_patch(self.path)
        return self.read(document=layer)

    @staticmethod
    def merge(defaults: PluginConfiguration, layers: Iterable[PluginConfiguration]) -> PluginConfiguration:
        for layer in layers:
            defaults = merge_layers(defaults, layer)
        return defaults

    def _expand(
        self, file: Path, chain: tuple[Path, ...], override: PluginConfiguration | None = None,
    ) -> PluginConfiguration:
        file = file.resolve()
        if file in chain:
            cycle = " -> ".join(map(str, (*chain, file)))
            raise ConfigurationError(f"plugin include cycle: {cycle}", source=str(file))
        current = override if override is not None else load_yaml_config(file)
        base = PluginConfiguration()
        for include in current.includes:
            base = merge_layers(base, self._expand(file.parent / include, (*chain, file)))
        return merge_layers(base, current)

def apply_entry_patches(config: PluginConfiguration) -> PluginConfiguration:
    if config.includes:
        raise ConfigurationError("plugin includes need a file path; read them with Include")
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
