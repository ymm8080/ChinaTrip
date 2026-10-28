"""POI detail API (v2.5 POI 底库新字段) — read-only enrichment feed for
the H5 site brief bubble (intro / photo / badges / phone, each with a
field-level source label). Lookup: city (「市」-tolerant) + name_zh exact,
fuzzy (spaces / parenthesized content stripped, contains) as fallback.
Pure DB read — the geography column is never loaded (no coordinate
serialization pitfalls; the H5 does not use coordinates).
"""

import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, load_only, sessionmaker

from app.db import get_session_factory
from app.models import Poi

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


def _to_model(row: Poi) -> PoiDetail:
    rating = row.rating  # Numeric → Decimal on real rows
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
        tags=row.tags,
        tags_source=row.tags_source,
        intro=row.intro,
        intro_source=row.intro_source,
        photos=row.photos,
        photos_source=row.photos_source,
        best_visit_time=row.best_visit_time,
        best_visit_time_source=row.best_visit_time_source,
        suggested_duration_min=row.suggested_duration_min,
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
    except Exception:
        raise HTTPException(status_code=503, detail="poi store unavailable") from None
    if row is None:
        raise HTTPException(status_code=404, detail="poi not found")
    return _to_model(row)
