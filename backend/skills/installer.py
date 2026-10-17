"""从公开 GitHub 仓库安装完整技能包；不执行安装包中的任何代码。"""
import asyncio
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from urllib.parse import quote, unquote, urlsplit
import zipfile

import aiohttp

from backend.core.http import get_http_session
from backend.skills.registry import NAME, SkillError, SkillScope, SkillSource, _load

CATALOG_REPO = "openai/skills"
CATALOG_PATH = "skills/.curated"
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_FILES = 2048
MAX_ARCHIVE_ENTRIES = 20000
INSTALL_TIMEOUT = 90


def install_enabled(config: dict) -> bool:
    """技能开关和白名单同时约束安装入口。"""
    names = config.get("enabled_skills")
    return (config.get("skills_enabled", True) is not False
            and config.get("skill_install_enabled", True) is not False
            and (names is None or "skill-installer" in names or "platform:skill-installer" in names))


def installation_root() -> Path:
    return Path(os.environ.get("SKILL_INSTALL_ROOT", Path(__file__).resolve().parents[2] / ".data/skills")).resolve()


def installed_source(scope: SkillScope) -> SkillSource:
    """目录归属来自服务端上下文，不接受模型指定租户、智能体或磁盘路径。"""
    if type(scope.tenant_id) is not int or scope.tenant_id <= 0 or not scope.agent_key:
        raise SkillError("技能安装缺少有效的租户和智能体上下文")
    agent = hashlib.sha256(scope.agent_key.encode()).hexdigest()
    root = installation_root() / str(scope.tenant_id) / agent
    return SkillSource("installed", root, tenant_ids=(scope.tenant_id,), agent_keys=(scope.agent_key,))


@dataclass(frozen=True)
class GitHubSkill:
    repository: str
    ref: str
    path: str


def parse_source(source: str, ref: str | None = None) -> GitHubSkill:
    """支持推荐目录中的名称和 GitHub tree/blob 地址；ref 可消除含 / 分支名的歧义。"""
    if not isinstance(source, str) or not source.strip():
        raise SkillError("请提供技能名称或 GitHub 技能目录地址")
    source = source.strip()
    if ref is not None and (not isinstance(ref, str) or not ref or len(ref) > 200 or any(ord(c) < 32 for c in ref)):
        raise SkillError("ref 必须为有效的分支、标签或提交号")
    if NAME.fullmatch(source):
        return GitHubSkill(CATALOG_REPO, ref or "main", f"{CATALOG_PATH}/{source}")
    url = urlsplit(source)
    if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment):
        raise SkillError("仅支持公开仓库的 https://github.com/ 地址")
    parts = unquote(url.path).strip("/").split("/")
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in (".", "..") for p in parts[:2]):
        raise SkillError("GitHub 仓库地址无效")
    repository = "/".join(parts[:2]).removesuffix(".git")
    if len(parts) == 2:
        return GitHubSkill(repository, ref or "HEAD", "")
    if len(parts) < 4 or parts[2] not in ("tree", "blob"):
        raise SkillError("请使用 GitHub 技能目录的 /tree/ 地址或 SKILL.md 的 /blob/ 地址")
    tail = "/".join(parts[3:])
    if ref is not None:
        if tail != ref and not tail.startswith(ref + "/"):
            raise SkillError("地址中的版本与 ref 不一致")
        selected_ref, path = ref, tail[len(ref):].lstrip("/")
    else:
        selected_ref, _, path = tail.partition("/")
    if parts[2] == "blob":
        if not path.endswith("/SKILL.md") and path != "SKILL.md":
            raise SkillError("文件地址必须指向 SKILL.md")
        path = path.removesuffix("SKILL.md").rstrip("/")
    if path:
        _safe_parts(path)
    return GitHubSkill(repository, selected_ref, path)


def _safe_parts(value: str) -> tuple[str, ...]:
    parts = value.split("/")
    if (not value or len(value) > 1024 or value.startswith("/") or "\\" in value
            or any(p in ("", ".", "..") or p.rstrip(" .") != p or ":" in p
                   or re.fullmatch(r"(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", p)
                   or any(ord(c) < 32 for c in p) for p in parts)):
        raise SkillError("技能包包含不安全的文件路径")
    return tuple(parts)


