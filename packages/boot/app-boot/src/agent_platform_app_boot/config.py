"""Composition discovery and default-package filling."""
from __future__ import annotations

import os
from pathlib import Path

from agent_platform_default import compose
from minidsh_cordis_plugin_include import PluginConfiguration, Include, merge_layers


def resolve_config_path() -> Path | None:
    """Explicit PLUGIN_CONFIG wins; otherwise the working directory is searched."""
    explicit = os.environ.get("PLUGIN_CONFIG")
    if explicit:
        return Path(explicit)
    for candidate in (
        Path.cwd() / "plugins.yaml",
        Path.cwd() / "config" / "plugins.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_config(document: PluginConfiguration | None = None) -> PluginConfiguration:
    path = resolve_config_path()
    config = Include(path).read(document=document) if path is not None else (document or PluginConfiguration())
    if patch := os.environ.get("MINIDSH_PLUGIN_PATCH"):
        config = merge_layers(config, Include(patch).read())
    return compose_plugins(config)


def compose_plugins(config: PluginConfiguration) -> PluginConfiguration:
    """Apply the shipped default composition; no database or domain access."""
    return compose(
        config,
        sandbox_backend=os.environ.get("SANDBOX_BACKEND", "local"),
    )
