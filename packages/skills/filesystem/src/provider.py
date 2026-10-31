"""Local directory discovery; all filesystem policy belongs to this provider."""
from agent_platform_skills.registry import Skill, SkillError, SkillSource, SkillScope, NAME
from agent_platform_skills.document import _load
from agent_platform_skills.installer import installed_source

class FilesystemSkillProvider:
    """共享源按租户和智能体过滤，正文每次加载时重新读取。"""

    def __init__(self, sources: list[SkillSource], *, include_installed: bool = False, name: str = "filesystem"):
        self.name = name
        self.sources = tuple(sources)
        self.include_installed = include_installed
        for source in self.sources:
            if not NAME.fullmatch(source.name) or source.kind not in ("skill", "command"):
                raise SkillError("技能来源名称或类型无效")

    def list(self, scope: SkillScope) -> list[Skill]:
        if not scope.enabled:
            return []
        skills = {}
        sources = list(self.sources)
        if self.include_installed:
            installed = installed_source(scope)
            if installed.root.is_dir():
                sources.append(installed)
        for source in sources:
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
