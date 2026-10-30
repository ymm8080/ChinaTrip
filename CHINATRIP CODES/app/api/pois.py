"""POI detail API (v2.5 POI 底库新字段) — read-only enrichment feed for
the H5 site brief bubble (intro / photo / badges / phone, each with a
field-level source label). Lookup: city (「市」-tolerant) + name_zh exact,
fuzzy (spaces / parenthesized content stripped, contains) as fallback.
Pure DB read — the geography column is never loaded (no coordinate
serialization pitfalls; the H5 does not use coordinates).

预约/订票出参（2026-10-29 读侧接线）：reservation_*/booking_url/ticket_*
库列优先（refresh_reservation_rules 周检回写 / ctrip 刷新链），RESERVATION_V0
名单兜底——与 plan._reservation_hint 同语义（库列有值不出名单提示），
详情气泡从此与行程卡/抢票日历共用同一份预约口径。
"""

import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, load_only, sessionmaker

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_details import apply_tier_tag
from app.services.reservation_seeds import (
    FOREIGNER_TIP,
    FOREIGNER_TIP_EN,
    RESERVATION_V0,
    reservation_meta_for,
)

router = APIRouter(prefix="/api/pois", tags=["pois"])


def get_poi_session_factory() -> sessionmaker[Session]:
    """Indirection over db.get_session_factory so tests can override
    (dependency_overrides) without touching the lru_cache'd engine."""
    return get_session_factory()


class PoiDetail(BaseModel):
    poi_id: str | None = None
    source: str | None = None
    origin: str | None = None
    city: str | None = None
    name_zh: str | None = None
    name_en: str | None = None
    category: str | None = None
    status: str | None = None
    address: str | None = None
    opening_hours: str | None = None
    hours_source: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    rating_source: str | None = None
    tags: list | None = None
    tags_source: str | None = None
    intro: str | None = None
    intro_source: str | None = None
    photos: list | None = None
    photos_source: str | None = None
    best_visit_time: str | None = None
    best_visit_time_source: str | None = None
    suggested_duration_min: int | None = None
    # 预约/订票情况（G1）：库列优先，名单 v0 兜底；note 双语并出（H5 I18N.pick）
    reservation_required: bool | None = None
    reservation_advance_days: int | None = None
    reservation_release_time: str | None = None
    reservation_note: str | None = None
    reservation_note_en: str | None = None
    foreigner_tip: str | None = None
    foreigner_tip_en: str | None = None
    booking_url: str | None = None
    ticket_price_min: float | None = None
    ticket_price_max: float | None = None
    ticket_source: str | None = None


# Columns actually read (response fields + id for poi_id). Deliberately
# excludes location / wgs84_location / hours_updated_at — nothing in the
# response needs geometry, and loading it invites serialization bugs.
_COLS = (
    Poi.id,
    Poi.source,
    Poi.origin,
    Poi.city,
    Poi.name_zh,
    Poi.name_en,
    Poi.category,
    Poi.status,
    Poi.address,
    Poi.opening_hours,
    Poi.hours_source,
    Poi.phone,
    Poi.website,
    Poi.rating,
    Poi.rating_source,
    Poi.tags,
    Poi.tags_source,
    Poi.intro,
    Poi.intro_source,
    Poi.photos,
    Poi.photos_source,
    Poi.best_visit_time,
    Poi.best_visit_time_source,
    Poi.suggested_duration_min,
    Poi.reservation_required,
    Poi.reservation_advance_days,
    Poi.booking_url,
    Poi.ticket_price_min,
    Poi.ticket_price_max,
    Poi.ticket_source,
)


def _city_variants(city: str) -> list[str]:
    """「重庆」vs「重庆市」— DB rows and callers use both forms."""
    c = (city or "").strip()
    if not c:
        return []
    bare = c[:-1] if c.endswith("市") else c
    return sorted({bare, bare + "市"})


def _norm_name(name: str) -> str:
    """Fuzzy key: drop parenthesized segments and all whitespace."""
    return re.sub(r"\s+", "", re.sub(r"[（(][^（）()]*[)）]", "", name))


def _seed_meta_for(name: str) -> dict | None:
    """RESERVATION_V0 名单命中：精确名优先，_same_site 同款互含容错
    （「故宫博物院」⊂ 名单键「故宫」）。与 plan._reservation_hint 的兜底
    语义一致——去动词前缀那一半只服务愿望短语，库内 canonical 名用不到。"""
    meta = reservation_meta_for(name)
    if meta:
        return meta
    n = _norm_name(name or "")
    if len(n) < 2:
        return None
    for seed_name, m in RESERVATION_V0.items():
        s = _norm_name(seed_name)
        if (s in n or n in s) and min(len(s), len(n)) >= 2:
            return m
    return None


