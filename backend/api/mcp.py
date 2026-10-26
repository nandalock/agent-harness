"""MCP API — 服务管理 + 代理 + 热拔插绑定。

MCP 连接、工具发现、探测与重连全部归 `agent-platform.mcp-client` 包：
- 静态配置（YAML/DB 启动装配）每个 server 一个 mcp-client 插件实例；
- 运行时导入/创建/测试通过 `mcp.manager.v1` 控制面完成；
- 工具执行统一走插件侧 tools.v1（或 manager 的临时连接）。

本模块只做 DB CRUD 与 HTTP 翻译，不持有 MCP transport。
"""
import json
import logging
import traceback

from fastapi import APIRouter, Body, HTTPException
from agent_platform_mcp_client import (
    MCP_MANAGER,
    McpConnection,
    McpManager,
    McpServerConfig,
    McpToolInfo,
)

from backend.api.tools import api_list_bindings, api_save_bindings
from backend.core.connection import get_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["MCP"])

#: backend 内嵌的 builtin MCP server（见 main.startup）。
LOCAL_MCP_URL = "http://localhost:9001/mcp"


# ━━ 插件控制面 ━━


def _manager() -> McpManager:
    from backend.plugin_host import get_plugin_host

    host = get_plugin_host()
    if host is None:
        raise HTTPException(503, "插件宿主未装配")
    try:
        return host.runtime.require(MCP_MANAGER)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"MCP 控制面未装配: {exc}") from exc


def _server_name(sid: int) -> str:
    """Statically loaded DB rows use the same stable name as plugin_host."""
    return f"mcp{sid}"


def _config_for_row(row: dict) -> McpServerConfig:
    transport = row.get("transport") or "http"
    name = row.get("server_name") or _server_name(int(row["id"]))
    if transport == "http":
        return McpServerConfig(
            server_name=name,
            transport="http",
            url=row.get("url") or LOCAL_MCP_URL,
        )
    args = row.get("args") or []
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = []
    env = row.get("env") or {}
    if isinstance(env, str):
        try:
            env = json.loads(env)
        except json.JSONDecodeError:
            env = {}
    return McpServerConfig(
        server_name=name,
        transport="stdio",
        command=row.get("command") or "",
        args=tuple(str(item) for item in args) if isinstance(args, list) else (),
        env={str(k): str(v) for k, v in env.items()}
        if isinstance(env, dict)
        else {},
    )


def _tool_rows(tools: tuple[McpToolInfo, ...] | list[McpToolInfo]) -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in tools
    ]


def _result_rows(result) -> dict:
    if result.error is not None:
        raise HTTPException(502, result.error.message)
    data = result.data if isinstance(result.data, dict) else {}
    rows = data.get("rows", [])
    return {"tool": None, "rows": rows, "count": data.get("count", len(rows))}


# ━━ MCP 服务 CRUD ━━


@router.get("/servers")
def api_list_servers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, name, transport, url, command, args, env, created_at "
                "FROM mcp_servers ORDER BY id"
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                d["args"] = list(d["args"]) if d.get("args") else []
                d["env"] = dict(d["env"]) if d.get("env") else {}
                rows.append(d)
            return rows


@router.post("/servers")
async def api_create_server(payload: dict = Body(...)):
    args = payload.get("args")
    if isinstance(args, list):
        args = json.dumps(args)
    env = payload.get("env")
    if isinstance(env, dict):
        env = json.dumps(env)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO mcp_servers (tenant_id, name, transport, url, command, args, env) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING id",
                (
                    payload.get("tenant_id", 1),
                    payload["name"],
                    payload.get("transport", "http"),
                    payload.get("url"),
                    payload.get("command"),
                    args,
                    env,
                ),
            )
            sid = cur.fetchone()["id"]
        conn.commit()

    # Make the new server usable without a restart; failure is not fatal.
    tools_count = 0
    try:
        config = _config_for_row(
            {
                "id": sid,
                "server_name": _server_name(sid),
                "transport": payload.get("transport", "http"),
                "url": payload.get("url"),
                "command": payload.get("command"),
                "args": payload.get("args", []),
                "env": payload.get("env", {}),
            }
        )
        server = await _manager().ensure(config)
        tools_count = len(server.connection.tools)
    except Exception as exc:  # noqa: BLE001
        logger.warning("新建 MCP server %s 连接失败（配置已保存）: %s", sid, exc)
    return {"id": sid, "ok": True, "tools_count": tools_count}


