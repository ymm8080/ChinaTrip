# -*- coding: utf-8 -*-
"""订单回填 API（设计 v2.4 §6.11）：三层管道的 HTTP 面。

粘贴回填为主（paste-return）/ 返回询问为辅（前端拉 status=opened 列表）/
联盟订单同步自动（alliance-sync，MVP 确定性 mock）。

错误映射：HandoffNotFoundError → 404 handoff_not_found；
InvalidTransitionError → 422 invalid_transition（状态机守卫）。
路由不注册进 app/main.py —— 由编排层接线（itineraries.py 同款约定）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.backfill import (
    AllianceFeedItem,
    HandoffNotFoundError,
    HandoffRecord,
    HandoffStore,
    InvalidTransitionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backfill", tags=["backfill"])

_ACTION_TYPE_PATTERN = "^(train|flight|hotel)$"
_CHANNEL_PATTERN = "^(12306|qunar|ctrip|meituan)$"
_STATUS_PATTERN = "^(opened|user_confirmed|alliance_verified|settled|returned)$"


class CreateHandoffRequest(BaseModel):
    """跳转埋点（用户点渠道卡时前端调）：只登记 opened，不推进状态。"""

    action_type: str = Field(pattern=_ACTION_TYPE_PATTERN)
    channel: str = Field(pattern=_CHANNEL_PATTERN)
    url: str = Field(min_length=1, max_length=2048)
    refund_summary: str | None = Field(default=None, max_length=512)


class PasteReturnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ManualConfirmRequest(BaseModel):
    order_ref: str = Field(min_length=1, max_length=64)


class AllianceSyncRequest(BaseModel):
    orders: list[AllianceFeedItem] = Field(default_factory=list)


# --- 依赖工厂（translate.py 进程级懒单例同款） -------------------------------

_store_singleton: HandoffStore | None = None


def get_handoff_store() -> HandoffStore:
    """进程级懒单例：回填状态必须跨请求存活（translate 短语缓存同款理由）。"""
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = HandoffStore()
    return _store_singleton


# --- routes ------------------------------------------------------------------


@router.post("/handoffs", status_code=201)
async def create_handoff(
    request: CreateHandoffRequest,
    store: HandoffStore = Depends(get_handoff_store),
) -> HandoffRecord:
    return store.create(
        action_type=request.action_type,
        channel=request.channel,
        url=request.url,
        refund_summary=request.refund_summary,
    )


@router.post("/handoffs/{record_id}/paste-return")
async def paste_return(
    record_id: str,
    request: PasteReturnRequest,
    store: HandoffStore = Depends(get_handoff_store),
) -> dict:
    try:
        record, parsed, applied, reason = store.apply_paste_return(
            record_id, request.text
        )
    except HandoffNotFoundError:
        raise HTTPException(status_code=404, detail="handoff_not_found") from None
    except InvalidTransitionError:
        raise HTTPException(status_code=422, detail="invalid_transition") from None
    # 铁律 21 口径：日志只带聚合值，不带粘贴原文。
    logger.info(
        "backfill_paste_return applied=%s confidence=%.2f", applied, parsed.confidence
    )
    body: dict = {"record": record, "parsed": parsed, "applied": applied}
    if reason is not None:
        body["reason"] = reason
    return body


@router.post("/handoffs/{record_id}/undo")
async def undo_handoff(
    record_id: str,
    store: HandoffStore = Depends(get_handoff_store),
) -> HandoffRecord:
    try:
        return store.undo(record_id)
    except HandoffNotFoundError:
        raise HTTPException(status_code=404, detail="handoff_not_found") from None
    except InvalidTransitionError:
        raise HTTPException(status_code=422, detail="invalid_transition") from None


@router.post("/handoffs/{record_id}/manual")
async def manual_confirm(
    record_id: str,
    request: ManualConfirmRequest,
    store: HandoffStore = Depends(get_handoff_store),
) -> HandoffRecord:
    try:
        return store.apply_manual(record_id, request.order_ref)
    except HandoffNotFoundError:
        raise HTTPException(status_code=404, detail="handoff_not_found") from None
    except InvalidTransitionError:
        raise HTTPException(status_code=422, detail="invalid_transition") from None


@router.get("/handoffs")
async def list_handoffs(
    status: str | None = Query(default=None, pattern=_STATUS_PATTERN),
    store: HandoffStore = Depends(get_handoff_store),
) -> list[HandoffRecord]:
    return store.list_records(status)


@router.post("/alliance-sync")
async def alliance_sync(
    request: AllianceSyncRequest,
    store: HandoffStore = Depends(get_handoff_store),
) -> dict:
    result = store.alliance_sync(request.orders)
    logger.info(
        "backfill_alliance_sync matched=%d advanced=%d skipped=%d",
        result["matched"],
        len(result["advanced"]),
        result["skipped"],
    )
    return result
