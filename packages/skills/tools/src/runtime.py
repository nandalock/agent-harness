"""Model catalog and explicit skill invocation as a plugin-owned loop hook."""
import asyncio
import hashlib
import html
import json
import re
from agent_platform_skills import SkillScope, SkillsService
from agent_platform_skills.runtime import catalog_entries, render_skill

SLASH = re.compile(r"^(?:/|\$(?=skill-installer(?:\s|$)))([a-z0-9]+(?:-[a-z0-9]+)*(?::[a-z0-9]+(?:-[a-z0-9]+)*)?)(?=\s|$)")


def render_catalog(entries: list[dict], *, update: bool) -> str:
    lines = [
        "<system-reminder>",
        "技能目录已更新，以下完整目录替换此前目录：" if update else "以下技能已在当前智能体启用：",
        "",
        "<available_skills>",
    ]
    for entry in entries:
        name = html.escape(entry["name"], quote=False)
        description = html.escape(" ".join(entry["description"].split()), quote=False)
        status = ""
        if not entry["available"]:
            reason = html.escape(" ".join(entry["unavailable_reason"].split()), quote=False)
            status = f"（暂不可加载：{reason}）"
        elif not entry["model_loadable"]:
            status = "（仅可由用户显式调用）" if entry["user_invocable"] else "（当前不可加载）"
        elif not entry["tools_ready"]:
            status = "（执行工具未全部就绪）"
        lines.append(f"- `{name}`: {description}{status}")
    lines.extend(["</available_skills>", ""])
    if entries:
        lines.extend([
            "用户提到技能或任务匹配其描述时，行动前先调用 skill 加载完整指令；不要根据摘要推测操作步骤。",
            "标记不可加载或仅限用户调用的条目不要自行加载，实际执行以当前工具列表为准。",
            "已提供 <skill_content> 时遵循其中指令，无需重复加载。",
        ])
    else:
        lines.append("当前没有已启用的技能，不要沿用此前目录中的名称。")
    lines.append("</system-reminder>")
    return "\n".join(lines)


class SkillPreStep:
    """只处理本步认领的用户输入；历史与重试不会重新展开指令。"""

    def __init__(self, scope: SkillScope, registry: SkillsService):
        self.scope = scope
        self.registry = registry

    async def __call__(self, session, messages):
        injections = []
        entries = await asyncio.to_thread(catalog_entries, self.registry, self.scope)
        # Enabled skills remain discoverable when execution dependencies are
        # unavailable. Knowledge of a skill must not imply permission to run it.
        model_entries = [{
            "name": e["name"], "description": e["description"][:500],
            "package": e["package_name"], "kind": e["kind"],
            "available": not bool(e["unavailable_reason"]),
            "tools_ready": e["tools_ready"],
            "unavailable_reason": e["unavailable_reason"],
            "model_loadable": bool(e["model_invocable"] and not e["unavailable_reason"]
                                   and "skill" in self.scope.tool_names),
            "user_invocable": e["user_invocable"],
        } for e in entries]
        digest = hashlib.sha256(json.dumps(model_entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        previous = next((e for e in reversed(session.events)
                         if e.type == "user/message" and e.data.get("source", {}).get("kind") == "skill-catalog"), None)
        if (previous is not None or model_entries) and (
            previous is None or previous.data["source"].get("digest") != digest
            or previous.data["source"].get("form") != "catalog"
        ):
            injections.append({
                "content": render_catalog(model_entries, update=previous is not None),
                "source": {"kind": "skill-catalog", "form": "catalog", "update": previous is not None,
                           "digest": digest, "entries": model_entries},
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
                "content": f"技能 {name} 无法加载：{reason}。请说明缺少的工具，不要执行该技能。" if reason else render_skill(skill, arguments, scope=self.scope),
                "source": source,
            })
        return injections
