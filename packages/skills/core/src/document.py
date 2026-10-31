"""Shared validation for skill documents, including installation staging."""
import hashlib
import re
from pathlib import Path
import yaml
from .registry import NAME, MAX_SKILL_BYTES, Skill, SkillError, SkillSource

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
