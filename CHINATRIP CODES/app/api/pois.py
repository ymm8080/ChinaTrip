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

import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, load_only, sessionmaker

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi, Restaurant
from app.services.amap_client import AmapClient
from app.services.poi_details import PoiDetailStore, apply_tier_tag
from app.services.poi_details import get_poi_detail_store as _poi_store_singleton
from app.services.poi_photos import fetch_photo_chain, in_cooldown
from app.services.reservation_seeds import (
    FOREIGNER_TIP,
    FOREIGNER_TIP_EN,
    RESERVATION_V0,
    reservation_meta_for,
)

logger = logging.getLogger(__name__)

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
    intro_en: str | None = None
    intro_source: str | None = None
    # P7b 证据链透出（2026-11-10）：UGC/点评综述——enrich 管道
    # （app.jobs.enrich_review_summary / backfill_review_summary）已入库，
    # 本端点纯读侧透出；source（llm/llm_distill）随字段小字标注。
    review_summary: str | None = None
    review_summary_en: str | None = None
    review_summary_source: str | None = None
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
    Poi.intro_en,
    Poi.intro_source,
    Poi.review_summary,
    Poi.review_summary_en,
    Poi.review_summary_source,
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
        intro_en=row.intro_en,
        intro_source=row.intro_source,
        review_summary=row.review_summary,
        review_summary_en=row.review_summary_en,
        review_summary_source=row.review_summary_source,
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


# --- 餐厅回退（2026-11-13 读侧接线）：行程卡餐位/餐厅名同走本气泡，
# 但 pois 表查无（餐厅在独立 restaurants 表）→ 此前 404 静默跳过，
# 照片/简介/米其林徽标永远不可见。pois 未命中时回落 restaurants 表
# （同口径 city 变体 → name_zh 精确 → contains 模糊，active 闸一致），
# 映射进同一 PoiDetail 形状——H5 气泡/找图按钮/死图打点零改动复用。


def _find_restaurant_for_photos(
    session: Session, city: str, wanted: str
) -> Restaurant | None:
    """餐厅侧与 detail 同查找口径（city 变体 → name_zh 精确 → contains）。

    fetch 端点与 detail 回退共用；写回列（photos/photos_source/
    photos_fetched_at/photos_fetch_fail）restaurants 与 pois 同构（0020）。
    """
    variants = _city_variants(city)
    alive = Restaurant.status.is_(None) | (Restaurant.status == "active")
    q = session.query(Restaurant).filter(alive)
    if variants:
        q = q.filter(Restaurant.city.in_(variants))
    row = q.filter(Restaurant.name_zh == wanted).first()
    if row is None:
        norm = _norm_name(wanted)
        if norm:
            fq = session.query(Restaurant).filter(alive)
            if variants:
                fq = fq.filter(Restaurant.city.in_(variants))
            row = fq.filter(Restaurant.name_zh.contains(norm)).first()
    return row


