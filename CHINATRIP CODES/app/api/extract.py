"""POST /api/v1/extract — anonymous-phase trip-text parsing.

Iron rule 14: the parsing stage has ZERO write permission — no DB access
anywhere in this code path.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.extraction import ExtractionService
from app.services.llm import get_llm_adapter
from app.services.llm.zhipu import LLMError

router = APIRouter(prefix="/api/v1", tags=["extract"])
logger = logging.getLogger(__name__)


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1)
    lang: str = "zh"


def get_extraction_service(
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    return ExtractionService(get_llm_adapter(settings))


@router.post("/extract")
async def extract_endpoint(
    request: ExtractRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: ExtractionService = Depends(get_extraction_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    if len(request.text) > settings.extract_max_text_chars:
        raise HTTPException(status_code=422, detail="text_too_long")
    try:
        result = await service.run(request.text, request.lang)
    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("extract llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    threshold = settings.extract_confidence_threshold
    return {
        "candidates": [
            {
                "name": c.name,
                "city": c.city,
                "category": c.category,
                "confidence": c.confidence,
                "poi_id": c.poi_id,
                "status": (
                    "confirmed" if c.confidence >= threshold else "pending_confirmation"
                ),
            }
            for c in result.candidates
        ],
        "assumptions": result.assumptions,
        "quarantined": result.quarantined,
        "model": result.model,
        "usage": {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out},
    }
