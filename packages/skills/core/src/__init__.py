"""Public skill contracts and shared document/installation helpers."""
from .registry import (
    SKILLS, MAX_SKILL_BYTES, Skill, SkillSummary, SkillError, SkillProvider,
    SkillRegistry, SkillScope, SkillSource, SkillsService,
)
from .runtime import catalog_entries, load_model_skill, render_skill, scope_for

__version__ = "0.1.0"
__all__ = [
    "SKILLS", "MAX_SKILL_BYTES", "Skill", "SkillSummary", "SkillError", "SkillProvider",
    "SkillRegistry", "SkillScope", "SkillSource", "SkillsService",
    "catalog_entries", "load_model_skill", "render_skill", "scope_for",
]
