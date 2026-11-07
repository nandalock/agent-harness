"""Agent API"""
import json

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from agent_platform_agent_entry import AgentGateway, RequestContext
from agent_platform_agent_runtime.context import CONTINUE_TASK
from agent_platform_chat.service import ChatService, LiveView
from agent_platform_plugin_sdk import AgentConfigService
from agent_platform_rpc_gateway import RpcError
from agent_platform_session import Session
from agent_platform_system_prompt import render_system_prompt
from agent_platform_user_approval import ApprovalService

from backend import plugin_services
from backend.rpc_http import http_error

from ..dependencies import agent_config, agent_entry, approval_inbox, chat_service

router = APIRouter(prefix="/api/agents", tags=["Agents"])


class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None
    visitor_id: str | None = None
    session_id: str | None = None  # AgentRuntime 多轮 Session id：首轮不传（新建），后续传回（恢复）
    resume_from: int | None = Field(default=None, gt=0)


class ResumeRequest(BaseModel):
    conversation_id: int
    session_id: str
    source_turn_start_seq: int = Field(gt=0)


class SteerRequest(BaseModel):
    """运行中输入（/chat/steer）：喂给**已经开着的那条 SSE 流**，不是新开一条。

    ``session_id`` 必填 —— 投递靠它找到正在跑的那一轮（RunRegistry 按 session_id 登记）。

    ``target``：next-step（默认，并入当前轮 —— 「方向偏了，往这边走」）/
    next-turn（本轮结束后作为新的一轮 —— 「等我做完这个，再看这个」）。
    """
    session_id: str
    question: str
    conversation_id: int | None = None  # 给了就落一条会话消息（刷新后仍在对话历史里）
    target: str = "next-step"


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    tier: str
    trace: dict = {}
    conversation_id: int
    session_id: str | None = None


@router.get("")
async def agent_list() -> list[dict]:
    return await plugin_services.agent_api().list()


@router.post("")
async def agent_create(body: dict = Body(...)) -> dict:
    key = (body.get("key") or "").strip()
    name = (body.get("name") or "").strip()
    desc = (body.get("desc") or "").strip()
    if not key or not name:
        raise HTTPException(400, "key 和 name 不能为空")

    agent_type = body.get("agent_type", "agent")
    if agent_type not in ("agent", "router"):
        raise HTTPException(400, "agent_type 必须为 agent 或 router")

    from agent_platform_api_agents import AgentCreateParams

    try:
        summary = await plugin_services.agent_api().create(AgentCreateParams(
            key=key, name=name, desc=desc, agent_type=agent_type,
            provider=(body.get("provider") or "deepseek"),
            system_prompt=body.get("system_prompt", ""),
            fallback_reply=body.get("fallback_reply", "抱歉，我暂时无法处理。"),
            max_steps=int(body.get("max_steps", 5)),
            api_key=body.get("api_key", ""),
            base_url=body.get("base_url", ""),
            model=body.get("model", ""),
        ))
    except RpcError as exc:
        raise http_error(exc) from None
    return {"ok": True, "agent": summary}


@router.get("/{agent_key}/config")
async def agent_get_config(agent_key: str) -> dict:
    try:
        config, cache_policy, model_info = await plugin_services.agent_api().get_config(agent_key)
    except RpcError as exc:
        raise http_error(exc) from None
    return {
        "agent_key": agent_key,
        "config": config,
        "cache_policy": cache_policy,
        "model_config": model_info,
    }


@router.get("/{agent_key}/prompt-preview")
async def agent_prompt_preview(
    agent_key: str,
    question: str = "",
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    entry: AgentGateway = Depends(agent_entry),
    configs: AgentConfigService = Depends(agent_config),
) -> dict:
    """预览该 agent 本轮的 system prompt 组装结果（不调用 LLM）

    调试与自检用：把「模型实际收到什么」显式暴露出来，而不是只能翻日志或猜。
    返回分段明细（每段来自哪个注册方、排在第几位）+ 完整渲染文本 + 可见工具 +
    变量取值，便于回答「为什么这轮提示词长这样」。

    用临时 Session（不注册 SessionStore、不落库）：预览不产生任何副作用。
    """
    definition = await entry.resolve(agent_key)
    if definition.get("agent_type") == "router":
        raise HTTPException(
            400, f"Agent [{agent_key}] 是 router：其提示词由路由模板拼装，暂未接入 SystemPrompt"
        )
    config = await configs.get_config(agent_key) or {}
    session = Session()
    assembly = await plugin_services.prompts().preview(
        tenant_id=x_tenant_id,
        agent_key=agent_key,
        agent_name=definition.get("name", agent_key),
        agent_description=definition.get("description", ""),
        config=config,
        question=question,
        session=session,
    )
    return {
        "agent_key": agent_key,
        "system_prompt": render_system_prompt(assembly),
        "sections": [
            {"name": s.name, "order": s.order, "text": s.text}
            for s in assembly.sections
        ],
        "contexts": [{"name": c.name, "text": c.text} for c in assembly.contexts],
        "tools": [t.name for t in assembly.tools],
        "variables": assembly.variables,
    }


