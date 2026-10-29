"""Plugin-owned service readiness, tool registration and reverse-order shutdown."""
import asyncio
import logging
import os
import sys

from pydantic import Field

from agent_platform_plugin_sdk import PluginSpec, SdkModel, ServiceRequirement
from agent_platform_mcp_client import MCP_MANAGER, McpServerConfig

logger = logging.getLogger(__name__)


def owns_database_row(row):
    """Rows consumed by these plugins rather than generic client discovery."""
    return row.get("name") in ("overleaf", "overleaf-rt") or row.get("url") in (
        "http://localhost:9001/mcp", "http://localhost:9002/mcp",
    )


class Config(SdkModel):
    enabled: bool = True
    port: int | None = Field(default=None, ge=1, le=65535)


def enabled(variable, default="true"):
    return os.environ.get(variable, default).lower() not in ("false", "0", "no")


def server_id(kind):
    """Keep persisted server identities and tool bindings across the migration."""
    if kind == "overleaf":
        from agent_platform_overleaf_mcp.integration import ensure_server
        return ensure_server()
    if kind == "overleaf-rt":
        from agent_platform_overleaf_rt_mcp.integration import ensure_server
        return ensure_server()
    from agent_platform_builtin_mcp.db import get_conn
    port = 9001 if kind == "builtin" else 9002
    url = f"http://localhost:{port}/mcp"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mcp_servers WHERE tenant_id=1 AND url=%s ORDER BY id LIMIT 1", (url,))
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute("INSERT INTO mcp_servers(tenant_id,name,transport,url) VALUES (1,%s,'http',%s) RETURNING id", (kind, url))
            return cur.fetchone()["id"]


class BuiltinPlugin:
    kind = "builtin"
    spec = PluginSpec(name="agent-platform.builtin-mcp", version="0.1.0",
                      requires=(ServiceRequirement(service=MCP_MANAGER.ref),))
    config_model = Config

    async def setup(self, ctx, config):
        if not config.enabled or not enabled("MANAGED_MCP_ENABLED"):
            return
        if self.kind.startswith("overleaf"):
            variable = "OVERLEAF_ENABLED" if self.kind == "overleaf" else "OVERLEAF_RT_ENABLED"
            if not enabled(variable, "true" if self.kind == "overleaf" else "false"):
                return
        # Embedded calls own a synchronous DB connection only for this operation.
        # Use the runtime's lifecycle task for MCP transport enter/exit.
        try:
            identity = await asyncio.to_thread(server_id, self.kind)
            manager = ctx.require(MCP_MANAGER)
            if self.kind in ("builtin", "paper"):
                from .http import start_server, close_servers
                if self.kind == "builtin":
                    from agent_platform_builtin_mcp.server import create_server
                    port = config.port or int(os.environ.get("BUILTIN_MCP_PORT", "9001"))
                else:
                    from agent_platform_paper_mcp.server import create_server
                    port = config.port or int(os.environ.get("PAPER_MCP_PORT", "9002"))
                server = await start_server(create_server().streamable_http_app(), port)
                ctx.on_dispose(lambda: close_servers([server]), label=f"{self.kind} HTTP server")
                connection = McpServerConfig(server_name=f"mcp{identity}", transport="http",
                                             url=f"http://localhost:{port}/mcp", tool_prefix="")
            else:
                module = "agent_platform_overleaf_mcp.launcher" if self.kind == "overleaf" else "agent_platform_overleaf_rt_mcp.launcher"
                connection = McpServerConfig(server_name=f"mcp{identity}", transport="stdio", command=sys.executable,
                                             args=("-m", module), tool_prefix="", execution_mode="exclusive")
            await manager.add(connection, owner=ctx.instance_id)

            async def disconnect():
                # Reconnect changes the generation token while retaining owner.
                current = manager.get(connection.server_name)
                if current is not None and current.owner == ctx.instance_id:
                    await manager.remove(connection.server_name, current.token)

            ctx.on_dispose(disconnect, label=f"{self.kind} MCP connection")
        except Exception:
            if self.kind in ("builtin", "paper"):
                raise
            logger.warning("Optional %s integration unavailable", self.kind, exc_info=True)


class PaperPlugin(BuiltinPlugin):
    kind = "paper"
    spec = PluginSpec(name="agent-platform.paper-mcp", version="0.1.0", requires=BuiltinPlugin.spec.requires)


class OverleafPlugin(BuiltinPlugin):
    kind = "overleaf"
    spec = PluginSpec(name="agent-platform.overleaf-mcp", version="0.1.0", requires=BuiltinPlugin.spec.requires)


class OverleafRtPlugin(BuiltinPlugin):
    kind = "overleaf-rt"
    spec = PluginSpec(name="agent-platform.overleaf-rt-mcp", version="0.1.0", requires=BuiltinPlugin.spec.requires)
