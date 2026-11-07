"""Composition discovery and default-package filling."""
from __future__ import annotations

import os
from pathlib import Path

from agent_platform_default import compose
from agent_platform_plugin_runtime import load_yaml_config
from agent_platform_plugin_sdk import PluginConfiguration


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


def load_config() -> PluginConfiguration:
    path = resolve_config_path()
    config = load_yaml_config(path) if path is not None else PluginConfiguration()
    return compose_plugins(config)


def compose_plugins(config: PluginConfiguration) -> PluginConfiguration:
    """Apply the shipped default composition; no database or domain access."""
    return compose(
        config,
        sandbox_backend=os.environ.get("SANDBOX_BACKEND", "local"),
    )
