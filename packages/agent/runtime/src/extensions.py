"""Plugin-owned agent extension registry. Plugins own their registrations."""
from dataclasses import replace
import logging
from agent_platform_plugin_sdk.agents import AgentExtension, RequestPreparation
from agent_platform_plugin_sdk import (
    AgentRunContext, AgentRunContribution, Registration, RegistrationConflictError, ServiceClosedError,
)

logger = logging.getLogger(__name__)


class _Registration:
    def __init__(self, registry: "AgentExtensionRegistry", name: str, callback: AgentExtension) -> None:
        self.registry, self.name, self.callback = registry, name, callback

    async def aclose(self) -> None:
        if self.registry._extensions.get(self.name) is self.callback:
            del self.registry._extensions[self.name]


class AgentExtensionRegistry:
    def __init__(self) -> None:
        self._extensions: dict[str, AgentExtension] = {}
        self._closed = False

    def register(self, name: str, extension: AgentExtension) -> Registration:
        if self._closed:
            raise ServiceClosedError("agent extensions are closed")
        if name in self._extensions:
            raise RegistrationConflictError(f"agent extension already registered: {name}")
        self._extensions[name] = extension
        return _Registration(self, name, extension)

    async def prepare(self, context: AgentRunContext) -> AgentRunContribution:
        if self._closed:
            raise ServiceClosedError("agent extensions are closed")
        context = replace(context, tool_schemas=list(context.tool_schemas))
        hooks = []
        request_hooks = []
        capabilities = set()
        automatic_tools: dict[str, set[str]] = {}
        for name, extension in tuple(self._extensions.items()):
            contribution = await extension(context)
            capabilities.update(contribution.capabilities)
            for tool, owners in contribution.automatic_tools.items():
                automatic_tools.setdefault(tool, set()).update(owners)
            context = replace(context, tool_schemas=contribution.tool_schemas)
            if contribution.pre_step is not None:
                hooks.append((name, extension, contribution.pre_step))
            if contribution.prepare_request is not None:
                request_hooks.append((name, extension, contribution.prepare_request))

        async def pre_step(session, messages):
            injections = []
            for name, extension, hook in hooks:
                if self._extensions.get(name) is not extension:
                    continue
                try:
                    injections.extend(await hook(session, messages))
                except Exception:
                    logger.exception("Agent extension %s pre_step failed", name)
            return injections

        async def prepare_request(session, request, llm):
            context_parts = []
            events = []
            for name, extension, hook in request_hooks:
                if self._extensions.get(name) is not extension:
                    continue
                try:
                    prepared = await hook(session, request, llm)
                    if prepared.system_context:
                        context_parts.append(prepared.system_context)
                    events.extend(prepared.events)
                except Exception:
                    logger.exception("Agent extension %s prepare_request failed", name)
            return RequestPreparation("\n\n".join(context_parts), tuple(events))

        return AgentRunContribution(
            context.tool_schemas, pre_step if hooks else None, frozenset(capabilities),
            {name: tuple(sorted(owners)) for name, owners in automatic_tools.items()},
            prepare_request if request_hooks else None,
        )


    async def aclose(self) -> None:
        self._closed = True
        self._extensions.clear()
