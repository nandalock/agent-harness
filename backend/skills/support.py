"""Explicit file-backed registries for skill regression tests."""
from agent_platform_skills import SkillRegistry
from agent_platform_skills_filesystem import FilesystemSkillProvider
from contextlib import asynccontextmanager
from agent_platform_plugin_runtime import PluginRuntime
from agent_platform_agent_runtime import AgentExtensionRegistry
from agent_platform_plugin_sdk import AGENTS, AGENT_EXTENSIONS


def filesystem_registry(sources, *, include_installed=False):
    registry = SkillRegistry()
    registry.register_provider(FilesystemSkillProvider(sources, include_installed=include_installed))
    return registry


@asynccontextmanager
async def installed_skill_runtime(extensions=None):
    class Agents:
        async def get_config(self, key):
            return {}
    extensions = extensions or AgentExtensionRegistry()
    runtime = PluginRuntime({"plugins": [
        {"id": "skills", "name": "agent-platform.skills-default"},
        {"id": "filesystem", "name": "agent-platform.skills-filesystem"},
        {"id": "tools", "name": "agent-platform.tools-default"},
        {"id": "skill-tools", "name": "agent-platform.skill-tools"},
    ]}, host_services={AGENTS: Agents(), AGENT_EXTENSIONS: extensions})
    await runtime.start()
    try:
        yield runtime, extensions
    finally:
        await runtime.aclose()
