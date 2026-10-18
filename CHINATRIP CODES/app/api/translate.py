"""POST /api/v1/translate — translation fast lane (design v2.0 §6.10/§6.12).

Fast lane, NOT an agent loop: one Flash chat call, or zero calls on a
phrase-cache hit. The API layer owns request validation (device id,
length, language pair); the service re-asserts defensively.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.llm import get_flash_adapter
from app.services.llm.zhipu import LLMError
from app.services.translate import TranslationService, UnsupportedLanguageError

router = APIRouter(prefix="/api/v1", tags=["translate"])
logger = logging.getLogger(__name__)


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1)
    source_lang: str
    target_lang: str


_service_singleton: TranslationService | None = None


def get_translation_service(
    settings: Settings = Depends(get_settings),
) -> TranslationService:
    """Process-wide singleton: FastAPI re-evaluates plain dependencies per
    request, and a fresh service per request would empty the phrase cache
    every time — the cache must persist across requests (§6.10)."""
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = TranslationService(
            get_flash_adapter(settings),
            cache_max_entries=settings.translate_phrase_cache_max_entries,
        )
    return _service_singleton


@router.post("/translate")
async def translate_endpoint(
    request: TranslateRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TranslationService = Depends(get_translation_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    if len(request.text) > settings.translate_max_chars:
        raise HTTPException(status_code=422, detail="text_too_long")
    try:
        result = await service.translate(
            request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=422, detail="unsupported_language") from exc
    except ValueError as exc:
        # Defensive: service-layer re-assertion (empty/oversized text).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("translate llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    return {
        "translated": result.translated,
        "cached": result.cached,
        "model": result.model,
        "usage": {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out},
    }
