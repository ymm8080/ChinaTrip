"""互动闭环端点（DESIGN §4，2026-10-25）。

卡片 👍/👎（②）、行中打卡（③）、行后点评（④）、站点反馈聚合读
（「去过的人说」）。零 LLM、零外呼——纯反馈落地。👎 的 unwanted
回写走既有 trip-items 端点，此处只计数（前端两条调用都发）。
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.poi_feedback import (
    REVIEW_TAGS,
    PoiFeedbackStore,
    get_poi_feedback_store,
)

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class VoteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    up: bool


class VisitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)


class ReviewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    text: str | None = Field(default=None, max_length=500)


@router.post("/vote")
async def vote(
    request: VoteRequest,
    store: PoiFeedbackStore = Depends(get_poi_feedback_store),
) -> dict:
    return store.vote(request.name, request.city, up=request.up)


@router.post("/visit")
async def visit(
    request: VisitRequest,
    store: PoiFeedbackStore = Depends(get_poi_feedback_store),
) -> dict:
    return store.visit(request.name, request.city)


@router.post("/review", status_code=201)
async def review(
    request: ReviewRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PoiFeedbackStore = Depends(get_poi_feedback_store),
) -> dict:
    bad_tags = [t for t in (request.tags or []) if t not in REVIEW_TAGS]
    if bad_tags:
        raise HTTPException(status_code=422, detail="unknown_tags")
    try:
        return store.add_review(
            request.name,
            request.city,
            rating=request.rating,
            tags=request.tags,
            text=request.text,
            device_id=x_device_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/poi")
async def poi_feedback(
    name: str,
    city: str | None = None,
    store: PoiFeedbackStore = Depends(get_poi_feedback_store),
) -> dict:
    return {
        "name": (name or "").strip(),
        "city": (city or "").strip().removesuffix("市"),
        "stats": store.stats_for(name, city),
        "recent_reviews": store.recent_reviews(name, city),
    }
