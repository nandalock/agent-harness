"""Skill discovery, loading, installation and session injection."""
from .installer import install_enabled, install_skill, installed_source, list_available
from .registry import (
    MAX_SKILL_BYTES,
    Skill,
    SkillError,
    SkillRegistry,
    SkillScope,
    SkillSource,
    get_skill_registry,
)
from .runtime import (
    SkillPreStep,
    catalog_entries,
    load_model_skill,
    render_skill,
    scope_for,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_SKILL_BYTES",
    "Skill",
    "SkillError",
    "SkillPreStep",
    "SkillRegistry",
    "SkillScope",
    "SkillSource",
    "catalog_entries",
    "get_skill_registry",
    "install_enabled",
    "install_skill",
    "installed_source",
    "list_available",
    "load_model_skill",
    "render_skill",
    "scope_for",
]
