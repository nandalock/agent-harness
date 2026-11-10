"""HTTP adapters for the optional memory service."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from agent_platform_memory import DebugRunRequest, MemoryConversationNotFound, MemoryRequestError, MemoryService
from agent_platform_memory.notes import MAX_NOTE_CHARS

router = APIRouter(prefix="/api/memory", tags=["Memory"])


def memory_service(request: Request) -> MemoryService:
    return request.app.state.memory


class MarkdownNote(BaseModel):
    markdown: str = Field(max_length=MAX_NOTE_CHARS)


@router.get("/agents")
async def list_agents(memory: MemoryService = Depends(memory_service)) -> list[dict]:
    return await memory.list_agents()


@router.get("/agents/{agent_key}")
async def agent_memory(
    agent_key: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.agent_memory(x_tenant_id, agent_key)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/agents/{agent_key}")
async def save_agent_memory(
    agent_key: str, body: MarkdownNote,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.agent_memory(x_tenant_id, agent_key, body.markdown)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/sessions/{session_id}")
async def session_memory(
    session_id: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.session_memory(x_tenant_id, session_id)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/sessions/{session_id}")
async def save_session_memory(
    session_id: str, body: MarkdownNote,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.session_memory(x_tenant_id, session_id, body.markdown)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/sessions/{session_id}/draft")
async def draft_session_notes(
    session_id: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.draft_session_notes(x_tenant_id, session_id)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except MemoryRequestError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/users")
def list_user_profiles(
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> list[dict]:
    return memory.experience.list_user_profiles(x_tenant_id)


@router.get("/users/{user_id}")
def get_user_profile(
    user_id: str,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    profile = memory.experience.get_user_profile(x_tenant_id, user_id)
    if profile is None:
        raise HTTPException(404, "用户画像不存在")
    return profile


@router.post("/debug/run")
async def debug_run_memory(
    body: DebugRunRequest,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    memory: MemoryService = Depends(memory_service),
) -> dict:
    try:
        return await memory.debug_run(body, x_tenant_id)
    except MemoryConversationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except MemoryRequestError as exc:
        raise HTTPException(400, str(exc)) from exc
