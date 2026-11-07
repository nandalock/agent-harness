"""经验记忆 — 跨会话检索用户画像和历史摘要"""
from __future__ import annotations

import json


class ExperienceMemory:
    """跨会话经验检索"""

    def __init__(self, database):
        self._database = database

    def get_profile(self, tenant_id: int, user_id: str) -> list[str]:
        """读用户画像（facts 列表）"""
        if not user_id:
            return []
        profile = self.get_user_profile(tenant_id, user_id)
        return list(profile["facts"]) if profile else []

    def get_recent_conversations(
        self, tenant_id: int, user_id: str, limit: int = 3,
    ) -> list[dict]:
        """该用户最近的会话摘要"""
        if not user_id:
            return []
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, channel, status,
                              (SELECT content FROM messages
                               WHERE conversation_id = c.id
                               ORDER BY created_at ASC LIMIT 1) as first_msg,
                              created_at
                       FROM conversations c
                       WHERE tenant_id = %s AND customer_id = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (tenant_id, user_id, limit),
                )
                return cur.fetchall()

    def render_profile(self, tenant_id: int, user_id: str) -> str:
        """画像 → prompt 文本"""
        facts = self.get_profile(tenant_id, user_id)
        if not facts:
            return ""
        lines = [f"- {f}" for f in facts]
        return "## 用户画像\n" + "\n".join(lines)

    def list_user_profiles(self, tenant_id: int) -> list[dict]:
        """获取所有有画像的用户列表"""
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT up.*, c.customer_name
                       FROM user_profiles up
                       LEFT JOIN conversations c ON c.tenant_id = up.tenant_id
                         AND c.customer_id = up.user_id
                         AND c.id = (
                           SELECT id FROM conversations
                           WHERE tenant_id = up.tenant_id AND customer_id = up.user_id
                           ORDER BY updated_at DESC LIMIT 1
                         )
                       WHERE up.tenant_id = %s
                       ORDER BY up.updated_at DESC""",
                    (tenant_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "user_id": r["user_id"],
                        "customer_name": r.get("customer_name") or r["user_id"],
                        "facts_count": len(r["facts"]),
                        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    }
                    for r in rows
                ]

    def get_user_profile(self, tenant_id: int, user_id: str) -> dict | None:
        """获取单个用户的画像详情"""
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM user_profiles WHERE tenant_id = %s AND user_id = %s",
                    (tenant_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "user_id": row["user_id"],
                    "facts": row["facts"],
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }

    def save_profile(self, tenant_id: int, user_id: str, facts: list[str]):
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_profiles (tenant_id, user_id, facts, updated_at)
                       VALUES (%s, %s, %s::jsonb, now())
                       ON CONFLICT (tenant_id, user_id)
                       DO UPDATE SET facts = EXCLUDED.facts, updated_at = now()""",
                    (tenant_id, user_id, json.dumps(facts, ensure_ascii=False)),
                )
