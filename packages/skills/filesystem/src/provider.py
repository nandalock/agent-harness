"""Local directory discovery; all filesystem policy belongs to this provider."""
from agent_platform_skills.registry import Skill, SkillSummary, SkillError, SkillSource, SkillScope, NAME
from agent_platform_skills.document import _load, _load_summary
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
            if source.package_key is not None and not NAME.fullmatch(source.package_key):
                raise SkillError("技能包标识无效")

    def list(self, scope: SkillScope) -> list[SkillSummary]:
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
                skill = _load_summary(path, source)
                if not scope.allows(skill):
                    continue
                if skill.key in skills:
                    raise SkillError(f"技能标识重复：{skill.key}")
                skills[skill.key] = skill
        return sorted(skills.values(), key=lambda s: s.key)

    def get(self, candidate: SkillSummary, scope: SkillScope) -> Skill | None:
        sources = list(self.sources)
        if self.include_installed:
            sources.append(installed_source(scope))
        for source in sources:
            if (source.name == candidate.source and source.visible(scope)
                    and candidate.path.resolve().is_relative_to(source.root.resolve())):
                if not candidate.path.is_file():
                    return None
                return _load(candidate.path, source)
        return None
