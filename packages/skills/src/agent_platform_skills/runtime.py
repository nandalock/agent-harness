"""两种技能加载入口共享渲染；展开后的指令由 Session 保存。"""
import asyncio
import hashlib
import html
import json
import re

from .registry import Skill, SkillError, SkillRegistry, SkillScope, get_skill_registry

SLASH = re.compile(r"^(?:/|\$(?=skill-installer(?:\s|$)))([a-z0-9]+(?:-[a-z0-9]+)*(?::[a-z0-9]+(?:-[a-z0-9]+)*)?)(?=\s|$)")


def scope_for(tenant_id, agent_key, tool_names, config):
    names = config.get("enabled_skills")
    if names is not None and (not isinstance(names, list) or any(not isinstance(n, str) for n in names)):
        raise SkillError("enabled_skills 必须为技能名称列表")
    return SkillScope(tenant_id, agent_key, frozenset(tool_names),
                      enabled=config.get("skills_enabled", True) is not False,
                      enabled_names=tuple(names) if names is not None else None)


def render_skill(skill: Skill, arguments: str = "") -> str:
    # 参数仅进行文本替换，永远不作为 shell 命令或文件路径求值。
    body = skill.content.replace("$ARGUMENTS", arguments)
    return (f'<skill_content name="{html.escape(skill.key, quote=True)}">\n'
            f"技能资源根目录：{skill.resource_base}\n"
            f"附属文本资源用 skill 工具读取：name={skill.key}，resource=相对路径；不要假设该目录已挂载到 shell 沙箱。\n"
            f"<skill_instructions>\n{body}\n</skill_instructions>\n</skill_content>")


def catalog_entries(registry: SkillRegistry, scope: SkillScope) -> list[dict]:
    skills = registry.list(scope)
    counts = {s.name: sum(other.name == s.name for other in skills) for s in skills}
    return [{
        "key": s.key, "name": s.name if counts[s.name] == 1 else s.key,
        "description": s.description, "source": s.source, "kind": s.kind,
        "argument_hint": s.argument_hint, "model_invocable": s.model_invocable,
        "user_invocable": s.user_invocable, "unavailable_reason": s.unavailable_reason(scope),
    } for s in skills]


def load_model_skill(name: str, scope: SkillScope, registry=None, resource: str | None = None) -> dict:
    skill = (registry or get_skill_registry()).get(name, scope)
    if skill is None:
        raise SkillError(f"技能不存在或未启用：{name}")
    if not skill.model_invocable:
        raise SkillError(f"技能仅允许用户显式调用：{name}")
    if reason := skill.unavailable_reason(scope):
        raise SkillError(reason)
    if resource is not None:
        from pathlib import Path
        from .registry import MAX_SKILL_BYTES
        relative = Path(resource)
        path = (skill.resource_base / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(skill.resource_base.resolve()):
            raise SkillError("技能资源路径必须位于技能目录内")
        if not path.is_file() or path.stat().st_size > MAX_SKILL_BYTES:
            raise SkillError("技能资源不存在或超过大小限制")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise SkillError("技能资源必须为 UTF-8 文本") from exc
        return {"name": skill.key, "resource": resource, "text": text}
    return {"name": skill.key, "content_hash": skill.content_hash, "text": render_skill(skill)}


class SkillPreStep:
    """只处理本步认领的用户输入；历史与重试不会重新展开指令。"""

    def __init__(self, scope: SkillScope, registry=None):
        self.scope = scope
        self.registry = registry or get_skill_registry()

    async def __call__(self, session, messages):
        injections = []
        entries = await asyncio.to_thread(catalog_entries, self.registry, self.scope)
        model_entries = [{"name": e["name"], "description": e["description"][:500]}
                         for e in entries if e["model_invocable"] and not e["unavailable_reason"]
                         and "skill" in self.scope.tool_names]
        digest = hashlib.sha256(json.dumps(model_entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        previous = next((e for e in reversed(session.events)
                         if e.type == "user/message" and e.data.get("source", {}).get("kind") == "skill-catalog"), None)
        if (previous is not None or model_entries) and (previous is None or previous.data["source"].get("digest") != digest):
            content = ("以下为当前完整技能目录，替换此前目录。按需调用 skill 工具加载正文后执行，"
                       "用户显式调用已提供 skill_content 时不要重复加载。\n"
                       + json.dumps(model_entries, ensure_ascii=False))
            injections.append({
                "content": content, "source": {"kind": "skill-catalog", "digest": digest, "entries": model_entries},
            })
        for message in messages:
            if message.source != "user" or not (match := SLASH.match(message.text)):
                continue
            name = match[1]
            skill = await asyncio.to_thread(self.registry.get, name, self.scope)
            if skill is None or not skill.user_invocable:
                continue
            # 首先保留用户输入，再记录实际展开的正文或可操作的拒绝原因。
            reason = skill.unavailable_reason(self.scope)
            arguments = message.text[match.end():].strip()
            event = next(e for e in reversed(session.events)
                         if e.type == "user/message" and e.data.get("msg_id") == message.id)
            source = {"kind": "skill-invocation", "name": skill.key,
                      "arguments": arguments, "content_hash": skill.content_hash,
                      "user_event_seq": event.seq, "status": "error" if reason else "loaded"}
            injections.append({
                "content": f"技能 {name} 无法加载：{reason}。请说明缺少的工具，不要执行该技能。" if reason else render_skill(skill, arguments),
                "source": source,
            })
        return injections
