import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent_platform_xianyu import XianyuManager

logger = logging.getLogger(__name__)

router = APIRouter()

_ws_clients: set[WebSocket] = set()


async def _broadcast(data: dict):
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


async def on_new_message(manager: XianyuManager, msg: dict) -> None:
    """Broadcast a newly persisted Xianyu message to browser clients."""
    conversations = manager.get_conversations()
    conversation = next((c for c in conversations if c["cid"] == msg["cid"]), None)
    await _broadcast({
        "type": "new_message",
        "data": {
            "role": "customer",
            "sender_name": msg.get("sender_name", ""),
            "content": msg.get("content", ""),
            "time": msg.get("time", ""),
        },
        "conversation": conversation,
        "conversation_id": conversation["id"] if conversation else None,
    })


def register_broadcast(manager: XianyuManager) -> None:
    async def callback(msg: dict) -> None:
        await on_new_message(manager, msg)

    manager.subscribe(callback)


@router.websocket("/api/ws/chat")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info("[WS] 客户端已连接")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("[WS] 客户端已断开")
    finally:
        _ws_clients.discard(websocket)
