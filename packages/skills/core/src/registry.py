"""Provider-neutral skill contracts and a runtime-scoped registry."""
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Protocol, Sequence
from agent_platform_plugin_sdk import Registration, ServiceClosedError, ServiceKey, RegistrationConflictError

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SKILL_BYTES = 128 * 1024


class SkillError(ValueError):
    """可向用户展示的技能配置或加载错误。"""


@dataclass(frozen=True)
class SkillScope:
    tenant_id: int
    agent_key: str
    tool_names: frozenset[str]
    enabled: bool = True
    enabled_names: tuple[str, ...] | None = None

    def allows(self, skill: "SkillSummary") -> bool:
        return self.enabled and (self.enabled_names is None or any(
            name in (skill.key, skill.name, skill.binding_key, *skill.aliases) for name in self.enabled_names
        ))


@dataclass(frozen=True)
class SkillSource:
    name: str
    root: Path
    kind: str = "skill"
    tenant_ids: tuple[int, ...] | None = None
    agent_keys: tuple[str, ...] | None = None
    requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)
    package_key: str | None = None
    package_name: str | None = None
    tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def visible(self, scope: SkillScope) -> bool:
        return ((self.tenant_ids is None or scope.tenant_id in self.tenant_ids)
                and (self.agent_keys is None or scope.agent_key in self.agent_keys))


@dataclass(frozen=True)
class SkillSummary:
    key: str
    name: str
    description: str
    source: str
    kind: str
    path: Path
    resource_base: Path
    model_invocable: bool
    user_invocable: bool
    argument_hint: str
    required_tools: tuple[str, ...]
    package_key: str | None = None
    package_name: str | None = None
    tools: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    @property
    def bound_tools(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.required_tools) | set(self.tools)))

    @property
    def binding_key(self) -> str:
        # The reserved marker cannot collide with a source:name skill identity.
        return f"@package/{self.package_key}" if self.package_key else self.key

    def unavailable_reason(self, scope: SkillScope) -> str | None:
        missing = sorted(set(self.required_tools) - scope.tool_names)
        return "所需工具未加载或不可用：" + "、".join(missing) if missing else None


@dataclass(frozen=True, kw_only=True)
class Skill(SkillSummary):
    """Full instructions, returned only by an explicit get/load."""
    content: str
    content_hash: str


class SkillProvider(Protocol):
    """A source contributes skills without coupling the registry to storage."""
    name: str
    def list(self, scope: SkillScope) -> Sequence[SkillSummary]: ...
    def get(self, candidate: SkillSummary, scope: SkillScope) -> Skill | None: ...


class SkillsService(Protocol):
    def register_provider(self, provider: SkillProvider) -> Registration: ...
    def list(self, scope: SkillScope) -> list[SkillSummary]: ...
    def get(self, name: str, scope: SkillScope) -> Skill | None: ...
    def load(self, name: str, scope: SkillScope, resource: str | None = None) -> dict: ...


SKILLS: ServiceKey[SkillsService] = ServiceKey("skills")


class _ProviderRegistration:
    def __init__(self, registry: "SkillRegistry", provider: SkillProvider) -> None:
        self.registry = registry
        self.provider = provider

    async def aclose(self) -> None:
        if self.registry._providers.get(self.provider.name) is self.provider:
            del self.registry._providers[self.provider.name]


class SkillRegistry:
    """One runtime's registry; providers and their effects have explicit owners."""
    def __init__(self) -> None:
        self._providers: dict[str, SkillProvider] = {}
        self._closed = False

    def register_provider(self, provider: SkillProvider) -> Registration:
        self._ensure_open()
        if provider.name in self._providers:
            raise RegistrationConflictError(f"skill provider already registered: {provider.name}")
        self._providers[provider.name] = provider
        return _ProviderRegistration(self, provider)

    def _collect(self, scope: SkillScope) -> dict[str, tuple[SkillSummary, SkillProvider]]:
        self._ensure_open()
        if not scope.enabled:
            return {}
        skills: dict[str, tuple[SkillSummary, SkillProvider]] = {}
        for provider in tuple(self._providers.values()):
            for skill in provider.list(scope):
                if not scope.allows(skill):
                    continue
                if skill.key in skills:
                    raise SkillError(f"技能标识重复：{skill.key}")
                skills[skill.key] = (skill, provider)
        return skills

    def list(self, scope: SkillScope) -> list[SkillSummary]:
        return sorted([SkillSummary(**{f.name: getattr(candidate, f.name) for f in fields(SkillSummary)})
                       for candidate, _ in self._collect(scope).values()], key=lambda skill: skill.key)

    def get(self, name: str, scope: SkillScope) -> Skill | None:
        matches = [(skill, provider) for skill, provider in self._collect(scope).values()
                   if name in (skill.name, skill.key, *skill.aliases)]
        if len(matches) > 1:
            raise SkillError(f"技能名称有歧义，请使用完整名称：{'、'.join(skill.key for skill, _ in matches)}")
        if not matches:
            return None
        candidate, provider = matches[0]
        loader = getattr(provider, "get", None)
        loaded = loader(candidate, scope) if callable(loader) else candidate if isinstance(candidate, Skill) else None
        if loaded is None:
            return None
        if loaded.key != candidate.key or loaded.source != candidate.source:
            raise SkillError("技能在发现与加载之间发生变化，请重试")
        return loaded if scope.allows(loaded) else None

    def load(self, name: str, scope: SkillScope, resource: str | None = None) -> dict:
        from .runtime import load_model_skill
        return load_model_skill(name, scope, self, resource)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ServiceClosedError("skills service is closed")

    async def aclose(self) -> None:
        self._closed = True
        self._providers.clear()
