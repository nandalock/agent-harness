"""两种技能加载入口共享渲染；展开后的指令由 Session 保存。"""
import html
import json

from .registry import Skill, SkillError, SkillsService, SkillScope

def scope_for(tenant_id, agent_key, tool_names, config):
    names = config.get("enabled_skills")
    if names is not None and (not isinstance(names, list) or any(not isinstance(n, str) for n in names)):
        raise SkillError("enabled_skills 必须为技能名称列表")
    return SkillScope(tenant_id, agent_key, frozenset(tool_names),
                      enabled=config.get("skills_enabled", True) is not False,
                      enabled_names=tuple(names) if names is not None else None)


def render_skill(skill: Skill, arguments: str = "", *, scope: SkillScope | None = None) -> str:
    # 参数仅进行文本替换，永远不作为 shell 命令或文件路径求值。
    body = skill.content.replace("$ARGUMENTS", arguments)
    missing = sorted(set(skill.bound_tools) - scope.tool_names) if scope is not None else []
    status = ("当前声明的工具尚未就绪：" + "、".join(missing)
              + "。可以读取本技能和设置参考资料；具体业务操作须等待对应工具就绪。\n") if missing else ""
    return (f'<skill_content name="{html.escape(skill.key, quote=True)}">\n'
            f"技能资源根目录：{skill.resource_base}\n"
            f"附属文本资源用 skill 工具读取：name={skill.key}，resource=相对路径；不要假设该目录已挂载到 shell 沙箱。\n"
            + status
            + f"<skill_instructions>\n{body}\n</skill_instructions>\n</skill_content>")


def catalog_entries(registry: SkillsService, scope: SkillScope) -> list[dict]:
    skills = registry.list(scope)
    counts = {s.name: sum(other.name == s.name for other in skills) for s in skills}
    return [{
        "key": s.key, "name": s.name if counts[s.name] == 1 else s.key,
        "description": s.description, "source": s.source, "kind": s.kind,
        "package_key": s.package_key or s.key,
        "package_name": s.package_name or s.package_key or (s.name if counts[s.name] == 1 else s.key),
        "binding_key": s.binding_key,
        "tools": list(s.bound_tools),
        "tools_ready": set(s.bound_tools).issubset(scope.tool_names),
        "aliases": list(s.aliases),
        "argument_hint": s.argument_hint, "model_invocable": s.model_invocable,
        "user_invocable": s.user_invocable, "unavailable_reason": s.unavailable_reason(scope),
    } for s in skills]


def load_model_skill(name: str, scope: SkillScope, registry: SkillsService, resource: str | None = None) -> dict:
    skill = registry.get(name, scope)
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
    return {"name": skill.key, "content_hash": skill.content_hash, "text": render_skill(skill, scope=scope)}