def _booking_fields(row: Poi) -> dict:
    """预约/订票出参组：库列优先，名单 v0 兜底（plan._reservation_hint
    同语义：库列有值不出名单提示，note 不以名单覆盖）。release 时刻无库列、
    恒由名单补，库列缺天数而名单命中同馆时天数照补（同一官方口径）；
    名单口径 "00:00"=未注明 → 出参 None。foreigner_tip 预约成立即挂
    （外籍小程序常败是 G1 第一痛）。"""
    seed = _seed_meta_for(row.name_zh) or {}
    db_first = bool(row.reservation_required or row.reservation_advance_days)
    rel = seed.get("release")
    required = bool(row.reservation_required or row.reservation_advance_days or seed)
    return {
        "reservation_required": required or None,
        "reservation_advance_days": (
            row.reservation_advance_days
            if row.reservation_advance_days is not None
            else seed.get("days")
        ),
        "reservation_release_time": rel if rel and rel != "00:00" else None,
        "reservation_note": None if db_first else seed.get("note"),
        "reservation_note_en": None if db_first else seed.get("note_en"),
        "foreigner_tip": FOREIGNER_TIP if required else None,
        "foreigner_tip_en": FOREIGNER_TIP_EN if required else None,
        "booking_url": row.booking_url,
    }


def _to_model(row: Poi, tags: list | None = None) -> PoiDetail:
    rating = row.rating  # Numeric → Decimal on real rows
    tmin, tmax = row.ticket_price_min, row.ticket_price_max
    return PoiDetail(
        poi_id=str(row.id) if row.id else None,
        source=row.source,
        origin=row.origin,
        city=row.city,
        name_zh=row.name_zh,
        name_en=row.name_en,
        category=row.category,
        status=row.status,
        address=row.address,
        opening_hours=row.opening_hours,
        hours_source=row.hours_source,
        phone=row.phone,
        website=row.website,
        rating=float(rating) if rating is not None else None,
        rating_source=row.rating_source,
        tags=tags if tags is not None else row.tags,
        tags_source=row.tags_source,
        intro=row.intro,
        intro_source=row.intro_source,
        photos=row.photos,
        photos_source=row.photos_source,
        best_visit_time=row.best_visit_time,
        best_visit_time_source=row.best_visit_time_source,
        suggested_duration_min=row.suggested_duration_min,
        **_booking_fields(row),
        ticket_price_min=float(tmin) if tmin is not None else None,
        ticket_price_max=float(tmax) if tmax is not None else None,
        ticket_source=row.ticket_source,
    )


@router.get("/detail", response_model=PoiDetail)
async def poi_detail(
    city: str,
    name: str,
    factory: Callable[[], Session] = Depends(get_poi_session_factory),
) -> PoiDetail:
    variants = _city_variants(city)
    wanted = name.strip()
    try:
        with factory() as session:
            q = session.query(Poi).options(load_only(*_COLS))
            if variants:
                q = q.filter(Poi.city.in_(variants))
            row = q.filter(Poi.name_zh == wanted).first()
            if row is None:
                norm = _norm_name(wanted)
                if norm:
                    fq = session.query(Poi).options(load_only(*_COLS))
                    if variants:
                        fq = fq.filter(Poi.city.in_(variants))
                    row = fq.filter(Poi.name_zh.contains(norm)).first()
            if row is None:
                raise HTTPException(status_code=404, detail="poi not found")
            # 读侧 tier 接线（2026-10-28）：5A/unesco 名单行 tags 列 0 覆盖
            # （名单以骨架行存在），H5 徽章按行内 tags 永远看不到层级——出参
            # 前按 共用 hit_tier 判级并入 tags；已有层级标签的行跳过名单查询。
            tags = list(row.tags or [])
            if not {"unesco", "5a", "4a", "3a", "intl"} & set(tags):
                heritage = [
                    (hz, 4 if src == "unesco" else 3)
                    for hz, src in session.query(Poi.name_zh, Poi.source)
                    .filter(Poi.source.in_(["unesco", "5a"]))
                    .all()
                ]
                h = {"name": row.name_zh, "source": row.source, "tags": tags}
                apply_tier_tag(h, heritage)
                tags = h["tags"]
            return _to_model(row, tags=tags)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="poi store unavailable") from None
