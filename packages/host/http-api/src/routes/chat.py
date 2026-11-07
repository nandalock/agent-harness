from fastapi import APIRouter, Depends, Header, HTTPException, Query

from agent_platform_chat import (
    ChatService, ConversationCreate, ConversationUpdate, ConversationResponse, MessageCreate, MessageResponse,
)

from ..dependencies import chat_service

router = APIRouter(prefix="/api/chat", tags=["Chat"])


@router.get("/conversations")
def list_conversations(
    channel: str = Query(default=""),
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> dict:
    rows = chat.store.list_conversations_with_summary(
        x_tenant_id,
        channel=channel or None,
        status=status or None,
        page=page,
        page_size=size,
    )
    return {"items": rows, "page": page, "size": size}


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> ConversationResponse:
    return chat.store.create_conversation(x_tenant_id, body)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> ConversationResponse:
    conv = chat.store.get_conversation(x_tenant_id, conversation_id)
    if conv is None:
        raise HTTPException(404, "会话不存在")
    return conv


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> ConversationResponse:
    conv = chat.store.update_conversation(x_tenant_id, conversation_id, body)
    if conv is None:
        raise HTTPException(404, "会话不存在")
    return conv


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> dict:
    conv = chat.store.get_conversation(x_tenant_id, conversation_id)
    if conv is None:
        raise HTTPException(404, "会话不存在")
    msgs = chat.store.list_messages(x_tenant_id, conversation_id, page=page, page_size=size)
    return {"items": msgs, "page": page, "size": size}


@router.get("/conversations/{conversation_id}/messages/window")
def message_window(
    conversation_id: int,
    before_id: int | None = Query(default=None, gt=0),
    size: int = Query(default=50, ge=1, le=100),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> dict:
    result = chat.store.message_window(x_tenant_id, conversation_id, before_id=before_id, size=size)
    if result is None:
        raise HTTPException(404, "会话不存在")
    return result


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: int,
    body: MessageCreate,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    chat: ChatService = Depends(chat_service),
) -> MessageResponse:
    conv = chat.store.get_conversation(x_tenant_id, conversation_id)
    if conv is None:
        raise HTTPException(404, "会话不存在")
    return chat.store.create_message(x_tenant_id, conversation_id, body)
