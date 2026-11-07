"""Compatibility adapters for legacy APIs."""


def read_tool_bindings(agent_key: str) -> list[str]:
    """Legacy API adapter; plugin runs read bindings through ``tool-bindings.v1``."""
    from backend.core.connection import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tool_name FROM agent_tool_bindings WHERE agent_key = %s",
                (agent_key,),
            )
            return [row["tool_name"] for row in cur.fetchall()]
