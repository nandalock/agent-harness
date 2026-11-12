"""Composition discovery and default-package filling."""
from __future__ import annotations

import os
from pathlib import Path

from agent_platform_default import compose
from minidsh_cordis_plugin_include import Include, PluginConfiguration


def resolve_config_path() -> Path | None:
    """Use the launcher's root, with a fallback for older profile directories."""
    explicit = os.environ.get("PLUGIN_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if configured := os.environ.get("MINIDSH_PROFILE_CONFIG"):
        root = Path(configured)
        if root.exists():
            return root
        legacy = root.with_name("plugins.yaml")
        if legacy.exists():
            return legacy
    return None


def load_config(
    document: PluginConfiguration | None = None, *,
    patch_document: PluginConfiguration | None = None,
) -> PluginConfiguration:
    path = resolve_config_path()
    if path is None and document is not None and (root := os.environ.get("MINIDSH_PROFILE_CONFIG")):
        path = Path(root)
    config = Include(path).read(document=document) if path is not None else (document or PluginConfiguration())
    layers = []
    if configured := os.environ.get("MINIDSH_PROFILE_PATCH"):
        profile_patch = Path(configured)
        if patch_document is not None or profile_patch.exists():
            layers.append(Include(profile_patch).read_patch(document=patch_document))
    if patch := os.environ.get("MINIDSH_PLUGIN_PATCH"):
        layers.append(Include(patch).read_patch())
    return compose_plugins(Include.merge(config, layers))


def compose_plugins(config: PluginConfiguration) -> PluginConfiguration:
    """Apply the shipped default composition; no database or domain access."""
    return compose(
        config,
        sandbox_backend=os.environ.get("SANDBOX_BACKEND", "local"),
    )
