"""实时服务单独登记，不改变已有 Python Overleaf 服务配置或工具绑定。"""
import json
import sys

from backend.core.connection import get_conn


def ensure_server():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mcp_servers WHERE tenant_id = %s AND name = %s ORDER BY id LIMIT 1", (1, "overleaf-rt"))
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute("INSERT INTO mcp_servers (tenant_id, name, transport, command, args, env) VALUES (%s, %s, 'stdio', %s, %s::jsonb, '{}'::jsonb) RETURNING id",
                        (1, "overleaf-rt", sys.executable, json.dumps(["-m", "backend.tool_packages.overleaf_rt.launcher"])))
            return cur.fetchone()["id"]


def configure_tools(registry, server_id):
    for descriptor in registry.descriptors():
        if descriptor.type == "mcp" and descriptor.server_id == server_id:
            registry.register_tool_timeout(descriptor.name, 300)
            registry.register_execution_mode(descriptor.name, "exclusive")
            registry.register_session_connection(descriptor.name)

