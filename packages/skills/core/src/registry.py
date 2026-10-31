"""Provider-neutral skill contracts and a runtime-scoped registry."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence
from agent_platform_plugin_sdk import Registration, ServiceClosedError, ServiceKey, ServiceRef, RegistrationConflictError

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


@dataclass(frozen=True)
class SkillSource:
    name: str
    root: Path
    kind: str = "skill"
    tenant_ids: tuple[int, ...] | None = None
    agent_keys: tuple[str, ...] | None = None
    requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def visible(self, scope: SkillScope) -> bool:
        return ((self.tenant_ids is None or scope.tenant_id in self.tenant_ids)
                and (self.agent_keys is None or scope.agent_key in self.agent_keys))


@dataclass(frozen=True)
class Skill:
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
    content: str
    content_hash: str

    def unavailable_reason(self, scope: SkillScope) -> str | None:
        missing = sorted(set(self.required_tools) - scope.tool_names)
        return "请先为智能体绑定工具：" + "、".join(missing) if missing else None


class SkillProvider(Protocol):
    """A source contributes skills without coupling the registry to storage."""
    name: str
    def list(self, scope: SkillScope) -> Sequence[Skill]: ...


class SkillsService(Protocol):
    def register_provider(self, provider: SkillProvider) -> Registration: ...
    def list(self, scope: SkillScope) -> list[Skill]: ...
    def get(self, name: str, scope: SkillScope) -> Skill | None: ...
    def load(self, name: str, scope: SkillScope, resource: str | None = None) -> dict: ...


SKILLS: ServiceKey[SkillsService] = ServiceKey(ServiceRef(name="skills", api_version=1))


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

    def list(self, scope: SkillScope) -> list[Skill]:
        self._ensure_open()
        if not scope.enabled:
            return []
        skills: dict[str, Skill] = {}
        for provider in tuple(self._providers.values()):
            for skill in provider.list(scope):
                if scope.enabled_names is not None and skill.key not in scope.enabled_names and skill.name not in scope.enabled_names:
                    continue
                if skill.key in skills:
                    raise SkillError(f"技能标识重复：{skill.key}")
                skills[skill.key] = skill
        return sorted(skills.values(), key=lambda skill: skill.key)

    def get(self, name: str, scope: SkillScope) -> Skill | None:
        matches = [skill for skill in self.list(scope) if name in (skill.name, skill.key)]
        if len(matches) > 1:
            raise SkillError(f"技能名称有歧义，请使用完整名称：{'、'.join(skill.key for skill in matches)}")
        return matches[0] if matches else None

    def load(self, name: str, scope: SkillScope, resource: str | None = None) -> dict:
        from .runtime import load_model_skill
        return load_model_skill(name, scope, self, resource)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ServiceClosedError("skills service is closed")

    async def aclose(self) -> None:
        self._closed = True
        self._providers.clear()
