"""POI 底库种子存储层（外部源骨架导入）.

铁律（DESIGN/feature_gap_and_dev_plan_2026-10-23.md §4.2）：外部源
（ChinaTravel/OSM/5A）只写「骨架」——名称/坐标/类别；时间敏感字段
（hours/price/duration/phone）绝不在此层写，只信后续高德/携程回源链
（app.jobs.refresh_pois → poi_details store）。判重键
(source, source_poi_id)，已存在的行不覆盖任何字段。DB 异常降级为
log warning + "skipped"，导入 job 继续跑。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.services.coords import make_point, wgs84_to_gcj02

logger = logging.getLogger(__name__)

#: 中文/OSM 原始类别 → 受控英文类别（精确匹配层）
CATEGORY_MAP: dict[str, str] = {
    # ChinaTravel type 值
    "博物馆/纪念馆": "museum",
    "公园/广场": "park",
    "历史遗迹": "historic",
    "寺庙/教堂": "temple",
    "自然风光": "nature",
    "游乐园": "theme_park",
    "动物园/植物园": "zoo",
    "观景台/地标": "viewpoint",
    "文化村/古镇": "ancient_town",
    "其他": "other",
    # OSM tourism/leisure 值
    "attraction": "attraction",
    "museum": "museum",
    "gallery": "gallery",
    "zoo": "zoo",
    "theme_park": "theme_park",
    "viewpoint": "viewpoint",
    "ruins": "ruins",
    "castle": "castle",
    "memorial": "memorial",
    "temple": "temple",
    "church": "church",
    "park": "park",
    "garden": "garden",
}


def normalize_category(raw: str | None) -> str | None:
    """原始类别 → 受控英文类别；先精确后包含，匹配不上返回 None."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    hit = CATEGORY_MAP.get(text) or CATEGORY_MAP.get(text.lower())
    if hit is not None:
        return hit
    lowered = text.lower()
    best: tuple[int, str] | None = None  # (命中词长度, 受控类别)
    for key, target in CATEGORY_MAP.items():
        for part in key.split("/"):  # 「博物馆/纪念馆」拆词参与包含匹配
            pl = part.lower()
            if (pl in lowered or lowered in pl) and (best is None or len(pl) > best[0]):
                best = (len(pl), target)
    return best[1] if best else None


def seed_upsert(
    session_factory: Callable[[], Any],
    model: Any,  # Poi 或 Restaurant
    *,
    source: str,
    source_poi_id: str,
    city: str,
    name_zh: str,
    category: str | None = None,
    lonlat: tuple[float, float] | None = None,
    wgs84_lonlat: tuple[float, float] | None = None,
    name_en: str | None = None,
    origin: str | None = None,
) -> str:
    """骨架 upsert，返回 "created" | "exists" | "skipped".

    存在同 (source, source_poi_id) 行则不覆盖任何字段（"exists"）；
    空 name_zh 或 DB 异常返回 "skipped"（job 继续）。city 统一去「市」
    后缀；category 经 normalize_category 归一（Poi→category，
    Restaurant→cuisine）；location 恒存 GCJ-02，仅给 WGS84 时自动
    派生，wgs84_location 存原始 WGS84。时间敏感字段（hours/price/
    duration/phone）绝不在此层写。
    """
    name_zh = (name_zh or "").strip()
    if not name_zh:
        return "skipped"
    city = (city or "").strip().removesuffix("市")
    name_en = (name_en or "").strip() or None
    cat = normalize_category(category)
    if lonlat is None and wgs84_lonlat is not None:
        lonlat = wgs84_to_gcj02(*wgs84_lonlat)
    try:
        with session_factory() as session:
            row = (
                session.query(model)
                .filter_by(source=source, source_poi_id=source_poi_id)
                .one_or_none()
            )
            if row is not None:
                return "exists"  # 骨架不覆盖：已有行原样保留
            kwargs: dict[str, Any] = {
                "id": uuid4(),
                "source": source,
                "source_poi_id": source_poi_id,
                "city": city,
                "name_zh": name_zh,
                "status": "active",
                "origin": origin or source,
            }
            if cat is not None:
                if hasattr(model, "category"):
                    kwargs["category"] = cat
                elif hasattr(model, "cuisine"):
                    kwargs["cuisine"] = cat
            if name_en is not None:
                kwargs["name_en"] = name_en
            if lonlat is not None:
                kwargs["location"] = make_point(*lonlat)
            if wgs84_lonlat is not None:
                kwargs["wgs84_location"] = make_point(*wgs84_lonlat)
            session.add(model(**kwargs))
            session.commit()
        return "created"
    except Exception:
        logger.warning(
            "poi_seed: seed_upsert failed (%s/%s)",
            source,
            source_poi_id,
            exc_info=True,
        )
        return "skipped"


def mark_status(
    session_factory: Callable[[], Any],
    model: Any,
    source: str,
    source_poi_id: str,
    status: str,
) -> bool:
    """置行 status（如 OSM delete → "inactive"）；行不存在返回 False."""
    try:
        with session_factory() as session:
            row = (
                session.query(model)
                .filter_by(source=source, source_poi_id=source_poi_id)
                .one_or_none()
            )
            if row is None:
                return False
            row.status = status
            session.commit()
        return True
    except Exception:
        logger.warning(
            "poi_seed: mark_status failed (%s/%s)",
            source,
            source_poi_id,
            exc_info=True,
        )
        return False
