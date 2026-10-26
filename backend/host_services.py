"""Host implementations for the public host-service contracts.

Plugins declare ``approval.v1`` / ``settings.v1`` / ``agents.v1``; this module
supplies the backend's DB- and process-backed implementations. Nothing here is
imported by a plugin package.
"""
import asyncio
import json
import logging

from agent_platform_plugin_sdk import ApprovalOutcome, ApprovalRequest

logger = logging.getLogger(__name__)


class ApprovalHostService:
    """Bridge to the process-level approval service.

    The service may be assembled after the plugin runtime; resolve it per call
    instead of capturing ``None`` at setup time.
    """

    @property
    def available(self) -> bool:
        from backend.interaction.approval import get_approval_service

        return get_approval_service() is not None

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        from backend.interaction.approval import get_approval_service

        service = get_approval_service()
        if service is None:
            return "unavailable"
        return await service.request(req)


class SettingsHostService:
    """DB-backed namespace settings (the ``settings`` table)."""

    async def get(self, namespace: str) -> dict:
        return await asyncio.to_thread(self._get_sync, namespace)

    async def set(self, namespace: str, value: dict) -> None:
        await asyncio.to_thread(self._set_sync, namespace, value)

    @staticmethod
    def _get_sync(namespace: str) -> dict:
        from backend.core.connection import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM settings WHERE namespace = %s", (namespace,)
                )
                row = cur.fetchone()
        raw = (row or {}).get("value")
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _set_sync(namespace: str, value: dict) -> None:
        from backend.core.connection import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO settings (namespace, value, updated_at) "
                    "VALUES (%s, %s::jsonb, now()) "
                    "ON CONFLICT (namespace) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = now()",
                    (namespace, json.dumps(value)),
                )
            conn.commit()


class AgentConfigHostService:
    """Read effective agent config (definition + override), matching the runtime."""

    async def get_config(self, agent_key: str) -> dict | None:
        def load() -> dict:
            from backend.agents import get_agent

            return dict(get_agent(agent_key)._cfg())

        return await asyncio.to_thread(load)


def host_services() -> dict:
    """Services supplied to every plugin runtime scope."""
    from agent_platform_plugin_sdk import AGENTS, APPROVAL, SETTINGS

    services: dict = {
        APPROVAL: ApprovalHostService(),
        SETTINGS: SettingsHostService(),
        AGENTS: AgentConfigHostService(),
    }
    return services


def read_tool_bindings(agent_key: str) -> list[str]:
    """Host DB adapter used by the package's binding filter in every deployment."""
    from backend.core.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tool_name FROM agent_tool_bindings WHERE agent_key = %s", (agent_key,))
            return [row["tool_name"] for row in cur.fetchall()]
