"""HTTP adapters for the optional memory service."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from agent_platform_memory import DebugRunRequest, MemoryConversationNotFound, MemoryRequestError, MemoryService

router = APIRouter(prefix="/api/memory", tags=["Memory"])


def memory_service(request: Request) -> MemoryService:
    return request.app.state.memory


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
