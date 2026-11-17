# -*- coding: utf-8 -*-
"""手输酒店名·验证搜索（2026-11-07 每晚酒店卡：用户指令「OR INPUT
MANUALLY BY USER, NEED TO VERIFY THE NAME AND SHOW ADDRESS ACCORDINGLY」）。

每晚酒店卡 ✏️ 手输名称 → 本路由 live 检索（复用规划页目的地搜索的
vendor 检索链，amap>tencent>baidu）→ 下拉以「名称 + 地址」展示 → 选中
经 plan set-hotel 写回。酒店类目命中排前；key 永不出服务端（铁律 22）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.amap import _SEARCH_LATCH, get_search_chain
from app.config import Settings, get_settings
from app.services.amap_client import AmapClient, AmapTimeoutError
from app.services.map_provider import map_ready
from app.services.vendor_chain import run_vendor_chain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hotels", tags=["hotels"])

# 酒店类目/名称标记：amap category 含「住宿服务」为准；图商类目缺失时
# 按名称常见宿字样兜底（不含「饭店」——餐馆歧义大）
_HOTEL_CATEGORY_MARKS = ("住宿", "hotel")
_HOTEL_NAME_MARKS = ("酒店", "宾馆", "民宿", "客栈", "招待所", "公寓")


def _is_hotel_hit(item: dict) -> bool:
    category = (item.get("category") or "").lower()
    if any(mark in category for mark in _HOTEL_CATEGORY_MARKS):
        return True
    name = (item.get("name") or "").lower()
    return any(mark in name for mark in _HOTEL_NAME_MARKS)


def _project(item: dict, is_hotel: bool) -> dict:
    loc = item.get("location")
    return {
        "name": item.get("name"),
        "name_en": item.get("ename"),
        "city": item.get("city"),
        "category": item.get("category"),
        "address": item.get("address"),
        "location": (
            {"lon": loc["lon"], "lat": loc["lat"]}
            if isinstance(loc, dict) and "lon" in loc and "lat" in loc
            else None
        ),
        "source_poi_id": item.get("source_poi_id"),
        "opening_hours": item.get("opening_hours"),
        "rating": item.get("rating"),
        "is_hotel": is_hotel,
    }


async def search_hotel_candidates(
    chain: list[AmapClient],
    settings: Settings,
    keywords: str,
    city: str | None,
    *,
    page: int = 1,
) -> list[dict]:
    """检索链搜名并投影（酒店类目优先，同组内保持图商序）。

    set-hotel 服务端验证与 /search 端点共用；全链失败抛 HTTPException
    （504/502），未配置 503——与 /api/v1/amap/poi/search 同口径。
    """
    if not map_ready(settings) or not chain:
        raise HTTPException(status_code=503, detail="amap_not_configured")
    result = await run_vendor_chain(
        chain,
        lambda c: c.search_poi(keywords, city=city, page=page),
        latch=_SEARCH_LATCH,
        function="search",
    )
    if isinstance(result, AmapTimeoutError):
        raise HTTPException(status_code=504, detail="amap_timeout") from result
    if result is None or isinstance(result, Exception):
        logger.warning("hotels/search all vendors failed: %s", result)
        raise HTTPException(status_code=502, detail="amap_error") from result
    hits = [_project(i, _is_hotel_hit(i)) for i in result]
    hits.sort(key=lambda h: not h["is_hotel"])  # 稳定排序：酒店类目置顶
    return hits


@router.get("/search")
async def search_hotels(
    keywords: str = Query(min_length=1, max_length=64),
    city: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    chain: list[AmapClient] = Depends(get_search_chain),
) -> dict:
    """手输酒店名验证搜索：下拉候选带名称+地址（验证展示），选中后由
    plan set-hotel 原位写回每晚酒店卡。"""
    items = await search_hotel_candidates(chain, settings, keywords, city, page=page)
    return {"items": items, "page": page}
