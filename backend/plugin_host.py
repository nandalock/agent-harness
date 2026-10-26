"""Backend host: load a package composition and inject host services.

Default plugin instances belong to agent-platform-default. Database rows add
MCP client instances; each instance owns its server's complete tool group.
All model-facing tool registrations are owned by plugins through tools.v1.
"""
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

def _resolve_config_path() -> Path | None:
    """显式 env 优先；否则自动发现工作目录里的约定文件。"""
    explicit = os.environ.get("PLUGIN_CONFIG")
    if explicit:
        return Path(explicit)
    for candidate in (
        Path.cwd() / "plugins.yaml",
        Path.cwd() / "config" / "plugins.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


@dataclass
class PluginHost:
    runtime: object
    unified: object
    tools: object

    @property
    def plugins(self):
        return self.runtime.plugins

    async def aclose(self) -> None:
        from agent_platform_tool_host import close_unified_tools

        try:
            await close_unified_tools()
        finally:
            await self.runtime.aclose()


_host: PluginHost | None = None


def get_plugin_host() -> PluginHost | None:
    return _host


def _mcp_plugin_entries() -> list[dict]:
    """Turn DB MCP server rows into mcp-client plugin instances.

    Raw tool names are preserved (`tool_prefix` empty) so existing Agent tool
    bindings keep working. Each server is one plugin instance, regardless of
    how many tools it discovers.
    """
    if os.environ.get("PLUGIN_MCP_AUTO", "true").lower() in ("0", "false", "no"):
        return []
    try:
        from backend.core.connection import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, transport, url, command, args, env "
                    "FROM mcp_servers ORDER BY id"
                )
                rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 MCP server 配置失败，跳过自动装配: %s", exc)
        return []

    entries: list[dict] = []
    for row in rows:
        # A shared DB may contain container-only optional integrations. Local
        # deployment leaves persisted rows untouched and selects its own profile.
        if row.get("name") in ("overleaf", "overleaf-rt"):
            enabled_var = "OVERLEAF_ENABLED" if row["name"] == "overleaf" else "OVERLEAF_RT_ENABLED"
            if os.environ.get(enabled_var, "true").lower() in ("0", "false", "no"):
                continue
        transport = row.get("transport") or "http"
        config = {
            "server_name": f"mcp{row['id']}",
            "transport": transport,
            "timeout_seconds": 300,
            "tool_prefix": "",
        }
        if transport == "http":
            if not row.get("url"):
                continue
            config["url"] = row["url"]
            for default_port, variable in ((9001, "BUILTIN_MCP_PORT"), (9002, "PAPER_MCP_PORT")):
                if row["url"] == f"http://localhost:{default_port}/mcp":
                    config["url"] = f"http://localhost:{os.environ.get(variable, str(default_port))}/mcp"
        else:
            if not row.get("command"):
                continue
            config["command"] = row["command"]
            args = row.get("args") or []
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = []
            config["args"] = list(args) if isinstance(args, list) else []
            env = row.get("env") or {}
            if isinstance(env, str):
                try:
                    env = json.loads(env)
                except json.JSONDecodeError:
                    env = {}
            config["env"] = (
                {str(k): str(v) for k, v in env.items()}
                if isinstance(env, dict)
                else {}
            )
        if row.get("name") in ("overleaf", "overleaf-rt"):
            # Compilation / realtime edits share local state and are slow.
            config["execution_mode"] = "exclusive"
        entries.append(
            {
                "id": f"mcp-{row['id']}",
                "name": "agent-platform.mcp-client",
                "config": config,
            }
        )
    return entries


def _compose_plugins(config):
    """Load the default package assembly, then add host-configured instances."""
    from agent_platform_default import compose
    from agent_platform_plugin_sdk import PluginConfiguration

    data = compose(config).model_dump()
    plugins = list(data["plugins"])
    existing_ids = {entry["id"] for entry in plugins}
    existing_servers = {
        entry.get("config", {}).get("server_name")
        for entry in plugins
        if entry.get("name") == "agent-platform.mcp-client"
        and isinstance(entry.get("config"), dict)
    }
    for entry in _mcp_plugin_entries():
        if entry["id"] in existing_ids:
            continue
        if entry["config"]["server_name"] in existing_servers:
            continue
        plugins.append(entry)
        existing_ids.add(entry["id"])

    data["plugins"] = plugins
    return PluginConfiguration.model_validate(data)


async def init_plugin_host(catalog: object | None = None) -> PluginHost | None:
    """装配单轨工具运行时并加载 PLUGIN_CONFIG 中的额外插件。

    `catalog` 仅用于测试/嵌入，缺省使用真实 entry point 发现。
    """
    global _host
    if _host is not None:
        return _host

    try:
        from agent_platform_plugin_runtime import PluginRuntime
        from agent_platform_plugin_sdk import TOOLS
        from agent_platform_tools_default import TOOL_CATALOG
        from agent_platform_tool_host import UnifiedToolsRuntime, set_unified_tools
        from agent_platform_tool_system.registry import ToolRegistry
        from agent_platform_tool_system.runtime import ToolRuntime
    except ImportError as exc:
        raise RuntimeError(
            "插件 SDK/runtime/tools-default 未安装，无法装配单轨工具运行时"
        ) from exc

    from agent_platform_plugin_runtime import load_yaml_config
    from agent_platform_plugin_sdk import PluginConfiguration

    config_path = _resolve_config_path()
    if config_path is not None:
        logger.info("加载插件配置: %s", config_path)
        config = load_yaml_config(config_path)
    else:
        config = PluginConfiguration()
    config = _compose_plugins(config)

    from backend.host_services import host_services, read_tool_bindings
    from agent_platform_tool_system.registry import configure_bindings
    configure_bindings(read_tool_bindings)

    runtime = None
    try:
        runtime = PluginRuntime(
            config, catalog=catalog, host_services=host_services()
        )
        await runtime.start()
        tools = runtime.require(TOOLS)
        catalog_service = runtime.require(TOOL_CATALOG)
        # No native registry: every tool is owned by a plugin. The empty
        # registry/runtime keep the bridge's generic native hooks available for
        # tests and embedded hosts without creating a second live source.
        native_registry = ToolRegistry(providers=[])
        unified = UnifiedToolsRuntime(
            native_registry,
            ToolRuntime(registry=native_registry, executors={}),
            tools,
            catalog_service,
        )
        await unified.start()
        set_unified_tools(unified)
    except BaseException:
        if runtime is not None:
            await runtime.aclose()
        raise

    _host = PluginHost(runtime=runtime, unified=unified, tools=tools)
    logger.info(
        "单轨工具运行时已启动，插件: %s",
        [(plugin.instance_id, plugin.name) for plugin in runtime.plugins],
    )
    return _host


async def close_plugin_host() -> None:
    """先注销单轨运行时，再逆序关闭插件；幂等。"""
    global _host
    host, _host = _host, None
    if host is not None:
        await host.aclose()
