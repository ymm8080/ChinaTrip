from fastapi import APIRouter

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    # llm_backend 暴露给监控：mock 出现在生产=对话编辑全废（2026-10-30
    # 事故），/health 一眼可见，不用翻 .env。
    return {
        "status": "ok",
        "service": "chinatrip-api",
        "version": __version__,
        "llm_backend": get_settings().llm_backend,
    }
