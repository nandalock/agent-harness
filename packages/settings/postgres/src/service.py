"""Namespace-scoped JSON settings in PostgreSQL."""
from __future__ import annotations

import asyncio
import json


class PostgresSettingsService:
    def __init__(self, database) -> None:
        self._database = database

    def _get_sync(self, namespace: str) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM settings WHERE namespace = %s", (namespace,))
                row = cur.fetchone()
        raw = (row or {}).get("value")
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw if isinstance(raw, dict) else {}

    def _set_sync(self, namespace: str, value: dict) -> None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO settings (namespace, value, updated_at) "
                    "VALUES (%s, %s::jsonb, now()) "
                    "ON CONFLICT (namespace) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = now()",
                    (namespace, json.dumps(value)),
                )

    async def get(self, namespace: str) -> dict:
        return await asyncio.to_thread(self._get_sync, namespace)

    async def set(self, namespace: str, value: dict) -> None:
        await asyncio.to_thread(self._set_sync, namespace, value)