@router.put("/{agent_key}/config")
async def agent_save_config(agent_key: str, body: dict = Body(...), entry: AgentGateway = Depends(agent_entry)) -> dict:
    for field in ("skills_enabled", "skill_install_enabled"):
        if field in body and not isinstance(body[field], bool):
            raise HTTPException(422, f"{field} 必须为布尔值")
    names = body.get("enabled_skills")
    if names is not None and (not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names)):
        raise HTTPException(422, "enabled_skills 必须为技能名称列表或 null")
    try:
        config, cache_policy = await plugin_services.agent_api().save_config(agent_key, body)
    except RpcError as exc:
        raise http_error(exc) from None
    entry.invalidate_desc_cache(agent_key)
    return {"agent_key": agent_key, "config": config, "cache_policy": cache_policy}


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse_frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _live_stream(view: LiveView):
    async def event_gen():
        try:
            if view.snapshot is not None:
                yield _sse_frame(view.snapshot)
            while (event := await view.events.get()) is not None:
                yield _sse_frame(event)
                if event.get("type") in ("done", "error"):
                    break
        finally:
            view.detach()

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/{agent_key}/chat")
async def agent_chat(
    agent_key: str, body: ChatRequest, x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> ChatResponse:
    return ChatResponse(**await chat.reply(x_tenant_id, agent_key, **body.model_dump()))


@router.post("/{agent_key}/chat/stream")
async def agent_chat_stream(
    agent_key: str, body: ChatRequest, x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
):
    return _live_stream(await chat.start_stream(x_tenant_id, agent_key, **body.model_dump()))


@router.get("/{agent_key}/chat/live")
async def agent_chat_live(
    agent_key: str,
    session_id: str = Query(min_length=1),
    conversation_id: int | None = Query(default=None),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
):
    view = chat.attach(x_tenant_id, agent_key, session_id, conversation_id)
    return _live_stream(view) if view is not None else Response(status_code=204)


class CancelRequest(BaseModel):
    session_id: str


@router.post("/{agent_key}/chat/cancel")
async def agent_chat_cancel(
    agent_key: str, body: CancelRequest, x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
):
    return {"cancelled": chat.cancel(x_tenant_id, agent_key, body.session_id)}


@router.post("/{agent_key}/chat/resume/stream")
async def agent_resume_stream(
    agent_key: str, body: ResumeRequest, x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
):
    return _live_stream(await chat.start_stream(
        x_tenant_id, agent_key, CONTINUE_TASK, conversation_id=body.conversation_id,
        session_id=body.session_id, resume_from=body.source_turn_start_seq,
    ))


@router.post("/{agent_key}/chat/steer", status_code=202)
async def agent_chat_steer(
    agent_key: str, body: SteerRequest, x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> dict:
    msg_id = await chat.steer(x_tenant_id, agent_key, **body.model_dump())
    return {"accepted": True, "target": body.target, "msg_id": msg_id}


@router.post("/{agent_key}/route-test")
async def agent_route_test(
    agent_key: str,
    body: ChatRequest,
    x_tenant_id: int = Header(default=1, alias="X-Tenant-ID"),
    entry: AgentGateway = Depends(agent_entry),
) -> dict:
    definition = await entry.resolve(agent_key)
    if definition.get("agent_type") != "router":
        raise HTTPException(400, "仅 Router Agent 支持路由测试")
    reply = await entry.chat(
        RequestContext(tenant_id=x_tenant_id, agent_key=agent_key, visitor_id=body.visitor_id),
        body.question,
    )
    try:
        routing_result = json.loads(reply.answer) if isinstance(reply.answer, str) else reply.answer
    except (json.JSONDecodeError, TypeError):
        routing_result = {"agent_key": reply.answer, "route_level": "?", "confidence": 0}
    return {"routing_result": routing_result, "trace": reply.trace}


@router.get("/sessions/{session_id}/recovery")
async def agent_session_recovery(session_id: str, x_tenant_id: int = Header(alias="X-Tenant-ID")):
    """Legacy REST adapter over the SessionApi service."""
    try:
        return await plugin_services.session_api().recovery(x_tenant_id, session_id)
    except RpcError as exc:
        raise http_error(exc) from None

@router.get("/sessions/{session_id}/trajectory")
async def agent_session_trajectory(
    session_id: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
) -> dict:
    """Legacy REST adapter over the SessionApi service."""
    try:
        result = await plugin_services.session_api().trajectory(x_tenant_id, session_id)
    except RpcError as exc:
        raise http_error(exc) from None
    return {"session_id": session_id, **result["trajectory"]}

class SandboxModeBody(BaseModel):
    mode: str


@router.get("/sessions/{session_id}/sandbox_mode")
async def agent_session_sandbox_mode(
    session_id: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
) -> dict:
    """Legacy REST adapter over the SessionApi service."""
    try:
        return await plugin_services.session_api().sandbox_mode(x_tenant_id, session_id)
    except RpcError as exc:
        raise http_error(exc) from None

@router.post("/sessions/{session_id}/sandbox_mode")
async def agent_set_sandbox_mode(
    session_id: str,
    body: SandboxModeBody,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
) -> dict:
    """Legacy REST adapter over the SessionApi service."""
    try:
        return await plugin_services.session_api().set_sandbox_mode(
            x_tenant_id, session_id, body.mode,
        )
    except RpcError as exc:
        raise http_error(exc) from None

class L1KeywordBody(BaseModel):
    keywords: list[str]
    target: str


class L1KeywordResponse(BaseModel):
    id: int
    router_key: str
    keywords: list[str]
    target: str
    created_at: str | None = None


@router.get("/{agent_key}/l1-keywords")
async def agent_l1_list(
    agent_key: str, entry: AgentGateway = Depends(agent_entry),
    configs: AgentConfigService = Depends(agent_config),
) -> list[dict]:
    await entry.resolve(agent_key)
    return await configs.list_l1_keywords(agent_key)


@router.post("/{agent_key}/l1-keywords")
async def agent_l1_create(
    agent_key: str, body: L1KeywordBody, entry: AgentGateway = Depends(agent_entry),
    configs: AgentConfigService = Depends(agent_config),
) -> dict:
    await entry.resolve(agent_key)
    if not body.keywords or not body.target:
        raise HTTPException(400, "keywords 和 target 不能为空")
    return await configs.create_l1_keyword(agent_key, body.keywords, body.target)


@router.put("/{agent_key}/l1-keywords/{rule_id}")
async def agent_l1_update(
    agent_key: str, rule_id: int, body: L1KeywordBody, entry: AgentGateway = Depends(agent_entry),
    configs: AgentConfigService = Depends(agent_config),
) -> dict:
    await entry.resolve(agent_key)
    result = await configs.update_l1_keyword(rule_id, agent_key, body.keywords, body.target)
    if result is None:
        raise HTTPException(404, "规则不存在")
    return result


@router.delete("/{agent_key}/l1-keywords/{rule_id}")
async def agent_l1_delete(
    agent_key: str, rule_id: int, entry: AgentGateway = Depends(agent_entry),
    configs: AgentConfigService = Depends(agent_config),
) -> dict:
    await entry.resolve(agent_key)
    ok = await configs.delete_l1_keyword(rule_id, agent_key)
    if not ok:
        raise HTTPException(404, "规则不存在")
    return {"ok": True}


# ── Ollama 模型列表 ──

# ── 沙箱升权审批（人工裁决） ──
#
# 一次升权申请会在执行器里挂起，直到这里裁决、或超时（超时按拒绝处理）。
# 申请经 SSE 推给前端（approval.request 事件），前端据此显示待批准卡片。


class ApprovalDecisionBody(BaseModel):
    #: "allow-once" = 一次性放行**本次调用**；"reject" / "cancel" 与未知值分别
    #: 映射到拒绝 / 取消（未知值一律 fail-closed）。不做 Literal 校验是刻意的：
    #: 未知值必须当场落地成「不放行」，而不是 400 之后让申请永远悬着。
    decision: str


@router.get("/approvals")
async def api_list_approvals(service: ApprovalService | None = Depends(approval_inbox)) -> list[dict]:
    """当前待裁决的审批申请。

    冷恢复用：进程重启后挂起表清空，前端据此清掉陈旧的待批准卡片。
    """
    if service is None:
        return []
    return [req.to_dict() for req in service.pending()]


@router.post("/approvals/{approval_id}")
async def api_resolve_approval(
    approval_id: str, body: ApprovalDecisionBody,
    service: ApprovalService | None = Depends(approval_inbox),
) -> dict:
    """裁决一个待批准的申请：唤醒挂起的调用方。

    404 表示该申请不存在或已被处理（超时 / 取消 / 重复点击）——不做幂等成功，
    否则调用方会以为裁决生效而实际没有。
    """
    if service is None or not service.available:
        raise HTTPException(503, "审批服务未装配")
    if not service.resolve(approval_id, body.decision):
        raise HTTPException(404, f"审批申请不存在或已处理: {approval_id}")
    return {"ok": True, "approval_id": approval_id, "decision": body.decision}


@router.get("/ollama-models")
async def list_ollama_models() -> list[dict]:
    """读取 Ollama 本地已安装的 embedding 模型"""
    import os
    import aiohttp
    from backend.core.http import get_http_session

    ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        session = await get_http_session()
        async with session.get(
            f"{ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            data = await resp.json()
    except Exception:
        return []

    models = []
    for m in data.get("models", []):
        caps = m.get("capabilities", []) if isinstance(m, dict) else []
        if "embedding" not in caps:
            continue
        detail = m.get("details", {}) or {}
        models.append({
            "name": m["name"],
            "size_mb": round(m.get("size", 0) / 1_000_000, 1),
            "dim": detail.get("embedding_length"),
            "quant": detail.get("quantization_level", ""),
        })
    return models
