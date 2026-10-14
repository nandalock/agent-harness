"""从显式配置的目录发现技能；模型参数不能选择文件路径或租户。"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
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


def _boolean(metadata, name, default):
    value = metadata.get(name, default)
    if not isinstance(value, bool):
        raise SkillError(f"{name} 必须为布尔值")
    return value


def _load(path: Path, source: SkillSource) -> Skill:
    resolved = path.resolve()
    root = source.root.resolve()
    if not resolved.is_relative_to(root):
        raise SkillError(f"技能文件超出配置目录：{path.name}")
    if resolved.stat().st_size > MAX_SKILL_BYTES:
        raise SkillError(f"技能文件过大：{path.name}")
    raw = resolved.read_text(encoding="utf-8-sig")
    parts = re.split(r"^---\s*$", raw, maxsplit=2, flags=re.MULTILINE)
    if len(parts) != 3 or parts[0].strip():
        raise SkillError(f"技能缺少 YAML 元数据：{path.name}")
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise SkillError(f"技能 YAML 无效：{path.name}") from exc
    if not isinstance(metadata, dict):
        raise SkillError(f"技能元数据必须为对象：{path.name}")
    name, description = metadata.get("name"), metadata.get("description")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise SkillError(f"技能名称无效：{path.name}")
    if not isinstance(description, str) or not description.strip():
        raise SkillError(f"技能缺少描述：{name}")
    hint = metadata.get("argument-hint", "")
    required = metadata.get("required-tools", source.requirements.get(name, ()))
    if not isinstance(hint, str) or not isinstance(required, (list, tuple)) or any(not isinstance(t, str) for t in required):
        raise SkillError(f"技能参数提示或工具依赖无效：{name}")
    content = parts[2].strip()
    if not content:
        raise SkillError(f"技能正文为空：{name}")
    return Skill(
        key=f"{source.name}:{name}", name=name, description=description.strip(),
        source=source.name, kind=source.kind, path=resolved,
        resource_base=resolved.parent if path.name == "SKILL.md" else root,
        model_invocable=not _boolean(metadata, "disable-model-invocation", source.kind == "command"),
        user_invocable=_boolean(metadata, "user-invocable", True),
        argument_hint=hint, required_tools=tuple(required), content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


class SkillRegistry:
    """共享源按租户和智能体过滤，正文每次加载时重新读取。"""

    def __init__(self, sources: list[SkillSource]):
        self.sources = tuple(sources)
        for source in self.sources:
            if not NAME.fullmatch(source.name) or source.kind not in ("skill", "command"):
                raise SkillError("技能来源名称或类型无效")

    def list(self, scope: SkillScope) -> list[Skill]:
        if not scope.enabled:
            return []
        skills = {}
        for source in self.sources:
            if not source.visible(scope):
                continue
            if not source.root.is_dir():
                raise SkillError(f"技能来源目录不存在：{source.name}")
            for entry in sorted(source.root.iterdir()):
                path = entry / "SKILL.md" if entry.is_dir() else entry
                if not path.is_file() or path.suffix != ".md":
                    continue
                skill = _load(path, source)
                if scope.enabled_names is not None and skill.key not in scope.enabled_names and skill.name not in scope.enabled_names:
                    continue
                if skill.key in skills:
                    raise SkillError(f"技能标识重复：{skill.key}")
                skills[skill.key] = skill
        return sorted(skills.values(), key=lambda s: s.key)

    def get(self, name: str, scope: SkillScope) -> Skill | None:
        matches = [s for s in self.list(scope) if name in (s.name, s.key)]
        if len(matches) > 1:
            raise SkillError(f"技能名称有歧义，请使用完整名称：{'、'.join(s.key for s in matches)}")
        return matches[0] if matches else None


def default_sources() -> list[SkillSource]:
    root = Path(__file__).resolve().parents[1] / "skill_packages/overleaf_rt"
    sources = [
        SkillSource("overleaf-rt", root / "skills", requirements={
            "overleaf-setup": ("overleaf_list_hosts", "overleaf_list_projects"),
            "overleaf-editing": ("overleaf_read_doc", "overleaf_edit_doc"),
            "overleaf-latex-workflow": ("overleaf_compile", "overleaf_read_compile_log"),
            "overleaf-comments": ("overleaf_list_comments",),
        }),
        SkillSource("overleaf-rt", root / "commands", kind="command", requirements={
            "overleaf-login": ("overleaf_list_hosts", "overleaf_list_projects"),
            "overleaf-status": ("overleaf_list_hosts", "overleaf_list_projects"),
        }),
    ]
    for source in json.loads(os.environ.get("SKILL_SOURCES", "[]")):
        # 自定义目录必须声明归属，避免共享服务器的个人技能跨租户出现。
        if not source.get("tenant_ids"):
            raise SkillError("自定义技能来源必须声明 tenant_ids")
        path = Path(source["path"])
        if not path.is_absolute():
            raise SkillError("技能来源必须使用后端可读取的绝对路径")
        sources.append(SkillSource(
            source["name"], path, source.get("kind", "skill"),
            tuple(source["tenant_ids"]),
            tuple(source["agent_keys"]) if "agent_keys" in source else None,
        ))
    return sources


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry(default_sources())
    return _registry