@router.delete("/servers/{sid}")
async def api_delete_server(sid: int):
    try:
        await _manager().remove(_server_name(sid))
    except HTTPException:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("移除 MCP server %s 连接失败: %s", sid, exc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mcp_servers WHERE id = %s", (sid,))
        conn.commit()
    return {"ok": True}


# ━━ 一键导入（Claude Desktop 格式） ━━


@router.post("/import")
async def api_import_servers(payload: dict = Body(...)):
    """导入 MCP Server 配置，支持 Claude Desktop 格式。

    格式 A — 单个 server:
      {"name":"github","command":"docker","args":[...],"env":{...}}

    格式 B — Claude Desktop 完整配置:
      {"mcpServers":{"github":{...},"filesystem":{...}}}
    """
    entries: list[tuple[str, dict]] = []

    if "mcpServers" in payload:
        for name, cfg in payload["mcpServers"].items():
            entries.append((name, cfg))
    elif "name" in payload:
        entries.append((payload["name"], payload))
    else:
        raise HTTPException(400, "请提供 mcpServers 对象或包含 name 的单个配置")

    created: list[dict] = []
    for name, cfg in entries:
        has_url = "url" in cfg and cfg["url"]
        transport = "http" if has_url else "stdio"

        args = cfg.get("args")
        if isinstance(args, list):
            args = json.dumps(args)
        env = cfg.get("env")
        if isinstance(env, dict):
            env = json.dumps(env)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO mcp_servers (tenant_id, name, transport, url, command, args, env)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING id""",
                    (
                        payload.get("tenant_id", 1),
                        name,
                        transport,
                        cfg.get("url"),
                        cfg.get("command"),
                        args,
                        env,
                    ),
                )
                sid = cur.fetchone()["id"]
            conn.commit()

        tools_count = 0
        try:
            config = _config_for_row(
                {
                    "id": sid,
                    "server_name": _server_name(sid),
                    "transport": transport,
                    "url": cfg.get("url"),
                    "command": cfg.get("command"),
                    "args": cfg.get("args", []),
                    "env": cfg.get("env", {}),
                }
            )
            server = await _manager().ensure(config)
            tools_count = len(server.connection.tools)
        except Exception as exc:  # noqa: BLE001
            logger.warning("导入 [%s] 连接失败 (server id=%s): %s", name, sid, exc)

        created.append(
            {
                "id": sid,
                "name": name,
                "transport": transport,
                "tools_count": tools_count,
            }
        )

    return {"ok": True, "created": created}


# ━━ 按 server ID 代理 ━━


def _lookup_server(sid: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, transport, url, command, args, env "
                "FROM mcp_servers WHERE id = %s",
                (sid,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"MCP 服务不存在: {sid}")
    result = dict(row)
    result["server_name"] = _server_name(sid)
    return result


@router.post("/servers/{sid}/tools")
async def api_server_tools(sid: int):
    """列出 server 的工具（兼做连通性检测）；stdio 会临时拉起/复用连接。"""
    config = _config_for_row(_lookup_server(sid))
    try:
        server = await _manager().ensure(config)
        return _tool_rows(server.connection.tools)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("MCP 服务 [%s] 连接失败: %s", sid, traceback.format_exc())
        raise HTTPException(502, f"无法连接 MCP 服务: {exc}") from exc


@router.post("/servers/{sid}/call")
async def api_server_call(sid: int, payload: dict = Body(...)):
    name = payload["name"]
    args = payload.get("args", {})
    config = _config_for_row(_lookup_server(sid))
    try:
        manager = _manager()
        server = manager.get(config.server_name) or await manager.ensure(config)
        raw_name = server.registration.public_to_raw.get(name, name)
        result = await manager.call(
            config.server_name, raw_name, args, config=config
        )
        body = _result_rows(result)
        body["tool"] = name
        return body
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(404, f"工具不存在: {name}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("MCP 调用失败 [%s/%s]: %s", sid, name, traceback.format_exc())
        raise HTTPException(502, f"MCP 调用失败: {exc}") from exc


# ━━ 通用 MCP proxy（传 URL，兼容旧前端） ━━


@router.post("/proxy/tools")
async def api_proxy_tools(payload: dict = Body(...)):
    url = payload.get("url", LOCAL_MCP_URL)
    config = McpServerConfig(server_name="proxy", transport="http", url=url)
    try:
        return _tool_rows(await _manager().probe(config))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("MCP 连接失败 [%s]: %s", url, traceback.format_exc())
        raise HTTPException(502, f"无法连接 MCP 服务: {exc}") from exc


@router.post("/proxy/call")
async def api_proxy_call(payload: dict = Body(...)):
    url = payload.get("url", LOCAL_MCP_URL)
    name = payload["name"]
    args = payload.get("args", {})
    config = McpServerConfig(server_name="proxy", transport="http", url=url)
    connection = McpConnection(config)
    try:
        await connection.connect()
        result = await connection.call(name, args)
        body = _result_rows(result)
        body["tool"] = name
        return body
    except Exception as exc:  # noqa: BLE001
        logger.error("MCP 调用失败 [%s/%s]: %s", url, name, traceback.format_exc())
        raise HTTPException(502, f"MCP 调用失败: {exc}") from exc
    finally:
        await connection.aclose()


# ━━ 本地 MCP 快捷方式 ━━


@router.get("/tools")
async def api_list_tools():
    config = McpServerConfig(
        server_name="local", transport="http", url=LOCAL_MCP_URL
    )
    try:
        return _tool_rows(await _manager().probe(config))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("本地 MCP 连接失败: %s", traceback.format_exc())
        raise HTTPException(502, f"无法连接本地 MCP 服务: {exc}") from exc


@router.get("/tools/all")
async def api_list_all_tools():
    """列出 tools.v1 中的全部工具（唯一 Agent-facing 注册表）。"""
    from agent_platform_tool_host import get_unified_tools_optional

    unified = get_unified_tools_optional()
    if unified is None:
        raise HTTPException(503, "单轨工具运行时未装配")
    return unified.list_tools()


@router.get("/tools/{name}")
async def api_get_tool(name: str):
    """查询单个工具信息（未索引则懒加载）。"""
    from agent_platform_tool_host import get_unified_tools_optional

    unified = get_unified_tools_optional()
    if unified is None:
        raise HTTPException(503, "单轨工具运行时未装配")
    descriptor = await unified.ensure_tool(name)
    if descriptor is None:
        raise HTTPException(404, f"工具不存在: {name}")
    native = unified.native_descriptor(name)
    return {
        "name": descriptor.name,
        "description": descriptor.description,
        "inputSchema": dict(descriptor.input_schema),
        "server_id": native.server_id if native is not None else 0,
        "server_name": unified.source_label(name),
        "plugin_id": descriptor.plugin_id,
        "plugin_name": descriptor.plugin_name,
        "transport": (native.transport or "native") if native is not None else "plugin",
    }


@router.post("/tools/{name}/call")
async def api_call_tool(name: str, args: dict = Body(...)):
    """调用工具 — 统一经 tools.v1；无宿主上下文的能力 fail-closed。"""
    from agent_platform_tool_host import get_unified_tools_optional

    unified = get_unified_tools_optional()
    if unified is None:
        raise HTTPException(503, "单轨工具运行时未装配")
    if await unified.ensure_tool(name) is None:
        raise HTTPException(404, f"工具不存在: {name}")
    result = await unified.execute(name, args, None)
    if "error" in result:
        raise HTTPException(502, result["error"])
    return result


# ━━ 热拔插绑定（兼容别名）━━
# 绑定与工具来源正交，已迁到 /api/tools/bindings（api/tools.py）；
# 这里保留旧路径，旧客户端与既有文档不受影响。

router.add_api_route("/bindings", api_list_bindings, methods=["GET"])
router.add_api_route("/bindings/{agent_key}", api_save_bindings, methods=["PUT"])
