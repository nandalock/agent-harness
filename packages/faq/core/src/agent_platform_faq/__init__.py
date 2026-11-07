"""FAQ plugin: CRUD, pg_trgm matching and embedding backfill."""
from .contracts import FAQ
from .models import (
    FAQBackfillResult,
    FAQCreate,
    FAQImportResult,
    FAQImportRow,
    FAQMatchRequest,
    FAQMatchResponse,
    FAQRagRequest,
    FAQRagResponse,
    FAQResponse,
    FAQUpdate,
    FAQVectorizeResult,
)
from .plugin import FaqConfig, FaqPlugin
from .service import FAQService

__all__ = [
    "FAQ",
    "FAQBackfillResult",
    "FAQCreate",
    "FAQImportResult",
    "FAQImportRow",
    "FAQMatchRequest",
    "FAQMatchResponse",
    "FAQRagRequest",
    "FAQRagResponse",
    "FAQResponse",
    "FAQService",
    "FAQUpdate",
    "FAQVectorizeResult",
    "FaqConfig",
    "FaqPlugin",
]
