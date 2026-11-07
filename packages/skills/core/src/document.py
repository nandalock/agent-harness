"""Read metadata for discovery; read instructions only on explicit load."""
import hashlib
from dataclasses import fields
from pathlib import Path
import yaml
from .registry import NAME, MAX_SKILL_BYTES, Skill, SkillSummary, SkillError, SkillSource


def _boolean(metadata, name, default):
    value = metadata.get(name, default)
    if not isinstance(value, bool):
        raise SkillError(f"{name} 必须为布尔值")
    return value


def _read(path: Path, source: SkillSource, *, body: bool):
    resolved = path.resolve()
    root = source.root.resolve()
    if not resolved.is_relative_to(root):
        raise SkillError(f"技能文件超出配置目录：{path.name}")
    if resolved.stat().st_size > MAX_SKILL_BYTES:
        raise SkillError(f"技能文件过大：{path.name}")
    with resolved.open(encoding="utf-8-sig") as reader:
        line = reader.readline()
        while line and not line.strip():
            line = reader.readline()
        if line.strip() != "---":
            raise SkillError(f"技能缺少 YAML 元数据：{path.name}")
        header = []
        for line in reader:
            if line.strip() == "---":
                break
            header.append(line)
        else:
            raise SkillError(f"技能缺少 YAML 元数据：{path.name}")
        # Catalog discovery stops at the YAML delimiter: no body or references.
        content = reader.read().strip() if body else None
    try:
        metadata = yaml.safe_load("".join(header))
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
    tools = metadata.get("tools", source.tools.get(name, ()))
    if not isinstance(hint, str) or not isinstance(required, (list, tuple)) or any(not isinstance(t, str) for t in required):
        raise SkillError(f"技能参数提示或工具依赖无效：{name}")
    if not isinstance(tools, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in tools):
        raise SkillError(f"技能工具声明无效：{name}")
    summary = SkillSummary(
        key=f"{source.name}:{name}", name=name, description=description.strip(),
        source=source.name, kind=source.kind, path=resolved,
        resource_base=resolved.parent if path.name == "SKILL.md" else root,
        model_invocable=not _boolean(metadata, "disable-model-invocation", source.kind == "command"),
        user_invocable=_boolean(metadata, "user-invocable", True),
        argument_hint=hint, required_tools=tuple(required), tools=tuple(tools),
        package_key=source.package_key, package_name=source.package_name,
        aliases=source.aliases.get(name, ()),
    )
    return summary, content


def _load_summary(path: Path, source: SkillSource) -> SkillSummary:
    return _read(path, source, body=False)[0]


def _load(path: Path, source: SkillSource) -> Skill:
    summary, content = _read(path, source, body=True)
    if not content:
        raise SkillError(f"技能正文为空：{summary.name}")
    return Skill(**{f.name: getattr(summary, f.name) for f in fields(SkillSummary)}, content=content,
                 content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest())
