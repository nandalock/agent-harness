import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_platform_workflow import (
    WorkflowNameConflict,
    WorkflowNotFound,
    WorkflowService,
    WorkflowValidationError,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class RunWorkflowPayload(BaseModel):
    input: str = ""
    user_id: str = ""


class CreateWorkflowPayload(BaseModel):
    name: str = "未命名工作流"
    nodes: list | None = None
    edges: list | None = None


class SaveWorkflowPayload(BaseModel):
    name: str | None = None
    status: str | None = None
    nodes: list | None = None
    edges: list | None = None


def workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow", None)
    if service is None:
        raise HTTPException(404, "workflow plugin is not enabled")
    return service


async def _sse(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    async for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("")
async def list_workflows(
    tenant_id: int = 1,
    service: WorkflowService = Depends(workflow_service),
):
    return {"items": await service.list(tenant_id)}


@router.post("")
async def create_workflow(
    payload: CreateWorkflowPayload,
    tenant_id: int = 1,
    service: WorkflowService = Depends(workflow_service),
):
    try:
        return await service.create(tenant_id, payload.name, payload.nodes, payload.edges)
    except WorkflowNameConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: int,
    service: WorkflowService = Depends(workflow_service),
):
    try:
        return await service.get(workflow_id)
    except WorkflowNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{workflow_id}")
async def save_workflow(
    workflow_id: int,
    payload: SaveWorkflowPayload,
    service: WorkflowService = Depends(workflow_service),
):
    try:
        await service.save(
            workflow_id,
            name=payload.name,
            status=payload.status,
            nodes=payload.nodes,
            edges=payload.edges,
        )
        return {"ok": True}
    except WorkflowNameConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: int,
    payload: RunWorkflowPayload,
    service: WorkflowService = Depends(workflow_service),
):
    events = service.run(workflow_id, {"input": payload.input, "user_id": payload.user_id})
    return StreamingResponse(_sse(events), media_type="text/event-stream")


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    service: WorkflowService = Depends(workflow_service),
):
    await service.delete(workflow_id)
    return {"ok": True}
