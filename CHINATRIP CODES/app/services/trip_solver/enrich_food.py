"""CP-SAT 餐饮候选搜索补位（R13q / gap #1）。

legacy 的 `_assemble_plan` 会按餐窗调用 `recommend_restaurants`（DB 荐点
`recommendation_food_in_city` + amap live 检索 + detour 排序）产真餐卡；
CP-SAT 此前只把 store 池里已有的 food 行顶成命名餐卡，引擎自己不搜餐厅。
本模块在**求解之前**（inputs 侧）把同一批候选并进 FactSnapshot：模型
C-09 见得到真餐厅即可直接绑定，`assembly/meals.py` 的命名餐卡链无需改动。

设计约束：
- 纯函数 + 注入依赖（async 调用方预取行，sync 快照构造器只吃行）；
- 任何失败降级为空列表（绝不拦生成），与 legacy `search_restaurants` 契约一致；
- 搜索只做一次每城，全行程上限 3 次（legacy `_assemble_plan` 同款预算）；
- 复用 `candidate_from_poi_dict` 的时段/菜系/时长口径，不重复实现餐饮规则。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_SEARCHES = 3  # legacy _assemble_plan `searches < 3` 同款
PER_CITY_LIMIT = 6  # 每城入池上限（餐类候选稀释防护）


async def prefetch_food_rows(
    *,
    cities: list[str],
    amap_client=None,
    store=None,
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """预取餐饮候选行（async，供 api 缝在 to_thread 之前 await）。

    返回 `_row_to_candidate` 可直接吃的 POI 行 dict；`category="food"` +
    `meal_slot` 由 live.snapshot_from_request 统一标注（`food_rows` 入参）。
    `enabled=False` → 零外呼、零 DB 读（与 legacy `plan_restaurant_search_enabled`
    默认关同口径）。amap/client 缺失或异常一律降级空列表。
    """
    if not enabled or not cities:
        return []
    rows: list[dict[str, Any]] = []
    searches = 0
    for city in cities:
        if searches >= MAX_SEARCHES:
            break
        # 1) DB 荐点（legacy _rec_food 同源；同步 DB 调用放线程外，量小）
        if store is not None:
            try:
                db_hits = store.recommendation_food_in_city(city, limit=PER_CITY_LIMIT)
                for raw in db_hits:
                    hit = dict(raw)
                    hit["city"] = city
                    hit["meal_slot"] = "any"
                    rows.append(hit)
            except Exception:
                logger.warning("enrich_food: DB rec food failed for %s", city)
        # 2) amap live 检索（legacy search_restaurants 同源；仅 key 可用时）
        if amap_client is not None:
            try:
                from app.services.restaurants import search_restaurants

                hits = await search_restaurants(amap_client, city, limit=PER_CITY_LIMIT)
                searches += 1
                for cand in hits:
                    loc = cand.location
                    rows.append(
                        {
                            "name": cand.name,
                            "source_poi_id": cand.poi_id,
                            "category": "food",
                            "city": city,
                            "address": cand.address,
                            "opening_hours": cand.opening_hours,
                            "rating": cand.rating,
                            "location": (
                                (loc.lon, loc.lat) if loc is not None else None
                            ),
                            "tags": list(cand.tags),
                            "best_visit_time": None,
                            "suggested_duration_min": cand.duration_hint,
                            "meal_slot": "any",
                            "rec_tagged": cand.rec_tagged,
                        }
                    )
            except Exception:
                logger.warning("enrich_food: amap search failed for %s", city)
    return rows
