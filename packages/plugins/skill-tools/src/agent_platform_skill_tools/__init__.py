"""Skill loading and installation as a tools.v1 plugin."""
from .descriptors import (
    openai_tool,
    skill_descriptor,
    skill_install_descriptor,
)
from .executors import SkillExecutor, SkillInstallExecutor
from .plugin import SkillToolsPlugin

__all__ = [
    "SkillExecutor",
    "SkillInstallExecutor",
    "SkillToolsPlugin",
    "openai_tool",
    "skill_descriptor",
    "skill_install_descriptor",
]
