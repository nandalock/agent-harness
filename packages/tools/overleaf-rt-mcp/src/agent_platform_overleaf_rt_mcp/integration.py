"""实时服务单独登记，不改变已有 Python Overleaf 服务配置或工具绑定。"""
import json
import sys

from .db import connect


def ensure_server():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mcp_servers WHERE tenant_id = %s AND name = %s ORDER BY id LIMIT 1", (1, "overleaf-rt"))
            row = cur.fetchone()
            args = json.dumps(["-m", "agent_platform_overleaf_rt_mcp.launcher"])
            if row:
                # Migrate rows created before the launcher moved out of backend.
                cur.execute(
                    "UPDATE mcp_servers SET transport='stdio', command=%s, "
                    "args=%s::jsonb WHERE id=%s",
                    (sys.executable, args, row["id"]),
                )
                conn.commit()
                return row["id"]
            cur.execute("INSERT INTO mcp_servers (tenant_id, name, transport, command, args, env) VALUES (%s, %s, 'stdio', %s, %s::jsonb, '{}'::jsonb) RETURNING id",
                        (1, "overleaf-rt", sys.executable, args))
            server_id = cur.fetchone()["id"]
        conn.commit()
        return server_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def configure_tools(registry, server_id):
    for descriptor in registry.descriptors():
        if descriptor.type == "mcp" and descriptor.server_id == server_id:
            registry.register_tool_timeout(descriptor.name, 300)
            registry.register_execution_mode(descriptor.name, "exclusive")
            registry.register_session_connection(descriptor.name)
