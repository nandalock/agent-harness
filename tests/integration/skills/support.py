"""Explicit file-backed registries for skill regression tests."""
from agent_platform_skills import SkillRegistry
from agent_platform_skills_filesystem import FilesystemSkillProvider
from contextlib import asynccontextmanager
from minidsh_cordis_plugin_loader import Loader
from agent_platform_agent_runtime import AgentExtensionRegistry
from agent_platform_plugin_sdk import AGENTS, AGENT_EXTENSIONS, TOOL_BINDINGS, TOOLS
from agent_platform_skills import SKILLS
from agent_platform_http_api.services import reset_services, set_services


class _ToolBindings:
    def get_bindings(self, agent_key):
        return []


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
    runtime = Loader({"plugins": [
        {"id": "skills", "name": "agent-platform.skills-default", "use": "agent_platform_skills_default:SkillsDefaultPlugin"},
        {"id": "filesystem", "name": "agent-platform.skills-filesystem", "use": "agent_platform_skills_filesystem:SkillsFilesystemPlugin"},
        {"id": "tools", "name": "agent-platform.tools-default", "use": "agent_platform_tools_default:ToolsDefaultPlugin"},
        {"id": "skill-tools", "name": "agent-platform.skill-tools", "use": "agent_platform_skill_tools:SkillToolsPlugin"},
    ]}, host_services={AGENTS: Agents(), AGENT_EXTENSIONS: extensions})
    await runtime.start()
    token = set_services({
        AGENTS: runtime.require(AGENTS),
        AGENT_EXTENSIONS: extensions,
        TOOLS: runtime.require(TOOLS),
        SKILLS: runtime.require(SKILLS),
        TOOL_BINDINGS: _ToolBindings(),
    })
    try:
        yield runtime, extensions
    finally:
        reset_services(token)
        await runtime.aclose()
