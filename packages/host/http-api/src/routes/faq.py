from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile

from agent_platform_faq import (
    FAQBackfillResult,
    FAQCreate,
    FAQImportResult,
    FAQMatchRequest,
    FAQMatchResponse,
    FAQResponse,
    FAQService,
    FAQUpdate,
    FAQVectorizeResult,
)

router = APIRouter(prefix="/api/faqs", tags=["FAQ"])


def faq_service(request: Request) -> FAQService:
    service = getattr(request.app.state, "faq", None)
    if service is None:
        raise HTTPException(404, "faq plugin is not enabled")
    return service


@router.get("")
def list_faqs(
    tag: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> dict:
    rows, total = service.list(x_tenant_id, tag=tag, page=page, size=size)
    return {"items": rows, "total": total, "page": page, "size": size}


@router.post("", status_code=201)
def create_faq(
    body: FAQCreate,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQResponse:
    return FAQResponse(**service.create(
        x_tenant_id, body.question, body.answer, body.tags, vectorize=body.vectorize,
    ))


@router.get("/{faq_id}")
def get_faq(
    faq_id: int,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQResponse:
    row = service.get(x_tenant_id, faq_id)
    if not row:
        raise HTTPException(404, "FAQ 不存在")
    return FAQResponse(**row)


@router.put("/{faq_id}")
def update_faq(
    faq_id: int,
    body: FAQUpdate,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQResponse:
    row = service.update(x_tenant_id, faq_id, **body.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(404, "FAQ 不存在")
    return FAQResponse(**row)


@router.delete("/{faq_id}", status_code=204)
def delete_faq(
    faq_id: int,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
):
    if not service.delete(x_tenant_id, faq_id):
        raise HTTPException(404, "FAQ 不存在")


@router.post("/{faq_id}/vectorize")
def vectorize_faq(
    faq_id: int,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQVectorizeResult:
    ok, error = service.vectorize(x_tenant_id, faq_id)
    return FAQVectorizeResult(faq_id=faq_id, success=ok, error=error)


@router.post("/backfill")
def backfill_faqs(
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQBackfillResult:
    return FAQBackfillResult(**service.backfill(x_tenant_id))


@router.post("/match")
def match_faq(
    body: FAQMatchRequest,
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQMatchResponse:
    result = service.match(x_tenant_id, body.question, body.direct_threshold)
    if result:
        faq = FAQResponse(**{key: value for key, value in result.items() if not key.startswith("_")})
        return FAQMatchResponse(
            matched=True,
            faq=faq,
            score=result.get("_score", 0),
            tier=result.get("_tier", ""),
        )
    return FAQMatchResponse(matched=False, faq=None, score=0, tier="none")


@router.post("/import")
def import_faqs(
    file: UploadFile = File(...),
    x_tenant_id: int = Header(alias="X-Tenant-ID"),
    service: FAQService = Depends(faq_service),
) -> FAQImportResult:
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "只支持 CSV 文件")
    return service.import_csv(x_tenant_id, file.file.read())
