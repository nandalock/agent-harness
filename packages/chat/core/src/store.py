import json
from typing import Optional

from agent_platform_agent_runtime.context import CONTINUE_TASK

from .history import hydrate_message_window
from .models import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)



class ChatStore:
    def __init__(self, database, sessions, persistence):
        self._database = database
        self._sessions = sessions
        self._persistence = persistence

    def message_window(self, tenant_id: int, conversation_id: int, *, before_id: int | None, size: int) -> dict | None:
        conversation = self.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            return None
        window = self.list_message_window(tenant_id, conversation_id, before_id=before_id, size=size)
        return hydrate_message_window(window, conversation.session_id, self._sessions, self._persistence)

    def list_conversations_with_summary(
        self,    tenant_id: int,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                params = [tenant_id]
                sql = """
                    SELECT c.*,
                           (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_msg,
                           (SELECT created_at FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) as last_time,
                           (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) as msg_count
                    FROM conversations c
                    WHERE c.tenant_id = %s
                """
                if channel:
                    params.append(channel)
                    sql += " AND c.channel = %s"
                if status:
                    params.append(status)
                    sql += " AND c.status = %s"
                sql += " ORDER BY c.updated_at DESC"
                sql += f" OFFSET {(page - 1) * page_size} LIMIT {page_size}"
                cur.execute(sql, params)
                return cur.fetchall()


    def get_messages_by_channel_cid(
        self,    tenant_id: int,
        channel_conversation_id: str,
        page: int = 1,
        page_size: int = 200,
    ) -> list[MessageResponse]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT m.* FROM messages m
                    JOIN conversations c ON m.conversation_id = c.id
                    WHERE m.tenant_id = %s AND c.channel_conversation_id = %s
                    ORDER BY m.created_at ASC
                """
                sql += f" OFFSET {(page - 1) * page_size} LIMIT {page_size}"
                cur.execute(sql, (tenant_id, channel_conversation_id))
                rows = cur.fetchall()
                return [MessageResponse(**r) for r in rows]


    def insert_message_raw(
        self,    tenant_id: int,
        conversation_id: int,
        role: str,
        sender_name: Optional[str],
        content: str,
        content_type: str = "text",
        metadata: Optional[dict] = None,
    ) -> MessageResponse:
        return self.create_message(tenant_id, conversation_id, MessageCreate(
            role=role, sender_name=sender_name, content=content,
            content_type=content_type, metadata=metadata or {},
        ))

    def get_conversation(self, tenant_id: int, conversation_id: int) -> Optional[ConversationResponse]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM conversations WHERE tenant_id = %s AND id = %s",
                    (tenant_id, conversation_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return ConversationResponse(**row)


    def get_or_create_conversation(
        self,    tenant_id: int,
        channel: str,
        channel_conversation_id: str,
        customer_name: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> ConversationResponse:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM conversations WHERE tenant_id = %s AND channel = %s AND channel_conversation_id = %s",
                    (tenant_id, channel, channel_conversation_id),
                )
                row = cur.fetchone()
                if row:
                    return ConversationResponse(**row)

                cur.execute(
                    """INSERT INTO conversations (tenant_id, channel, channel_conversation_id, customer_name, customer_id)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING *""",
                    (tenant_id, channel, channel_conversation_id, customer_name, customer_id),
                )
                new_row = cur.fetchone()
                return ConversationResponse(**new_row)


    def create_conversation(
        self,    tenant_id: int,
        data: ConversationCreate,
    ) -> ConversationResponse:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO conversations (tenant_id, channel, channel_conversation_id, customer_name, customer_id, agent_key, assigned_to)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       RETURNING *""",
                    (
                        tenant_id,
                        data.channel,
                        data.channel_conversation_id,
                        data.customer_name,
                        data.customer_id,
                        data.agent_key,
                        data.assigned_to,
                    ),
                )
                row = cur.fetchone()
                return ConversationResponse(**row)


    def update_conversation(
        self,    tenant_id: int,
        conversation_id: int,
        data: ConversationUpdate,
    ) -> Optional[ConversationResponse]:
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return self.get_conversation(tenant_id, conversation_id)

        updates["updated_at"] = "now()"

        set_clause = ", ".join(
            f"{col} = %s" if col != "updated_at" else f"{col} = now()"
            for col in updates
        )
        values = [v for k, v in updates.items() if k != "updated_at"]

        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE conversations SET {set_clause} WHERE tenant_id = %s AND id = %s RETURNING *",
                    values + [tenant_id, conversation_id],
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return ConversationResponse(**row)


    def list_messages(
        self,    tenant_id: int,
        conversation_id: int,
        page: int = 1,
        page_size: int = 50,
        order: str = "ASC",
    ) -> list[MessageResponse]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                sql = "SELECT * FROM messages WHERE tenant_id = %s AND conversation_id = %s ORDER BY created_at " + order
                sql += f" OFFSET {(page - 1) * page_size} LIMIT {page_size}"
                cur.execute(sql, (tenant_id, conversation_id))
                rows = cur.fetchall()
                return [MessageResponse(**r) for r in rows]


    def list_message_window(
        self,    tenant_id: int, conversation_id: int, *, before_id: int | None = None, size: int = 50,
    ) -> dict:
        """Newest-first keyset query, returned in reading order. Concurrent appends don't shift pages."""
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                params = [tenant_id, conversation_id]
                sql = "SELECT * FROM messages WHERE tenant_id = %s AND conversation_id = %s"
                if before_id is not None:
                    sql += " AND id < %s"
                    params.append(before_id)
                cur.execute(sql + " ORDER BY id DESC LIMIT %s", (*params, size + 1))
                rows = cur.fetchall()
                has_more = len(rows) > size
                items = [MessageResponse(**r) for r in reversed(rows[:size])]
                # Only needed to bind legacy replies without an explicit event pointer.
                if items:
                    cur.execute(
                        """SELECT COUNT(*) AS total,
                                  COUNT(*) FILTER (WHERE id < %s) AS preceding
                           FROM messages WHERE tenant_id = %s AND conversation_id = %s AND role = 'agent'""",
                        (items[0].id, tenant_id, conversation_id),
                    )
                    counts = cur.fetchone()
                else:
                    counts = {"total": 0, "preceding": 0}
                return {"items": items, "has_more": has_more,
                        "next_before_id": items[0].id if has_more else None,
                        "agent_total": counts["total"], "agent_offset": counts["preceding"]}


    def bind_session(self, tenant_id: int, conversation_id: int, session_id: str, *, resumed=False) -> None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                self._update_session(cur, tenant_id, conversation_id, session_id)
                if resumed:
                    self._insert_message(cur, tenant_id, conversation_id, MessageCreate(
                        role="customer", content=CONTINUE_TASK,
                    ))

    def save_reply(self, tenant_id: int, conversation_id: int, session_id: str | None,
                   data: MessageCreate) -> MessageResponse:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                if session_id:
                    self._update_session(cur, tenant_id, conversation_id, session_id)
                return self._insert_message(cur, tenant_id, conversation_id, data)

    def create_message(self, tenant_id: int, conversation_id: int, data: MessageCreate) -> MessageResponse:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                return self._insert_message(cur, tenant_id, conversation_id, data)

    @staticmethod
    def _update_session(cur, tenant_id: int, conversation_id: int, session_id: str) -> None:
        cur.execute(
            "UPDATE conversations SET session_id = %s, updated_at = now() "
            "WHERE tenant_id = %s AND id = %s",
            (session_id, tenant_id, conversation_id),
        )

    @staticmethod
    def _insert_message(cur, tenant_id: int, conversation_id: int, data: MessageCreate) -> MessageResponse:
        cur.execute(
            """INSERT INTO messages (tenant_id, conversation_id, role, sender_name, content, content_type, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (
                tenant_id, conversation_id, data.role, data.sender_name, data.content, data.content_type,
                json.dumps(data.metadata or {}, default=str),
            ),
        )
        return MessageResponse(**cur.fetchone())
