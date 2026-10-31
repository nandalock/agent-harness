"""Directory configuration for bundled, user and tenant-scoped skills."""
import json
import os
from pathlib import Path
from agent_platform_skills import SkillError, SkillSource

def default_sources(*, include_builtin: bool = True) -> list[SkillSource]:
    packages_root = Path(os.environ.get(
        "SKILL_PACKAGES_ROOT",
        Path(__file__).resolve().parent / "builtin",
    )).resolve()
    root = packages_root / "overleaf_rt"
    sources = [
        SkillSource("platform", packages_root / "platform"),
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
    if not include_builtin:
        sources = []
    for source in json.loads(os.environ.get("SKILL_SOURCES", "[]")):
        if source.get("name") in ("installed", "platform"):
            raise SkillError("installed 和 platform 是平台保留的技能来源名称")
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