async def _download(url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    # 地址只由已验证的仓库标识构造。禁止跟随重定向，避免跳往其他主机。
    session = await get_http_session()
    async with session.get(url, allow_redirects=False,
                           headers={"User-Agent": "agent-low-code-platform/skill-installer",
                                    "Accept": "application/vnd.github+json"},
                           timeout=aiohttp.ClientTimeout(total=45)) as response:
        if response.status != 200:
            if response.status == 404:
                raise SkillError("找不到公开仓库、版本或技能目录；请核对地址（含 / 的分支名需提供 ref）")
            if response.status in (403, 429):
                raise SkillError("GitHub 请求被限制，请稍后重试")
            raise SkillError(f"GitHub 下载失败（HTTP {response.status}）")
        if response.content_length is not None and response.content_length > limit:
            raise SkillError("GitHub 下载内容超过大小限制")
        data = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            data.extend(chunk)
            if len(data) > limit:
                raise SkillError("GitHub 下载内容超过大小限制")
        return bytes(data)


async def list_available(scope: SkillScope) -> list[dict]:
    root = installed_source(scope).root
    data = json.loads(await _download(f"https://api.github.com/repos/{CATALOG_REPO}/contents/{CATALOG_PATH}", 2 * 1024 * 1024))
    if not isinstance(data, list):
        raise SkillError("GitHub 技能目录格式无效")
    return [{"name": row["name"], "installed": (root / row["name"] / "SKILL.md").is_file(),
             "source": f"https://github.com/{CATALOG_REPO}/tree/main/{CATALOG_PATH}/{row['name']}"}
            for row in data if isinstance(row, dict) and row.get("type") == "dir"
            and isinstance(row.get("name"), str) and NAME.fullmatch(row["name"])]


def _publish(data: bytes, origin: GitHubSkill, commit: str, scope: SkillScope) -> dict:
    """校验并在同一文件系统中原子发布，失败或重复安装不覆盖已有技能。"""
    source = installed_source(scope)
    source.root.mkdir(parents=True, exist_ok=True)
    staging = installation_root() / ".staging"
    staging.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skill-", dir=staging) as temporary:
        package = Path(temporary) / "package"
        package.mkdir()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
                raise SkillError("仓库压缩包为空或条目过多")
            archive_root = _safe_parts(entries[0].filename.rstrip("/"))[0]
            prefix = (archive_root, *PurePosixPath(origin.path).parts) if origin.path else (archive_root,)
            files = []
            total = 0
            destinations = set()
            for entry in entries:
                parts = _safe_parts(entry.filename.rstrip("/"))
                if parts[0] != archive_root:
                    raise SkillError("仓库压缩包存在多个根目录")
                if parts[:len(prefix)] != prefix or len(parts) <= len(prefix):
                    continue
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise SkillError("技能包不允许符号链接或特殊文件")
                if entry.is_dir():
                    continue
                relative = parts[len(prefix):]
                key = "/".join(relative).casefold()
                if key in destinations:
                    raise SkillError("技能包包含重名文件")
                destinations.add(key)
                total += entry.file_size
                files.append((entry, relative))
                if total > MAX_PACKAGE_BYTES or len(files) > MAX_PACKAGE_FILES:
                    raise SkillError("技能包解压大小或文件数量超过限制")
            if not files:
                raise SkillError("该版本中找不到技能目录")
            for entry, relative in files:
                target = package.joinpath(*relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                # 不调用 extractall，也不保留可执行权限或执行 setup 脚本。
                with archive.open(entry) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
        instruction = package / "SKILL.md"
        if not instruction.is_file():
            raise SkillError("目录缺少 SKILL.md；请提供具体技能子目录，而非整个技能集合仓库")
        skill = _load(instruction, SkillSource("installed", package))
        _safe_parts(skill.name)
        if skill.name == "skill-installer":
            raise SkillError("skill-installer 是平台保留名称")
        destination = source.root / skill.name
        # os.rename 在目标非空时失败；先检查也覆盖重复调用的常见情况。
        if destination.exists():
            raise SkillError(f"技能已安装：installed:{skill.name}；本次未覆盖")
        provenance = {"repository": origin.repository, "path": origin.path, "ref": origin.ref, "commit": commit}
        (package / ".installation.json").write_text(json.dumps(provenance, ensure_ascii=False), encoding="utf-8")
        try:
            package.rename(destination)
        except OSError:
            if destination.exists():
                raise SkillError(f"技能已安装：installed:{skill.name}；本次未覆盖") from None
            raise
    allowed = scope.enabled_names is None or skill.name in scope.enabled_names or skill.key in scope.enabled_names
    return {"name": skill.name, "key": skill.key, "status": "installed", **provenance,
            "files": len(files), "visible": scope.enabled and allowed,
            "unavailable_reason": skill.unavailable_reason(scope),
            "message": "已安装到当前租户的当前智能体；目录将在下一步刷新。脚本依赖和 MCP 连接需另行配置。"}


async def install_skill(source: str, scope: SkillScope, ref: str | None = None) -> dict:
    installed_source(scope)
    origin = parse_source(source, ref)
    async with asyncio.timeout(INSTALL_TIMEOUT):
        commit_data = json.loads(await _download(
            f"https://api.github.com/repos/{origin.repository}/commits/{quote(origin.ref, safe='')}", 2 * 1024 * 1024))
        commit = commit_data.get("sha") if isinstance(commit_data, dict) else None
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SkillError("GitHub 返回的提交标识无效")
        data = await _download(f"https://codeload.github.com/{origin.repository}/zip/{commit}")
        # 发布只涉及有界本地文件操作，不在线程中留下取消后继续安装的后台任务。
        return _publish(data, origin, commit, scope)
