"""PostgreSQL Event Log persistence with exclusive session ownership.

append_events buffers new events; flush commits one ordered batch and rejects
conflicting sequence contents. Per-session locks serialize background and runtime
writes. write_owner holds a PostgreSQL advisory lock on a dedicated connection
through preparation, execution, and cleanup; process death releases ownership.
"""
import json
import logging
import hashlib
import threading
from contextlib import contextmanager

from backend.agents.runtime.session.events import SessionEvent, SessionHeader
from backend.agents.runtime.session.persistence.base import SessionPersistence
from backend.core.connection import get_conn

logger = logging.getLogger(__name__)


class PostgresSessionPersistence(SessionPersistence):
    """PostgreSQL 实现:create / append_events → pending / flush → durable / load / exists / list"""

    def __init__(self):
        # session_id → 未落库事件(按 seq 升序,append 顺序即到达顺序)
        self._pending: dict[str, list[SessionEvent]] = {}
        # session_id → 已确认落库的最大 seq(进程内游标;进程退出即弃,
        # DB 全量是持久真相,load 时按 DB 重建游标)
        self._written: dict[str, int] = {}
        self._guard = threading.RLock()
        self._locks: dict[str, threading.RLock] = {}
        self._leases: dict[str, object] = {}

    durable = True

    def reset_pending(self, session_id):
        with self._lock(session_id):
            self._pending.pop(session_id, None)

    def _lock(self, session_id):
        with self._guard:
            return self._locks.setdefault(session_id, threading.RLock())

    @staticmethod
    def _lock_key(session_id):
        return int.from_bytes(hashlib.blake2b(session_id.encode(), digest_size=8).digest(), "big", signed=True)

    @contextmanager
    def write_owner(self, session_id):
        """Advisory ownership held on a dedicated pooled connection until teardown."""
        from backend.agents.runtime.loop.registry import RunConflict
        with super().write_owner(session_id):
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (self._lock_key(session_id),))
                    if not cur.fetchone()["locked"]:
                        raise RunConflict(session_id)
                conn.commit()
                with self._lock(session_id):
                    self._leases[session_id] = conn
                try:
                    yield
                finally:
                    with self._lock(session_id):
                        self._leases.pop(session_id, None)
                        if not conn.closed:
                            conn.rollback()
                            with conn.cursor() as cur:
                                cur.execute("SELECT pg_advisory_unlock(%s)", (self._lock_key(session_id),))
                            conn.commit()

    def is_busy(self, session_id):
        if super().is_busy(session_id):
            return True
        with get_conn() as conn:
            with conn.cursor() as cur:
                key = self._lock_key(session_id)
                cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,))
                locked = cur.fetchone()["locked"]
                if locked:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
                return not locked

    # ── 写路径 ──

    def create(self, session_id: str, header: SessionHeader) -> None:
        """注册 Session 元信息。ON CONFLICT DO NOTHING:已存在的 header 不覆盖
        (同一 session_id 不应有第二个 header,防进程重启后重复 create 破坏首版)。"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO session_headers
                           (session_id, version, created_at, cwd, parent_session, seed_length, delegation_depth)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (session_id) DO NOTHING""",
                    (
                        session_id,
                        header.version,
                        header.created_at,
                        header.cwd,
                        header.parent_session,
                        header.seed_length,
                        header.delegation_depth,
                    ),
                )

    def append_events(self, session_id: str, events: list[SessionEvent]) -> None:
        """事件进入 pending 缓冲(不落盘)。按 seq 去重:跳过已落库(≤游标)与已入 pending 的。"""
        if not events:
            return
        with self._lock(session_id):
            base = self._written.get(session_id, 0)
            pending = self._pending.setdefault(session_id, [])
            seen = {e.seq: e for e in pending}
            for event in events:
                if event.seq <= base:
                    continue
                if event.seq in seen:
                    if seen[event.seq] != event:
                        raise ValueError(f"Conflicting pending session event: {session_id}/{event.seq}")
                    continue
                pending.append(event)
                seen[event.seq] = event

    def flush(self, session_id: str | None = None) -> None:
        """持久化边界:一次 flush 一个事务(session_id=None 时 flush 全部 pending)。

        相同序号且内容相同可重复提交；不同内容拒绝整批事务。
        失败保留 pending。恢复重新读取 durable 历史时丢弃未确认的缓冲。
        """
        with self._guard:
            targets = [session_id] if session_id is not None else list(self._pending)
        for sid in targets:
            with self._lock(sid):
                if not self._pending.get(sid):
                    if sid in self._leases:
                        conn = self._leases[sid]
                        with conn.cursor() as cur:
                            cur.execute("SELECT 1")
                        conn.commit()
                    continue
                if sid in self._leases:
                    self._flush_owned(sid)
                else:
                    with self.write_owner(sid):
                        self._flush_owned(sid)

    def _flush_owned(self, sid):
        events = self._pending.get(sid, [])
        conn = self._leases[sid]
        try:
            with conn.cursor() as cur:
                for event in sorted(events, key=lambda e: e.seq):
                    cur.execute(
                        """INSERT INTO session_events AS stored
                           (session_id, seq, event_type, event_time, data, source_event_seqs)
                           VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                           ON CONFLICT (session_id, seq) DO UPDATE SET seq = stored.seq
                           WHERE stored.event_type = EXCLUDED.event_type
                             AND stored.event_time = EXCLUDED.event_time
                             AND stored.data = EXCLUDED.data
                             AND stored.source_event_seqs IS NOT DISTINCT FROM EXCLUDED.source_event_seqs
                           RETURNING seq""",
                        (sid, event.seq, event.type, event.time,
                         json.dumps(event.data, ensure_ascii=False),
                         json.dumps(event.source_event_seqs) if event.source_event_seqs is not None else None),
                    )
                    if cur.fetchone() is None:
                        raise ValueError(f"Conflicting session event: {sid}/{event.seq}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        self._pending.pop(sid, None)
        self._written[sid] = max((e.seq for e in events), default=self._written.get(sid, 0))

    # ── 读路径(冷恢复 replay 源) ──

    def load(self, session_id: str) -> tuple[SessionHeader, list[SessionEvent]] | None:
        """读 durable 完整 Event Log(ORDER BY seq);无 header(或 header 已被删)返回 None。

        load 后把 DB 最大 seq 记为已写游标:恢复出的 Session 在内存继续 append → flush,
        只会写入该 Session 新产生的事件(旧事件已在 DB,无需重写)。
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM session_headers WHERE session_id = %s", (session_id,),
                )
                h = cur.fetchone()
                if h is None:
                    return None
                cur.execute(
                    "SELECT * FROM session_events WHERE session_id = %s ORDER BY seq", (session_id,),
                )
                rows = cur.fetchall()

        header = SessionHeader(
            id=h["session_id"],
            version=h["version"],
            created_at=h["created_at"],
            cwd=h["cwd"],
            parent_session=h["parent_session"],
            seed_length=h["seed_length"],
            delegation_depth=h["delegation_depth"],
        )
        events = [
            SessionEvent(
                type=r["event_type"],
                seq=r["seq"],
                time=r["event_time"],
                data=r["data"],  # psycopg2 自动反序列化 JSONB → dict
                source_event_seqs=r["source_event_seqs"],
            )
            for r in rows
        ]
        with self._lock(session_id):
            self._written[session_id] = events[-1].seq if events else 0
        logger.info(f"PostgresSessionPersistence load: session_id={session_id}, events={len(events)}")
        return header, events

    def exists(self, session_id: str) -> bool:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM session_headers WHERE session_id = %s", (session_id,),
                )
                return cur.fetchone() is not None

    def list(self) -> list[str]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT session_id FROM session_headers ORDER BY created_at DESC")
                return [r["session_id"] for r in cur.fetchall()]
