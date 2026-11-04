"""Model catalog and explicit skill invocation as a plugin-owned loop hook."""
import asyncio
import hashlib
import json
import re
from agent_platform_skills import SkillScope, SkillsService
from agent_platform_skills.runtime import catalog_entries, render_skill

SLASH = re.compile(r"^(?:/|\$(?=skill-installer(?:\s|$)))([a-z0-9]+(?:-[a-z0-9]+)*(?::[a-z0-9]+(?:-[a-z0-9]+)*)?)(?=\s|$)")


class SkillPreStep:
    """只处理本步认领的用户输入；历史与重试不会重新展开指令。"""

    def __init__(self, scope: SkillScope, registry: SkillsService):
        self.scope = scope
        self.registry = registry

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
