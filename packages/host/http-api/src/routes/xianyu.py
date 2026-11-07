from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agent_platform_xianyu import XianyuManager

router = APIRouter(prefix="/api/xianyu", tags=["Xianyu"])


class ConnectRequest(BaseModel):
    cookie: str


class FetchHistoryRequest(BaseModel):
    cid: str


def xianyu_service(request: Request) -> XianyuManager:
    service = getattr(request.app.state, "xianyu", None)
    if service is None:
        raise HTTPException(404, "xianyu plugin is not enabled")
    return service


@router.post("/connect")
async def connect_route(
    body: ConnectRequest,
    service: XianyuManager = Depends(xianyu_service),
):
    try:
        error = await service.connect(body.cookie)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if error:
        raise HTTPException(400, error)
    return {"ok": True}


@router.post("/disconnect")
async def disconnect_route(service: XianyuManager = Depends(xianyu_service)):
    await service.disconnect()
    return {"ok": True}


@router.get("/cookie")
def get_cookie_route(service: XianyuManager = Depends(xianyu_service)) -> dict:
    return {"cookie": service.get_saved_cookie()}


@router.get("/status")
def status_route(service: XianyuManager = Depends(xianyu_service)) -> dict:
    return service.get_status()


@router.get("/conversations")
def conversations_route(service: XianyuManager = Depends(xianyu_service)) -> dict:
    return {"conversations": service.get_conversations()}


@router.get("/conversations/{cid}")
def messages_route(cid: str, service: XianyuManager = Depends(xianyu_service)) -> dict:
    return {"messages": service.get_messages(cid)}


@router.post("/conversations/fetch")
async def fetch_history_route(
    body: FetchHistoryRequest,
    service: XianyuManager = Depends(xianyu_service),
):
    try:
        count = await service.fetch_history(body.cid)
        return {"ok": True, "count": count}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
