"""Workspace business operations, independent of FastAPI and frontend code."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from agent_platform_rpc_gateway import RpcError
from agent_platform_sandbox.errors import SandboxUnavailableError
from agent_platform_sandbox.workspace import (
    READ_ROOTS_ENV,
    WRITE_ROOTS_ENV,
    normalize_host_path,
    parse_roots,
    path_in_roots,
    resolve_workspace_member,
    resolve_workspace_root,
    session_workspace_path,
)
from agent_platform_session.events import (
    TITLE,
    USER_MESSAGE,
    SessionEvent,
    SessionHeader,
    new_session_id,
)
from agent_platform_session_title import (
    fallback_session_title,
    session_title_of,
    title_message_of,
)

from .models import (
    CreatedWorkspaceSession,
    WorkspaceFileEntry,
    WorkspaceProject,
    WorkspaceSession,
)

logger = logging.getLogger(__name__)

MAX_LIST_ENTRIES = 2000
MAX_SESSIONS = 100
_SESSION_SCAN_LIMIT = 1000
_BACKEND_WRITE_MOUNT_BASE = "/srv/host-write"
_BACKEND_READ_MOUNT_BASE = "/srv/host-read"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _canonical_project_path(cwd: str) -> str:
    """项目路径的规范化字符串；保留根（``C:/`` 不能变成 ``C:``）。"""
    raw = cwd.strip().replace("\\", "/")
    prefix = ""
    if len(raw) >= 2 and raw[1] == ":":
        prefix, raw = raw[:2].upper(), raw[2:]
    elif raw.startswith("//"):
        prefix, raw = "//", raw[2:]
    segments: list[str] = []
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return prefix + "/" + "/".join(segments)


def _project_label(canonical: str) -> str:
    """项目显示名 = 最后一段；根目录没有末段时回落成整串。"""
    _, _, rest = canonical.partition("/")
    segments = [segment for segment in rest.split("/") if segment]
    return segments[-1] if segments else canonical


def _project_payload(row: dict) -> WorkspaceProject:
    canonical = row["canonical_path"]
    return WorkspaceProject(
        id=row["id"],
        key=canonical,
        label=row.get("title") or _project_label(canonical),
        path=canonical,
        sort_order=float(row.get("sort_order") or 0),
    )


def _event_of_row(row: dict) -> SessionEvent:
    return SessionEvent(
        type=row["event_type"],
        seq=row["seq"],
        time=row["event_time"],
        data=row["data"],
    )


def _agent_key_from_channel(channel: str | None) -> str | None:
    if channel and channel.startswith("agent:"):
        return channel.split(":", 1)[1] or None
    return None


@dataclass(frozen=True)
class _BrowseRoot:
    name: str
    host: str
    container: Path
    writable: bool


def _write_roots() -> tuple[str, ...]:
    return parse_roots(os.environ.get(WRITE_ROOTS_ENV))


def _read_roots() -> tuple[str, ...]:
    return parse_roots(os.environ.get(READ_ROOTS_ENV))


def _local_backend() -> bool:
    return os.environ.get("SANDBOX_BACKEND", "local").strip().lower() == "local"


def _is_read_only_mount(path: Path) -> bool:
    """Best-effort mount-flag check for the backend's read-only roots."""
    if os.name != "posix":
        return False
    try:
        resolved = str(path.resolve())
        best = ""
        read_only = False
        with open("/proc/self/mounts", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if len(parts) < 4:
                    continue
                mount_point = parts[1]
                if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
                    if len(mount_point) >= len(best):
                        best = mount_point
                        read_only = "ro" in parts[3].split(",")
        return read_only
    except OSError:
        return False


def _backend_visible(host_root: str) -> Path:
    name = host_root.rstrip("/").rsplit("/", 1)[-1]
    return Path(_BACKEND_WRITE_MOUNT_BASE) / name


def _browse_roots() -> list[_BrowseRoot]:
    out: list[_BrowseRoot] = []
    seen: set[str] = set()
    for raw in _write_roots():
        host = normalize_host_path(raw)
        name = host.rstrip("/").rsplit("/", 1)[-1]
        if name in seen:
            continue
        seen.add(name)
        out.append(_BrowseRoot(name, host, _backend_visible(host), True))
    for raw in _read_roots():
        host = normalize_host_path(raw)
        name = host.rstrip("/").rsplit("/", 1)[-1]
        if name in seen:
            continue
        container = Path(_BACKEND_READ_MOUNT_BASE) / name
        if not container.is_dir():
            continue
        seen.add(name)
        out.append(_BrowseRoot(name, host, container, False))
    return out


def _folder_value(host_path: str, roots: list[_BrowseRoot]) -> str | None:
    path = normalize_host_path(host_path)
    for root in roots:
        base = normalize_host_path(root.host).rstrip("/")
        if path == base or path == base + "/":
            return root.name
        if path.startswith(base + "/"):
            return f"{root.name}/{path[len(base) + 1:]}"
    return None


def _is_writable(host_path: str, write_roots: tuple[str, ...]) -> bool:
    return path_in_roots(host_path, write_roots)


def _host_cwd_to_backend(roots: list[_BrowseRoot], cwd: str) -> Path | None:
    if not cwd or not roots:
        return None
    norm = normalize_host_path(cwd)
    for root in roots:
        base = normalize_host_path(root.host).rstrip("/")
        if norm == base or norm == base + "/":
            return root.container
        if norm.startswith(base + "/"):
            rest = norm[len(base) + 1:]
            if ".." in PurePosixPath(rest).parts:
                return None
            return root.container / rest
    return None


def _visible_host_dir(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        raise RpcError("workspace/invalid-path", "path 不能为空")
    try:
        host = normalize_host_path(text)
    except ValueError as exc:
        raise RpcError("workspace/invalid-path", f"path 必须是全限定绝对路径: {exc}") from None
    if _local_backend():
        if not Path(host).is_dir():
            raise RpcError("workspace/invalid-path", f"目录不存在或不是目录: {host}")
        return host
    visible = _host_cwd_to_backend(_browse_roots(), host)
    if visible is None or not visible.is_dir():
        raise RpcError("workspace/invalid-path", f"path 不在任何可浏览的根内: {host}")
    return host


def _validate_project_title(raw: object) -> str:
    title = str(raw or "").strip()
    if not title:
        raise RpcError("workspace/invalid-title", "项目名称不能为空")
    if len(title.encode("utf-8")) > 200:
        raise RpcError("workspace/invalid-title", "项目名称过长")
    return title


def _local_project_path(raw: str) -> Path:
    if not _local_backend():
        raise RpcError("workspace/unsupported", "绝对路径项目只在本地后端可用")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RpcError("workspace/invalid-path", f"项目路径必须是绝对路径: {raw!r}")
    path = path.resolve()
    if path == Path(path.anchor):
        raise RpcError("workspace/invalid-path", "不能把磁盘根目录作为项目")
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RpcError("workspace/invalid-path", f"无法创建项目目录: {exc}") from None
    if not path.is_dir():
        raise RpcError("workspace/invalid-path", f"项目路径不是目录: {path}")
    return path


class WorkspaceService:
    """Per-runtime workspace operations with explicit collaborators."""

    def __init__(self, database, persistence, title) -> None:
        self._database = database
        self._persistence = persistence
        self._title = title

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # ── sessions ──

    def _titles_for(self, session_ids: list[str]) -> dict[str, dict]:
        if not session_ids:
            return {}
        found: dict[str, dict] = {}
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT ON (session_id)
                              session_id, seq, event_type, event_time, data
                       FROM session_events
                       WHERE session_id = ANY(%s) AND event_type = %s
                       ORDER BY session_id, seq DESC""",
                    (session_ids, TITLE),
                )
                for row in cur.fetchall():
                    title = session_title_of(_event_of_row(row))
                    if title is not None:
                        found[row["session_id"]] = {
                            "title": title.title, "source": title.source,
                        }
                pending = [sid for sid in session_ids if sid not in found]
                if pending:
                    cur.execute(
                        """SELECT DISTINCT ON (session_id)
                                  session_id, seq, event_type, event_time, data
                           FROM session_events
                           WHERE session_id = ANY(%s) AND event_type = %s
                           ORDER BY session_id, seq""",
                        (pending, USER_MESSAGE),
                    )
                    for row in cur.fetchall():
                        message = title_message_of(_event_of_row(row))
                        if message is None:
                            continue
                        fallback = fallback_session_title(message.text)
                        if fallback:
                            found[row["session_id"]] = {
                                "title": fallback, "source": "fallback",
                            }
        return found

    def _agent_names(self) -> dict[str, str]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT agent_key, name FROM agent_definitions")
                return {row["agent_key"]: row["name"] for row in cur.fetchall() if row["name"]}

    def _ledger_for(self, tenant_id: int, session_ids: list[str]) -> dict[str, dict]:
        if not session_ids:
            return {}
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT wps.session_id, wp.id, wp.canonical_path, wp.title, wp.sort_order
                       FROM workspace_project_sessions wps
                       JOIN workspace_projects wp ON wp.id = wps.project_id
                       WHERE wp.tenant_id = %s AND wps.session_id = ANY(%s)""",
                    (tenant_id, session_ids),
                )
                return {row["session_id"]: row for row in cur.fetchall()}

    def _workspace_for(self, cwd: str | None, session_id: str, deployment_root: Path) -> Path | None:
        if cwd:
            if _local_backend():
                try:
                    local = Path(cwd).expanduser().resolve()
                except (OSError, RuntimeError):
                    local = None
                if local is not None and local.is_dir():
                    return local
            backend_ws = _host_cwd_to_backend(_browse_roots(), cwd)
            if backend_ws is not None:
                return backend_ws
            try:
                workspace = Path(cwd).resolve()
            except (OSError, RuntimeError):
                return None
            if not workspace.is_relative_to(deployment_root) or workspace == deployment_root:
                return None
            return workspace
        try:
            return session_workspace_path(str(deployment_root), session_id)
        except ValueError:
            return None

    def _project_for(
        self, session_id: str, cwd: str | None, ws: Path | None, ledger: dict[str, dict],
    ) -> WorkspaceProject | None:
        if not cwd:
            return None
        row = ledger.get(session_id)
        if row is None or ws is None or not ws.is_dir():
            return None
        if _canonical_project_path(cwd) != row["canonical_path"]:
            return None
        return _project_payload(row)

    def _list_sessions_sync(self, tenant_id: int) -> tuple[list[WorkspaceSession], bool]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM (
                           SELECT DISTINCT ON (sh.session_id)
                                  sh.session_id, sh.cwd, sh.updated_at,
                                  c.customer_name, c.channel, c.id AS conversation_id
                           FROM session_headers sh
                           JOIN conversations c
                             ON c.session_id = sh.session_id AND c.tenant_id = %s
                           ORDER BY sh.session_id, c.id DESC
                       ) t ORDER BY t.updated_at DESC NULLS LAST
                       LIMIT %s""",
                    (tenant_id, _SESSION_SCAN_LIMIT),
                )
                rows = cur.fetchall()
        try:
            deployment_root = Path(resolve_workspace_root()).resolve()
        except (SandboxUnavailableError, ValueError) as exc:
            raise RpcError("workspace/unavailable", f"沙箱工作区未配置: {exc}") from None
        scanned = len(rows)
        rows = rows[:MAX_SESSIONS]
        session_ids = [row["session_id"] for row in rows]
        titles = self._titles_for(session_ids)
        ledger = self._ledger_for(tenant_id, session_ids)
        agent_names = self._agent_names()
        items: list[WorkspaceSession] = []
        for row in rows:
            agent_key = _agent_key_from_channel(row["channel"])
            workspace = self._workspace_for(row["cwd"], row["session_id"], deployment_root)
            try:
                entries = len(os.listdir(workspace)) if workspace is not None else 0
            except OSError:
                entries = 0
            label = row["customer_name"] or row["channel"] or row["session_id"][:8]
            hit = titles.get(row["session_id"])
            items.append(WorkspaceSession(
                session_id=row["session_id"],
                agent_key=agent_key,
                agent_name=agent_names.get(agent_key or "") or agent_key,
                conversation_id=row["conversation_id"],
                title=hit["title"] if hit else label,
                title_source=hit["source"] if hit else None,
                project=self._project_for(row["session_id"], row["cwd"], workspace, ledger),
                label=label,
                channel=row["channel"],
                updated_at=_iso(row["updated_at"].timestamp()) if row["updated_at"] else None,
                entries=entries,
            ))
        return items, scanned >= _SESSION_SCAN_LIMIT or scanned > MAX_SESSIONS

    async def list_sessions(self, tenant_id: int):
        return await self._run(self._list_sessions_sync, tenant_id)

    # ── projects ──

    def _list_projects_sync(self, tenant_id: int) -> list[WorkspaceProject]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT wp.id, wp.canonical_path, wp.title, wp.sort_order
                       FROM workspace_projects wp
                       WHERE wp.tenant_id = %s
                       ORDER BY wp.sort_order, wp.id""",
                    (tenant_id,),
                )
                return [_project_payload(row) for row in cur.fetchall()]

    async def list_projects(self, tenant_id: int):
        return await self._run(self._list_projects_sync, tenant_id)

    def _ensure_project(self, cur, tenant_id: int, canonical: str, title: str | None = None) -> int:
        cur.execute(
            """INSERT INTO workspace_projects (tenant_id, canonical_path, title, sort_order)
               VALUES (%s, %s, %s,
                       (SELECT COALESCE(MAX(sort_order), 0) + 10
                        FROM workspace_projects WHERE tenant_id = %s))
               ON CONFLICT (tenant_id, canonical_path) DO NOTHING
               RETURNING id""",
            (tenant_id, canonical, title or _project_label(canonical), tenant_id),
        )
        row = cur.fetchone()
        if row is not None:
            return row["id"]
        cur.execute(
            "SELECT id FROM workspace_projects WHERE tenant_id = %s AND canonical_path = %s",
            (tenant_id, canonical),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RpcError("workspace/internal", "项目登记失败")
        return existing["id"]

    def _create_project_sync(self, tenant_id: int, path: str, title: str | None):
        host = _visible_host_dir(path)
        canonical = _canonical_project_path(host)
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, canonical_path, title, sort_order FROM workspace_projects
                       WHERE tenant_id = %s AND canonical_path = %s""",
                    (tenant_id, canonical),
                )
                row = cur.fetchone()
                created = row is None
                if row is None:
                    project_id = self._ensure_project(cur, tenant_id, canonical, title)
                    cur.execute(
                        "SELECT id, canonical_path, title, sort_order FROM workspace_projects WHERE id = %s",
                        (project_id,),
                    )
                    row = cur.fetchone()
        return created, _project_payload(row)

    async def create_project(self, tenant_id: int, path: str, title: str | None):
        if title is not None:
            title = _validate_project_title(title)
        return await self._run(self._create_project_sync, tenant_id, path, title)

    def _update_project_sync(self, tenant_id: int, project_id: int, title: str | None, sort_order: float | None):
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            sets.append("title = %s")
            params.append(_validate_project_title(title))
        if sort_order is not None:
            sets.append("sort_order = %s")
            params.append(float(sort_order))
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM workspace_projects WHERE id = %s AND tenant_id = %s",
                    (project_id, tenant_id),
                )
                if cur.fetchone() is None:
                    raise RpcError("workspace/not-found", f"项目不存在: {project_id}")
                cur.execute(
                    f"""UPDATE workspace_projects SET {', '.join(sets)}, updated_at = now()
                        WHERE id = %s
                        RETURNING id, canonical_path, title, sort_order""",
                    (*params, project_id),
                )
                return _project_payload(cur.fetchone())

    async def update_project(self, tenant_id: int, project_id: int, title: str | None, sort_order: float | None):
        if title is None and sort_order is None:
            raise RpcError("workspace/invalid-request", "至少要给 title 或 sort_order")
        return await self._run(self._update_project_sync, tenant_id, project_id, title, sort_order)

    def _delete_project_sync(self, tenant_id: int, project_id: int) -> str:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM workspace_projects
                       WHERE id = %s AND tenant_id = %s
                       RETURNING canonical_path""",
                    (project_id, tenant_id),
                )
                row = cur.fetchone()
        if row is None:
            raise RpcError("workspace/not-found", f"项目不存在: {project_id}")
        return row["canonical_path"]

    async def delete_project(self, tenant_id: int, project_id: int):
        return await self._run(self._delete_project_sync, tenant_id, project_id)

    # ── folder / session creation ──

    def _validate_new_name(self, raw: str | None) -> str:
        name = (raw or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
            raise RpcError("workspace/invalid-name", "文件夹名不合法")
        return name

    def _ensure_folder_sync(self, raw_name: str) -> dict:
        name = self._validate_new_name(raw_name)
        roots = _browse_roots()
        if roots:
            errors: list[str] = []
            local = _local_backend()
            for root in sorted(roots, key=lambda item: not item.writable):
                base = Path(root.host) if local else root.container
                try:
                    target = resolve_workspace_member(str(base), name)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                if target.exists() and not target.is_dir():
                    raise RpcError("workspace/name-conflict", f"同名文件已存在: {name}")
                try:
                    target.mkdir(exist_ok=True)
                except OSError as exc:
                    errors.append(f"{root.host}: {exc}")
                    continue
                host_path = root.host.rstrip("/") + "/" + name
                return {
                    "path": str(target),
                    "host_path": host_path,
                    "folder": _folder_value(host_path, roots) or name,
                    "writable": _is_writable(host_path, _write_roots()),
                }
            raise RpcError("workspace/invalid-path", "无法创建工作区文件夹: " + "；".join(errors))
        try:
            deployment_root = Path(resolve_workspace_root()).resolve()
        except (SandboxUnavailableError, ValueError) as exc:
            raise RpcError("workspace/unavailable", f"沙箱工作区未配置: {exc}") from None
        try:
            target = resolve_workspace_member(str(deployment_root), name)
        except ValueError as exc:
            raise RpcError("workspace/invalid-path", str(exc)) from None
        if target.exists() and not target.is_dir():
            raise RpcError("workspace/name-conflict", f"同名文件已存在: {name}")
        try:
            target.mkdir(exist_ok=True)
        except OSError as exc:
            raise RpcError("workspace/invalid-path", f"无法创建工作区文件夹: {exc}") from None
        return {"path": str(target), "host_path": str(target), "folder": name, "writable": True}

    async def ensure_folder(self, raw_name: str):
        return await self._run(self._ensure_folder_sync, raw_name)

    def _create_session_sync(
        self, tenant_id: int, agent_key: str, folder: str, folder_path: str,
    ) -> CreatedWorkspaceSession:
        agent_key = (agent_key or "").strip()
        if not agent_key:
            raise RpcError("workspace/invalid-request", "agent_key 不能为空")
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM agent_definitions WHERE agent_key = %s",
                    (agent_key,),
                )
                row = cur.fetchone()
        if row is None:
            raise RpcError("agent/not-found", f"Agent 不存在: {agent_key}")
        agent_name = row["name"] or agent_key
        folder = (folder or "").strip()
        folder_path = (folder_path or "").strip()
        cwd: str | None = None
        if folder_path:
            cwd = str(_local_project_path(folder_path))
        elif folder:
            roots = _browse_roots()
            if roots:
                name, _, rest = folder.partition("/")
                root = next((item for item in roots if item.name == name), None)
                if root is None:
                    raise RpcError("workspace/invalid-path", f"浏览根不存在: {name!r}")
                try:
                    target = resolve_workspace_member(str(root.container), rest)
                except ValueError as exc:
                    raise RpcError("workspace/invalid-path", str(exc)) from None
                if root.writable:
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    except OSError as exc:
                        raise RpcError("workspace/invalid-path", f"无法创建工作区文件夹: {exc}") from None
                elif not target.is_dir():
                    raise RpcError("workspace/invalid-path", "只读位置没有这个目录，无法作为工作区")
                cwd = root.host if not rest else root.host.rstrip("/") + "/" + rest
            else:
                try:
                    root = Path(resolve_workspace_root()).resolve()
                except (SandboxUnavailableError, ValueError) as exc:
                    raise RpcError("workspace/unavailable", f"沙箱工作区未配置: {exc}") from None
                try:
                    target = resolve_workspace_member(str(root), folder)
                except ValueError as exc:
                    raise RpcError("workspace/invalid-path", str(exc)) from None
                if target == root:
                    raise RpcError("workspace/invalid-path", "不能直接把部署根作为工作区文件夹")
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise RpcError("workspace/invalid-path", f"无法创建工作区文件夹: {exc}") from None
                cwd = str(target)

        label = (Path(cwd).name if cwd else "") or (folder.rsplit("/", 1)[-1] if folder else "") or "新会话"
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO conversations (tenant_id, channel, customer_name, agent_key)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (tenant_id, f"agent:{agent_key}", label, agent_key),
                )
                conversation_id = cur.fetchone()["id"]

        session_id = new_session_id()
        header = SessionHeader(version=1, id=session_id, created_at=__import__("time").time(), seed_length=0)
        header.cwd = cwd
        self._persistence.create(session_id, header)
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE conversations SET session_id = %s, updated_at = now() WHERE tenant_id = %s AND id = %s",
                    (session_id, tenant_id, conversation_id),
                )
        if cwd:
            try:
                canonical = _canonical_project_path(cwd)
                with self._database.get_conn() as conn:
                    with conn.cursor() as cur:
                        project_id = self._ensure_project(cur, tenant_id, canonical)
                        cur.execute(
                            """INSERT INTO workspace_project_sessions (project_id, session_id, position)
                               VALUES (%s, %s,
                                       (SELECT COALESCE(MAX(position), 0) + 10
                                        FROM workspace_project_sessions WHERE project_id = %s))
                               ON CONFLICT (project_id, session_id) DO NOTHING""",
                            (project_id, session_id, project_id),
                        )
            except Exception as exc:  # noqa: BLE001 — grouping is secondary to a created session
                logger.warning("会话 %s 的项目登记失败: %s", session_id, exc)
        return CreatedWorkspaceSession(
            session_id=session_id,
            conversation_id=conversation_id,
            agent_key=agent_key,
            agent_name=agent_name,
            label=label,
            folder=folder or folder_path or None,
        )

    async def create_session(
        self, tenant_id: int, agent_key: str, folder: str | None, folder_path: str | None,
    ):
        return await self._run(
            self._create_session_sync, tenant_id, agent_key, folder or "", folder_path or ""
        )

    # ── rename ──

    def _assert_session_visible(self, session_id: str, tenant_id: int) -> None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT 1 FROM session_headers sh
                       WHERE sh.session_id = %s
                         AND EXISTS (SELECT 1 FROM conversations c
                                     WHERE c.session_id = sh.session_id AND c.tenant_id = %s)""",
                    (session_id, tenant_id),
                )
                if cur.fetchone() is None:
                    raise RpcError("session/not-found", f"会话不存在或不属于本租户: {session_id}")

    async def rename_session(self, tenant_id: int, session_id: str, title: str):
        title = (title or "").strip()
        if not title:
            raise RpcError("session/invalid-title", "标题不能为空")
        await self._run(self._assert_session_visible, session_id, tenant_id)
        try:
            snapshot = self._title.rename_by_id(session_id, title)
        except LookupError:
            raise RpcError("session/not-found", f"会话不存在: {session_id}") from None
        except ValueError as exc:
            raise RpcError("session/invalid-title", str(exc)) from None
        return snapshot

    # ── files ──

    def _session_workspace_root(self, session_id: str, tenant_id: int) -> Path:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT sh.cwd FROM session_headers sh
                       WHERE sh.session_id = %s
                         AND EXISTS (SELECT 1 FROM conversations c
                                     WHERE c.session_id = sh.session_id AND c.tenant_id = %s)""",
                    (session_id, tenant_id),
                )
                row = cur.fetchone()
        if row is None:
            raise RpcError("session/not-found", f"会话不存在或不属于本租户: {session_id}")
        try:
            deployment_root = Path(resolve_workspace_root()).resolve()
        except (SandboxUnavailableError, ValueError) as exc:
            raise RpcError("workspace/unavailable", f"沙箱工作区未配置: {exc}") from None
        workspace = self._workspace_for(row["cwd"], session_id, deployment_root)
        if workspace is None:
            raise RpcError("workspace/not-found", "会话工作区不可用")
        return workspace

    @staticmethod
    def _entry(root: Path, path: Path) -> WorkspaceFileEntry:
        try:
            stat = path.lstat()
            is_link = path.is_symlink()
            outside = False
            if is_link:
                try:
                    outside = not path.resolve().is_relative_to(root.resolve())
                except (OSError, RuntimeError):
                    outside = True
            is_dir = path.is_dir() and not outside
            return WorkspaceFileEntry(
                name=path.name,
                is_dir=is_dir,
                size=0 if is_dir else stat.st_size,
                mtime=_iso(stat.st_mtime),
                is_link=is_link,
                outside=outside,
            )
        except OSError as exc:
            raise RpcError("workspace/not-found", f"无法读取条目: {exc}") from None

    def _list_files_sync(self, session_id: str, tenant_id: int, path: str):
        root = self._session_workspace_root(session_id, tenant_id)
        if not root.is_dir():
            raise RpcError("workspace/not-found", "会话工作区不存在")
        try:
            target = resolve_workspace_member(str(root), path or ".")
        except ValueError as exc:
            raise RpcError("workspace/invalid-path", str(exc)) from None
        if not target.is_dir():
            raise RpcError("workspace/not-found", f"目录不存在: {path}")
        entries: list[WorkspaceFileEntry] = []
        truncated = False
        try:
            with os.scandir(target) as iterator:
                for index, item in enumerate(iterator):
                    if index >= MAX_LIST_ENTRIES:
                        truncated = True
                        break
                    entries.append(self._entry(root, Path(item.path)))
        except OSError as exc:
            raise RpcError("workspace/invalid-path", f"无法读取目录: {exc}") from None
        entries.sort(key=lambda entry: (not entry.is_dir, entry.name.lower()))
        return entries, truncated, not _is_read_only_mount(root)

    async def list_files(self, tenant_id: int, session_id: str, path: str):
        return await self._run(self._list_files_sync, session_id, tenant_id, path)

    def _create_file_sync(self, session_id: str, tenant_id: int, path: str, name: str, kind: str):
        root = self._session_workspace_root(session_id, tenant_id)
        try:
            parent = resolve_workspace_member(str(root), path or ".")
        except ValueError as exc:
            raise RpcError("workspace/invalid-path", str(exc)) from None
        if not parent.is_dir():
            raise RpcError("workspace/not-found", f"目录不存在: {path}")
        name = name.strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
            raise RpcError("workspace/invalid-name", "名称不合法")
        target = parent / name
        try:
            if kind == "dir":
                target.mkdir(exist_ok=False)
            else:
                with open(target, "xb"):
                    pass
        except FileExistsError:
            raise RpcError("workspace/name-conflict", f"条目已存在: {name}") from None
        except OSError as exc:
            raise RpcError("workspace/invalid-path", f"无法创建条目: {exc}") from None
        return self._entry(root, target)

    async def create_file(self, tenant_id: int, session_id: str, path: str, name: str, kind: str):
        return await self._run(self._create_file_sync, session_id, tenant_id, path, name, kind)
