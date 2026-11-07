"""Xianyu connection lifecycle, persistence and subscriber fan-out."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_platform_chat import MessageCreate

from .live import XianyuLive

logger = logging.getLogger(__name__)


def _default_cookie_file() -> Path:
    explicit = os.environ.get("XIANYU_COOKIE_FILE")
    if explicit:
        return Path(explicit)
    if os.path.exists("/app"):
        return Path("/app/xianyu_cookie.json")
    return Path.cwd() / "xianyu_cookie.json"


class XianyuManager:
    """One connection manager per plugin runtime."""

    def __init__(
        self,
        store: Any,
        *,
        cookie_file: str | Path | None = None,
        tenant_id: int | None = None,
    ) -> None:
        self._store = store
        self._cookie_file = Path(cookie_file) if cookie_file else _default_cookie_file()
        self._tenant_id = tenant_id if tenant_id is not None else int(os.getenv("XIANYU_TENANT_ID", "1"))
        self._live: XianyuLive | None = None
        self._task: asyncio.Task | None = None
        self._connected_at: datetime | None = None
        self._subscribers: list[Any] = []

    # ── subscribers ──

    def subscribe(self, callback: Any) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Any) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    # ── cookie persistence ──

    @staticmethod
    def _h5tk(cookie: str) -> str:
        for part in cookie.split("; "):
            if part.startswith("_m_h5_tk="):
                return part.split("=", 1)[1].split("_")[0]
        return ""

    def _cookie_changed(self, new_cookie: str) -> bool:
        old = self.get_saved_cookie()
        return bool(old) and self._h5tk(old) != self._h5tk(new_cookie)

    def get_saved_cookie(self) -> str:
        try:
            if self._cookie_file.exists():
                return json.loads(self._cookie_file.read_text("utf-8")).get("cookie", "")
        except Exception:  # noqa: BLE001
            pass
        return ""

    def get_cached_token(self) -> tuple[str, str]:
        try:
            if self._cookie_file.exists():
                data = json.loads(self._cookie_file.read_text("utf-8"))
                return data.get("token", ""), data.get("device_id", "")
        except Exception:  # noqa: BLE001
            pass
        return "", ""

    def save_cookie(self, cookie: str, token: str = "", device_id: str = "") -> None:
        self._cookie_file.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if self._cookie_file.exists():
            try:
                existing = json.loads(self._cookie_file.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                pass
        existing["cookie"] = cookie
        if token:
            existing["token"] = token
        if device_id:
            existing["device_id"] = device_id
        self._cookie_file.write_text(
            json.dumps(existing, ensure_ascii=False), "utf-8",
        )

    # ── message/query views ──

    async def _on_message(self, msg: dict) -> None:
        cid = msg["cid"]
        if not cid:
            return
        msg["time"] = datetime.now(timezone.utc).isoformat()
        try:
            conv = self._store.get_or_create_conversation(
                self._tenant_id, "xianyu", cid,
                customer_name=msg.get("sender_name", ""),
                customer_id=msg.get("sender_id", ""),
            )
            self._store.create_message(
                self._tenant_id, conv.id,
                MessageCreate(
                    role="customer",
                    sender_name=msg.get("sender_name", ""),
                    content=msg.get("content", ""),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("写入消息到数据库失败: %s", exc)

        logger.info(
            "[闲鱼消息] cid=%s %s: %s",
            cid, msg["sender_name"], msg["content"][:80],
        )
        for callback in self._subscribers:
            try:
                await callback(msg)
            except Exception:  # noqa: BLE001
                pass

    def get_status(self) -> dict:
        return {
            "is_online": self._live is not None and self._task is not None and not self._task.done(),
            "connected_at": self._connected_at.isoformat() if self._connected_at else None,
        }

    def get_conversations(self) -> list[dict]:
        try:
            rows = self._store.list_conversations_with_summary(
                self._tenant_id, channel="xianyu", page_size=200,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("从数据库读取会话列表失败: %s", exc)
            return []

        return [
            {
                "id": row["id"],
                "cid": row["channel_conversation_id"] or "",
                "buyer_name": row["customer_name"] or "",
                "last_msg": (row["last_msg"] or "")[:50],
                "last_time": row["last_time"].isoformat() if row["last_time"] else "",
                "count": row["msg_count"] or 0,
            }
            for row in rows
        ]

    def get_messages(self, cid: str) -> list[dict]:
        try:
            messages = self._store.get_messages_by_channel_cid(
                self._tenant_id, cid, page_size=500,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("从数据库读取消息失败: %s", exc)
            return []
        return [
            {
                "cid": cid,
                "sender_id": message.sender_name or "",
                "sender_name": message.sender_name or "",
                "content": message.content,
                "time": message.created_at.isoformat(),
            }
            for message in messages
        ]

    async def fetch_history(self, cid: str) -> int:
        if not self._live:
            raise RuntimeError("未连接闲鱼")
        history = await self._live.list_all_conversations(cid)
        try:
            conv = self._store.get_or_create_conversation(
                self._tenant_id, "xianyu", cid,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("查找会话失败: %s", exc)
            return 0

        inserted = 0
        for msg in history:
            try:
                self._store.insert_message_raw(
                    self._tenant_id, conv.id,
                    role="customer",
                    sender_name=msg.get("sender_name", ""),
                    content=msg.get("content", ""),
                )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("写入历史消息失败: %s", exc)
        return inserted

    # ── lifecycle ──

    async def connect(self, cookie: str) -> str | None:
        if self._live and self._task and not self._task.done():
            raise RuntimeError("已连接，请先断开")

        cached_token, cached_device_id = self.get_cached_token()
        if cached_token and self._cookie_changed(cookie):
            logger.warning("Cookie 已变更，清除旧 token")
            cached_token = ""
        self.save_cookie(cookie, token=cached_token, device_id=cached_device_id)

        async def on_registered() -> None:
            logger.warning("[on_ready] IM 注册完成，开始拉取会话")
            await self._fetch_conversations()

        self._live = XianyuLive(
            cookie, on_message=self._on_message,
            cached_token=cached_token, cached_device_id=cached_device_id,
            on_ready=on_registered,
        )
        self._task = asyncio.create_task(self._live.main())
        self._connected_at = datetime.now(timezone.utc)

        error = await self._live.wait_ready(timeout=300)
        if error:
            await self.disconnect()
            return error

        token = self._live.xianyu._cached_token
        if token:
            self.save_cookie(cookie, token=token, device_id=self._live.device_id)
        logger.info("闲鱼连接已启动，等待 IM 注册完成后拉取会话")
        return None

    async def _fetch_conversations(self) -> None:
        logger.warning("[拉会话] _fetch_conversations 已启动")
        try:
            conversations = await self._live.list_newest_conversations()
            logger.warning("[拉会话] list_newest_conversations 返回 %s 条", len(conversations))
            for index, conversation in enumerate(conversations):
                cid = conversation["cid"]
                if not cid:
                    continue
                try:
                    self._store.get_or_create_conversation(
                        self._tenant_id, "xianyu", cid,
                        customer_name=conversation.get("buyer_name", ""),
                        customer_id=conversation.get("buyer_id", ""),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[拉会话] 创建会话失败 cid=%s: %s", cid, exc)
                    continue

                if index > 0:
                    await asyncio.sleep(1.5)
                try:
                    history = await self._live.list_all_conversations(cid)
                    if history:
                        conv = self._store.get_or_create_conversation(
                            self._tenant_id, "xianyu", cid,
                        )
                        for msg in history:
                            try:
                                self._store.insert_message_raw(
                                    self._tenant_id, conv.id,
                                    role="customer",
                                    sender_name=msg.get("sender_name", ""),
                                    content=msg.get("content", ""),
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        logger.warning("[拉历史] cid=%s 写入 %s 条消息到数据库", cid, len(history))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[拉历史] cid=%s 失败: %s", cid, exc)
            logger.info("会话列表已同步到数据库，共 %s 个会话", len(conversations))
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取会话列表失败: %s", exc)

    async def disconnect(self) -> None:
        if not self._live:
            return
        self._live.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._live = None
        self._task = None
        self._connected_at = None
        logger.info("闲鱼连接已断开")

    async def aclose(self) -> None:
        await self.disconnect()
        self._subscribers.clear()
