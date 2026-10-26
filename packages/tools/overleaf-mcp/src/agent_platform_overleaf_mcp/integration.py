"""Register Overleaf through the platform's MCP server table."""
import json
import sys

from .db import connect

SERVER_NAME = "overleaf"


def ensure_server() -> int:
    """Register once; preserve an existing Overleaf server's configuration."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM mcp_servers WHERE tenant_id = %s AND name = %s ORDER BY id LIMIT 1",
                (1, SERVER_NAME),
            )
            row = cur.fetchone()
            args = json.dumps(["-m", "agent_platform_overleaf_mcp.launcher"])
            if row:
                # Migrate rows created before the tool implementation moved out
                # of backend/tool_packages.
                cur.execute(
                    "UPDATE mcp_servers SET transport='stdio', command=%s, "
                    "args=%s::jsonb WHERE id=%s",
                    (sys.executable, args, row["id"]),
                )
                conn.commit()
                return row["id"]
            cur.execute(
                """INSERT INTO mcp_servers (tenant_id, name, transport, command, args, env)
                   VALUES (%s, %s, 'stdio', %s, %s::jsonb, '{}'::jsonb) RETURNING id""",
                (1, SERVER_NAME, sys.executable, args),
            )
            server_id = cur.fetchone()["id"]
        conn.commit()
        return server_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def configure_tools(registry, server_id: int):
    """Allow compilation time and serialize tools that share a local git cache."""
    for descriptor in registry.descriptors():
        if descriptor.type == "mcp" and descriptor.server_id == server_id:
            registry.register_tool_timeout(descriptor.name, 300)
            registry.register_execution_mode(descriptor.name, "exclusive")