def _restaurant_to_model(row: Restaurant) -> PoiDetail:
    """Restaurant 行 → PoiDetail（仅两表同构字段；预约/订票/点评综述
    列餐厅侧不存在，恒 None）。cuisine 即受控 EN 类别（seed_upsert
    Restaurant→cuisine 同口径），映射进 category 供 H5 复用。"""
    rating = row.rating  # Numeric → Decimal on real rows
    return PoiDetail(
        poi_id=str(row.id) if row.id else None,
        source=row.source,
        origin=row.origin,
        city=row.city,
        name_zh=row.name_zh,
        name_en=row.name_en,
        category=row.cuisine,
        status=row.status,
        address=row.address,
        opening_hours=row.opening_hours,
        hours_source=row.hours_source,
        phone=row.phone,
        website=row.website,
        rating=float(rating) if rating is not None else None,
        rating_source=row.rating_source,
        tags=list(row.tags or []) or None,
        tags_source=row.tags_source,
        intro=row.intro,
        intro_en=row.intro_en,
        intro_source=row.intro_source,
        photos=row.photos,
        photos_source=row.photos_source,
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
            # 退役闸（与主池 poi_details 口径一致）：retired/inactive/duplicate
            # 行不得经详情接口回吐；在册旧卡靠快照展示，404 静默跳过是既有语义
            alive = (Poi.status.is_(None)) | (Poi.status == "active")
            q = session.query(Poi).options(load_only(*_COLS)).filter(alive)
            if variants:
                q = q.filter(Poi.city.in_(variants))
            row = q.filter(Poi.name_zh == wanted).first()
            if row is None:
                norm = _norm_name(wanted)
                if norm:
                    fq = session.query(Poi).options(load_only(*_COLS)).filter(alive)
                    if variants:
                        fq = fq.filter(Poi.city.in_(variants))
                    row = fq.filter(Poi.name_zh.contains(norm)).first()
            if row is None:
                # 餐厅回退（2026-11-13）：行程卡餐位/餐厅名的气泡读侧——
                # pois 查无再查 restaurants，命中即出同形状详情（照片/
                # 简介/米其林徽标）。仍查无才 404（H5 静默跳过语义不变）。
                rrow = _find_restaurant_for_photos(session, city, wanted)
                if rrow is not None:
                    return _restaurant_to_model(rrow)
                raise HTTPException(status_code=404, detail="poi not found")
            # 读侧 tier 接线（2026-10-28）：5A/unesco 名单行 tags 列 0 覆盖
            # （名单以骨架行存在），H5 徽章按行内 tags 永远看不到层级——出参
            # 前按 共用 hit_tier 判级并入 tags；已有层级标签的行跳过名单查询。
            tags = list(row.tags or [])
            if not {"unesco", "5a", "4a", "3a", "intl"} & set(tags):
                heritage = [
                    # 档号随 2026-11-13 名录序（source_tier）：国际站=0、
                    # unesco=1、5a=2——与 catalog_rank 2026-11-13 拍板对齐。
                    (hz, 1 if src == "unesco" else 2)
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


# --- F2 点击回源 / F4 死图上报（DESIGN poi_photos_functional_design 2026-11-11）---


class PhotosFetchRequest(BaseModel):
    city: str
    name: str


class PhotosFetchResponse(BaseModel):
    photos: list = []
    photos_source: str | None = None
    fetched: bool = False


class PhotosDeadReport(BaseModel):
    poi_id: str


def _find_poi_for_photos(session: Session, city: str, wanted: str) -> Poi | None:
    """与 detail 同查找口径（city 变体 → name_zh 精确 → contains 模糊）。"""
    variants = _city_variants(city)
    alive = (Poi.status.is_(None)) | (Poi.status == "active")
    q = session.query(Poi).filter(alive)
    if variants:
        q = q.filter(Poi.city.in_(variants))
    row = q.filter(Poi.name_zh == wanted).first()
    if row is None:
        norm = _norm_name(wanted)
        if norm:
            fq = session.query(Poi).filter(alive)
            if variants:
                fq = fq.filter(Poi.city.in_(variants))
            row = fq.filter(Poi.name_zh.contains(norm)).first()
    return row


@router.post("/photos/fetch", response_model=PhotosFetchResponse)
async def photos_fetch(
    req: PhotosFetchRequest,
    factory: Callable[[], Session] = Depends(get_poi_session_factory),
) -> PhotosFetchResponse:
    """点击触发确定性回源（幂等）。库有图直接回；冷却内回库值不外呼；
    否则走 fetch_photo_chain 链——photos/photos_source 只填空，
    photos_fetched_at 尝试即落戳（拉空也落，防连点烧配额）。失败必须
    留日志（10-25 立规），响应不吐错误细节。"""
    wanted = req.name.strip()
    try:
        with factory() as session:
            row = _find_poi_for_photos(session, req.city, wanted)
            if row is None:
                # 餐厅回退（2026-11-13）：找图按钮对餐位/餐厅名同样成立——
                # restaurants 与 pois 回源列同构（0020），链/写回零分支复用。
                row = _find_restaurant_for_photos(session, req.city, wanted)
            if row is None:
                raise HTTPException(status_code=404, detail="poi not found")
            if row.photos:
                return PhotosFetchResponse(
                    photos=row.photos, photos_source=row.photos_source, fetched=False
                )
            now = datetime.now()
            if in_cooldown(row.photos_fetched_at, now):
                return PhotosFetchResponse(
                    photos=list(row.photos or []),
                    photos_source=row.photos_source,
                    fetched=False,
                )
            photos: list | None = None
            source: str | None = None
            try:
                settings = get_settings()
                amap = (
                    AmapClient(key=settings.amap_api_key, timeout_seconds=10.0)
                    if settings.amap_api_key
                    else None
                )
                photos, source = await fetch_photo_chain(row, amap=amap)
            except Exception:
                logger.warning(
                    "photos_fetch: chain failed, poi=%s city=%s name=%s",
                    row.id,
                    req.city,
                    wanted,
                    exc_info=True,
                )
            row.photos_fetched_at = now
            if photos:
                row.photos = photos
                row.photos_source = source
            session.commit()
            return PhotosFetchResponse(
                photos=list(photos or []),
                photos_source=row.photos_source,
                fetched=bool(photos),
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "photos_fetch: store unavailable, city=%s name=%s",
            req.city,
            wanted,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="poi store unavailable") from None


@router.post("/photos/report-dead", status_code=204)
def photos_report_dead(
    req: PhotosDeadReport,
    factory: Callable[[], Session] = Depends(get_poi_session_factory),
) -> Response:
    """F4 死图上报（fire-and-forget）：photos_fetch_fail += 1，恒 204——
    前端 onerror 不等结果。未知/坏 poi_id 留 warning 日志（静默吞掉
    不允许），响应层无差别 204 防探测。"""
    try:
        poi_uuid = uuid.UUID(req.poi_id)
    except (ValueError, AttributeError):
        logger.warning("photos_report_dead: bad poi_id=%r", req.poi_id)
        return Response(status_code=204)
    with factory() as session:
        row = session.get(Poi, poi_uuid)
        if row is None:
            # 餐厅回退（2026-11-13）：气泡出参 poi_id 可能是 restaurants 行
            # （detail 回退命中餐厅）——死图计数落在同构 photos_fetch_fail 列。
            row = session.get(Restaurant, poi_uuid)
        if row is None:
            logger.warning("photos_report_dead: unknown poi_id=%s", req.poi_id)
            return Response(status_code=204)
        row.photos_fetch_fail = (row.photos_fetch_fail or 0) + 1
        session.commit()
    return Response(status_code=204)


def get_poi_store() -> PoiDetailStore:
    """Dependency indirection over the process singleton so tests can
    override (dependency_overrides) without touching the global store."""
    return _poi_store_singleton()


class PoiSearchHit(BaseModel):
    """库内检索下拉项（2026-11-01 行程卡「换景点」）：lean 形状，供
    H5 展示与后续 replace 端点按 name 精确落实。"""

    poi_id: str | None = None
    name: str
    name_en: str | None = None
    city: str | None = None
    category: str | None = None
    tags: list = []
    rating: float | None = None
    address: str | None = None
    opening_hours: str | None = None
    located: bool = False


@router.get("/search", response_model=list[PoiSearchHit])
def search_pois(
    q: str = Query(min_length=1, max_length=64),
    city: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=8, ge=1, le=20),
    store: PoiDetailStore = Depends(get_poi_store),
) -> list[PoiSearchHit]:
    """POI 底库关键字检索（2026-11-01）：search_keyword 同引擎（q 对
    name/category/tags LIKE，city 三态收窄），排序 精确命中>标签>有坐
    标>类别>tier。无坐标行也返回（located=False）——用户显式挑选时不
    静默隐藏，坐标回填链后补（坐标闸拍板 2026-10-30）。"""
    kw = q.strip()
    if not kw:
        return []
    try:
        hits = store.search_keyword(city, [kw], limit=limit)
    except Exception:
        raise HTTPException(status_code=503, detail="poi store unavailable") from None
    out: list[PoiSearchHit] = []
    for h in hits:
        name = str(h.get("name") or "").strip()
        if not name:
            continue
        loc = h.get("location")
        try:
            rating = float(h.get("rating")) if h.get("rating") else None
        except (TypeError, ValueError):
            rating = None
        out.append(
            PoiSearchHit(
                poi_id=h.get("source_poi_id"),
                name=name,
                name_en=h.get("name_en"),
                city=h.get("city"),
                category=h.get("category"),
                tags=list(h.get("tags") or []),
                rating=rating,
                address=h.get("address"),
                opening_hours=h.get("opening_hours"),
                located=bool(loc),
            )
        )
    return out
