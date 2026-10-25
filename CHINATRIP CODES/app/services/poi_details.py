"""POI display details (address + opening hours) store (v2.4.4).

用户拍板 2026-10-19: enrichment results live in the pois table; the daily
job (app.jobs.refresh_pois) runs the source chain — 携程 sight pages
first, then 高德 v5 detail / keyword search — and planning READS this
store instead of fetching live. When the database is unreachable (MVP dev
without the docker db) the store degrades to an in-process dict so
planning keeps working; the next job run against the DB repopulates it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from math import log2
from uuid import uuid4

from sqlalchemy import and_, func, or_

from app.models import Poi
from app.services.coords import gcj02_to_wgs84, make_point
from app.services.poi_classify import duration_upgradable

logger = logging.getLogger(__name__)

# ST_AsText(点几何) → "POINT(lon lat)"（geography 同样 lon 在前）
_POINT_WKT_RE = re.compile(r"POINT\((\S+) (\S+)\)")

_STALE_AFTER = timedelta(hours=24)
# After a failed DB call, skip DB attempts for this long (memory
# serves instead). Bounds the down-db cost to ONE connect_timeout
# stall per window instead of one per call (2026-10-20 latency fix).
_DB_DOWN_COOLDOWN_SECONDS = 300.0
# Empty memory has nothing to serve: a long latch would ship empty
# candidate lists for minutes (2026-10-25 placeholder incident — one
# connect failure while the dev WSL db slept poisoned planning for the
# 300s window). Empty store retries the DB quickly instead; cost is one
# connect_timeout per request while down.
_DB_DOWN_EMPTY_RETRY_SECONDS = 5.0

# A 级优先（用户拍板 2026-10-25：unesco > 5A > 4A > 3A）。名单在库里
# 以 source='unesco'/'5a' 骨架行存在（tags 列 0 覆盖——boost 从未生效
# 过，2026-10-25 城市阳台事件）；读时按 source + 全库名单互含判定层级，
# 并把层级标签注入候选 tags（LLM 选点层同享信号）。
_TIER_BOOST = {4: 1.8, 3: 1.5, 2: 1.3, 1: 1.15}
_TIER_TAG = {4: "unesco", 3: "5a", 2: "4a", 1: "3a"}


def _name_overlap(a: str | None, b: str | None) -> bool:
    """名单互含匹配（灵隐飞来峰 ↔ 灵隐飞来峰景区）；短名防泛名误伤。"""
    a, b = (a or "").strip(), (b or "").strip()
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a


class PoiDetailStore:
    """Read/upsert POI display details; DB-backed with memory fallback."""

    def __init__(self, session_factory=None) -> None:
        self._factory = session_factory
        self._memory: dict[str, dict] = {}
        self._db_down_until = 0.0  # time.monotonic() deadline

    def _db_available(self) -> bool:
        return self._factory is not None and (time.monotonic() >= self._db_down_until)

    def _note_db_failure(self) -> None:
        cooldown = (
            _DB_DOWN_COOLDOWN_SECONDS if self._memory else _DB_DOWN_EMPTY_RETRY_SECONDS
        )
        self._db_down_until = time.monotonic() + cooldown

    def db_degraded(self) -> bool:
        """DB 配置存在且刚失败、处于锁存窗口（规划占位出货门禁用）。

        factory=None（无 DB 部署的内存模式）不算降级——那是设计内形态。
        """
        return self._factory is not None and (time.monotonic() < self._db_down_until)

    # --- read ---------------------------------------------------------------

    def get(self, source_poi_id: str) -> dict | None:
        if self._db_available():
            try:
                with self._factory() as session:
                    row = (
                        session.query(Poi)
                        .filter_by(source="amap", source_poi_id=source_poi_id)
                        .one_or_none()
                    )
                    if row is None:
                        return None
                    return {
                        "poi_id": row.source_poi_id,
                        "address": row.address,
                        "opening_hours": row.opening_hours,
                        "hours_source": row.hours_source,
                        "hours_updated_at": (
                            row.hours_updated_at.isoformat()
                            if row.hours_updated_at
                            else None
                        ),
                    }
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db read failed, memory fallback",
                    exc_info=True,
                )
        return self._memory.get(source_poi_id)

    def stale_pois(
        self,
        *,
        limit: int = 200,
        sources: tuple[str, ...] | None = None,
        city: str | None = None,
    ) -> list[tuple[str, str | None, str | None, str | None, str | None]]:
        """POIs whose hours are missing or older than 24h (job targets).

        返回 (source_poi_id, city, name_zh, source, location) 五元组；
        location 为 amap-ready "lon,lat"（GCJ-02，无坐标行 None）——链③
        text 配额尽(10021)时 client 降级 around-search 要用（2026-10-24）。
        sources 非 None 时只返回指定 source 的行（骨架行按渠道分批回源
        用）。city 过滤必须在 SQL 层做——查询无 ORDER BY，limit 窗口是
        物理顺序前 N 行；若窗口外过滤，单城刷批次会拿不到行（2026-10-23
        实测：首 200 行全北京，其余城 total=0 饿死）。
        """
        cutoff = datetime.now(timezone.utc) - _STALE_AFTER
        city_names = (
            {city, f"{city}市", (city or "").removesuffix("市")} if city else None
        )
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(
                        Poi.hours_updated_at.is_(None) | (Poi.hours_updated_at < cutoff)
                    )
                    if sources is not None:
                        q = q.filter(Poi.source.in_(list(sources)))
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    rows = q.limit(limit).all()
                    out = []
                    for r, loc_txt in rows:
                        m = _POINT_WKT_RE.match(loc_txt or "")
                        out.append(
                            (
                                r.source_poi_id,
                                r.city,
                                r.name_zh,
                                r.source,
                                f"{m.group(1)},{m.group(2)}" if m else None,
                            )
                        )
                    return out
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db unreachable, memory fallback",
                    exc_info=True,
                )
        out: list[tuple[str, str | None, str | None, str | None, str | None]] = []
        for pid, v in self._memory.items():
            ts = v.get("hours_updated_at")
            if ts is None or ts < cutoff:
                loc = v.get("location")
                out.append(
                    (
                        pid,
                        v.get("city"),
                        v.get("name"),
                        v.get("source") or "amap",
                        f"{loc[0]},{loc[1]}" if loc else None,
                    )
                )
        if sources is not None:
            out = [t for t in out if (t[3] or "") in sources]
        if city_names:
            out = [t for t in out if t[1] in city_names]
        return out[:limit]

    def ping(self) -> bool:
        # Explicit probe: ignores the down-latch so the daily job and
        # a mid-session db start recover without a process restart.
        if self._factory is None:
            return False
        try:
            with self._factory() as session:
                session.query(Poi.id).first()
            self._db_down_until = 0.0
            return True
        except Exception:
            return False

    # --- write --------------------------------------------------------------

    def get_by_name(self, city: str | None, name: str) -> dict | None:
        """Exact-name lookup so appended rows serve later no-poi_id items."""
        name = (name or "").strip()
        if not name:
            return None
        if self._db_available():
            try:
                with self._factory() as session:
                    row = session.query(Poi).filter(Poi.name_zh == name).first()
                    if row is None:
                        return None
                    return {
                        "poi_id": row.source_poi_id,
                        "address": row.address,
                        "opening_hours": row.opening_hours,
                        "hours_source": row.hours_source,
                    }
            except Exception:
                self._note_db_failure()
                logger.warning("poi_details: db get_by_name failed", exc_info=True)
        for key, v in self._memory.items():
            if v.get("name") == name:
                return dict(v, poi_id=key)
        return None

    def search_keyword(
        self, city: str | None, tokens: list[str], *, limit: int = 5
    ) -> list[dict]:
        """POI 底库关键字搜索（心愿落实先查库再打高德，用户拍板
        2026-10-24）。city 匹配同 stale_pois 三态；tokens 对 name_zh/
        category 做 LIKE。返回 amap 形状的骨架 dict（name/city/category/
        source_poi_id/location/address/opening_hours/source/rating），
        按（名字精确命中，有坐标，类别命中）降序。"""
        toks = [t for t in (tokens or []) if t]
        if not toks:
            return []
        city_names = None
        if city:
            c = city.strip()
            city_names = {c, f"{c}市", c.removesuffix("市")} - {""}

        def rank(h: dict) -> tuple[bool, bool, bool]:
            n = (h.get("name") or "").strip()
            return (
                any(n == t for t in toks),
                h.get("location") is not None,
                any(t in (h.get("category") or "") for t in toks),
            )

        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    )
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    conds = []
                    for t in toks:
                        pat = f"%{t}%"
                        conds.append(Poi.name_zh.like(pat))
                        conds.append(Poi.category.like(pat))
                    rows = q.filter(or_(*conds)).limit(limit * 3).all()
                    hits = []
                    for row, loc_txt in rows:
                        m = _POINT_WKT_RE.match(loc_txt or "")
                        hits.append(
                            {
                                "source_poi_id": row.source_poi_id,
                                "name": row.name_zh,
                                "city": row.city,
                                "category": row.category,
                                "address": row.address,
                                "opening_hours": row.opening_hours,
                                "source": row.source,
                                "rating": float(row.rating) if row.rating else None,
                                "location": (
                                    (float(m.group(1)), float(m.group(2)))
                                    if m
                                    else None
                                ),
                            }
                        )
                    hits.sort(key=rank, reverse=True)
                    return hits[:limit]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db keyword search failed, memory fallback",
                    exc_info=True,
                )
        hits = []
        for pid, v in self._memory.items():
            if city_names and v.get("city") not in city_names:
                continue
            name = v.get("name") or ""
            hay = f"{name} {v.get('category') or ''}"
            if not any(t in hay for t in toks):
                continue
            loc = v.get("location")
            hits.append(
                {
                    "source_poi_id": pid,
                    "name": name,
                    "city": v.get("city"),
                    "category": v.get("category"),
                    "address": v.get("address"),
                    "opening_hours": v.get("opening_hours"),
                    "source": v.get("source") or "amap",
                    "rating": None,
                    "location": tuple(loc) if loc else None,
                }
            )
        hits.sort(key=rank, reverse=True)
        return hits[:limit]

    _FOOD_CATEGORY_MARKS = ("food", "餐饮", "美食", "餐厅")

    @classmethod
    def _row_is_food(cls, category: str | None) -> bool:
        c = (category or "").strip()
        return any(mark in c for mark in cls._FOOD_CATEGORY_MARKS)

    def _heritage_names(self) -> list[tuple[str, int]]:
        """全库 unesco/5A 名单行 (name_zh, tier)——读时并档用，不限城。"""
        out: list[tuple[str, int]] = []
        if self._db_available():
            try:
                with self._factory() as session:
                    rows = (
                        session.query(Poi.name_zh, Poi.source)
                        .filter(Poi.source.in_(["unesco", "5a"]))
                        .all()
                    )
                    return [(name, 4 if src == "unesco" else 3) for name, src in rows]
            except Exception:
                self._note_db_failure()
                logger.warning("poi_details: heritage list query failed", exc_info=True)
        for v in self._memory.values():
            src = v.get("source")
            if src in ("unesco", "5a"):
                out.append((v.get("name") or "", 4 if src == "unesco" else 3))
        return out

    def top_pois_in_city(
        self, city: str, limit: int = 30, *, exclude_food: bool = True
    ) -> list[dict]:
        """引擎候选主池（DESIGN 8.1.1，2026-10-24）：同城确定性排序取 top N。

        score = rating × log2(1 + rating_count) × 标签加成（tags 含
        unesco/5A 乘 1.5）；有坐标优先；无评分行按（有标签、有坐标）
        垫底但保留——5A/UNESCO 骨架可能尚未回源评分，不能因冷启动被
        埋没。返回 search_keyword 同形状 + 富化字段（rating_count/
        tags/best_visit_time/suggested_duration_min/indoor/rain_ok/
        review_tags/intro 摘要 ≤60 字）；location 为 (lon, lat) 元组。
        """
        c = (city or "").strip().removesuffix("市")
        city_names = ({c, f"{c}市"} - {""}) if c else set()
        if not city_names:
            return []

        def build(row, loc_txt: str | None) -> dict:
            m = _POINT_WKT_RE.match(loc_txt or "")
            # rating 可能是 Decimal/str/float（DB 列 vs amap 原文），统一安全转
            try:
                rating = float(row.rating) if row.rating else None
            except (TypeError, ValueError):
                rating = None
            return {
                "source_poi_id": row.source_poi_id,
                "name": row.name_zh,
                # 双语 P1：_en 并出（空时前端回退中文）
                "name_en": row.name_en,
                "address_en": row.address_en,
                "intro_en": (row.intro_en or "")[:60] or None,
                "opening_hours_en": row.opening_hours_en,
                "review_tags_en": row.review_tags_en or [],
                "city": row.city,
                "category": row.category,
                "address": row.address,
                "opening_hours": row.opening_hours,
                "source": row.source,
                "rating": rating,
                "rating_count": row.rating_count,
                "tags": row.tags or [],
                "best_visit_time": row.best_visit_time or "any",
                "suggested_duration_min": row.suggested_duration_min,
                "indoor": row.indoor,
                "rain_ok": row.rain_ok,
                "review_tags": row.review_tags or [],
                "intro": (row.intro or "")[:60] or None,
                "reservation_required": row.reservation_required,
                "reservation_advance_days": row.reservation_advance_days,
                "booking_url": row.booking_url,
                "location": ((float(m.group(1)), float(m.group(2))) if m else None),
            }

        def score(h: dict) -> tuple:
            # A 级优先（2026-10-25 用户拍板）：tier 在前——无评分的 5A/
            # unesco 名单行也要压过裸 4.8 的边缘点（城市阳台事件）。
            rating = h.get("rating") or 0.0
            count = h.get("rating_count") or 0
            quality = rating * (1 + (log2(1 + count) if count else 0))
            tier = h.get("_tier") or 0
            boost = _TIER_BOOST.get(tier, 1.0)
            if not tier:
                tags = {str(t) for t in (h.get("tags") or [])}
                if tags & {"michelin", "black_pearl"}:
                    boost = 1.5
            return (
                tier,
                round(quality * boost, 3),
                1 if h.get("location") else 0,
            )

        rows_out: list[dict] = []
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(
                        Poi.city.in_(city_names),
                        (Poi.status.is_(None)) | (Poi.status == "active"),
                    )
                    if exclude_food:
                        q = q.filter(
                            Poi.category.is_(None)
                            | and_(
                                *[
                                    ~Poi.category.like(f"%{mark}%")
                                    for mark in self._FOOD_CATEGORY_MARKS
                                ]
                            )
                        )
                    q = q.limit(2000)
                    rows_out = [build(r, t) for r, t in q.all()]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: top_pois_in_city db failed, memory fallback",
                    exc_info=True,
                )
                rows_out = []
        if not rows_out:

            class _MemRow:  # memory rows mimic ORM attrs for build()
                __slots__ = (
                    "source_poi_id",
                    "name_zh",
                    "city",
                    "category",
                    "address",
                    "opening_hours",
                    "source",
                    "rating",
                    "rating_count",
                    "tags",
                    "best_visit_time",
                    "suggested_duration_min",
                    "indoor",
                    "rain_ok",
                    "review_tags",
                    "intro",
                    "name_en",
                    "address_en",
                    "intro_en",
                    "opening_hours_en",
                    "review_tags_en",
                    "reservation_required",
                    "reservation_advance_days",
                    "booking_url",
                )

            for pid, v in self._memory.items():
                if (v.get("city") or "").removesuffix("市") != c:
                    continue
                if exclude_food and self._row_is_food(v.get("category")):
                    continue
                r = _MemRow()
                for slot in _MemRow.__slots__:
                    setattr(r, slot, None)
                r.source_poi_id = pid
                r.name_zh = v.get("name")
                r.city = v.get("city")
                r.category = v.get("category")
                r.address = v.get("address")
                r.opening_hours = v.get("opening_hours")
                r.source = v.get("source") or "amap"
                r.rating = v.get("rating")
                r.rating_count = v.get("rating_count")
                r.tags = v.get("tags")
                r.best_visit_time = v.get("best_visit_time")
                r.suggested_duration_min = v.get("suggested_duration_min")
                r.indoor = v.get("indoor")
                r.rain_ok = v.get("rain_ok")
                r.review_tags = v.get("review_tags")
                r.intro = v.get("intro")
                r.name_en = v.get("name_en")
                r.address_en = v.get("address_en")
                r.intro_en = v.get("intro_en")
                r.opening_hours_en = v.get("opening_hours_en")
                r.review_tags_en = v.get("review_tags_en")
                r.reservation_required = v.get("reservation_required")
                r.reservation_advance_days = v.get("reservation_advance_days")
                r.booking_url = v.get("booking_url")
                loc = v.get("location")
                h = build(r, f"POINT({loc[0]} {loc[1]})" if loc else None)
                rows_out.append(h)
        heritage = self._heritage_names()

        def tier_of(h: dict) -> int:
            tags = {str(t) for t in (h.get("tags") or [])}
            if "unesco" in tags or h.get("source") == "unesco":
                return 4
            if "5a" in tags or h.get("source") == "5a":
                return 3
            if "4a" in tags:
                return 2
            if "3a" in tags:
                return 1
            name = h.get("name") or ""
            for ref, tier in heritage:
                if _name_overlap(name, ref):
                    return tier
            return 0

        for h in rows_out:
            tier = tier_of(h)
            h["_tier"] = tier
            tag = _TIER_TAG.get(tier)
            if tag and tag not in h["tags"]:
                h["tags"] = [*h["tags"], tag]
        rows_out.sort(key=score, reverse=True)
        for h in rows_out:  # 私有排序键，出库前剥掉
            h.pop("_tier", None)
        return rows_out[:limit]

    def upsert(
        self,
        source_poi_id: str,
        *,
        city: str | None = None,
        name: str | None = None,
        address: str | None = None,
        opening_hours: str | None = None,
        hours_source: str | None = None,
        source: str = "amap",
        category: str | None = None,
        location: tuple[float, float] | None = None,
        rating: float | None = None,
        rating_source: str | None = None,
        rating_count: int | None = None,
        photos: list | None = None,
        photos_source: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        district: str | None = None,
        business_area: str | None = None,
        suggested_duration_min: int | None = None,
        duration_source: str | None = None,
        review_tags: list | None = None,
        review_tags_source: str | None = None,
        ticket_price_min: int | None = None,
        ticket_price_max: int | None = None,
        ticket_source: str | None = None,
    ) -> bool:
        """Persist display details; memory always written, DB best-effort.

        category/location 是 v2.5 骨架字段（外部源仅写名称/坐标/类别，
        用户拍板 2026-10-24：关键字搜到的店 APPEND 进 pois，沿用现有
        food/attraction 归类）；location 为 GCJ-02 (lon, lat)，入库按
        v1.7 铁律成对写 wgs84 副本。

        0009 富化字段写入语义（A/B 组，DESIGN §3.1/3.2）：rating/
        rating_count 随回源**刷新**（时间敏感值，高德/携程是真相）；
        photos/phone/website/district/business_area/suggested_duration/
        review_tags/ticket_price 只填空（已有值不覆盖——wikimedia 照片、
        ctrip 时长优先于 amap 兜底值）。
        """
        # 列宽 varchar(500)（高德多季节营业时间串可超长，2026-10-23 实测
        # 114/200 行因 StringDataRightTruncation 丢写），入库前截断
        address = address[:500] if address else address
        opening_hours = opening_hours[:500] if opening_hours else opening_hours
        now = datetime.now(timezone.utc)
        mem = self._memory.setdefault(source_poi_id, {})
        if city and not mem.get("city"):
            mem["city"] = city
        if name and not mem.get("name"):
            mem["name"] = name
        if source and not mem.get("source"):
            mem["source"] = source
        if category and not mem.get("category"):
            mem["category"] = category
        if location and not mem.get("location"):
            mem["location"] = location
        if address:
            mem["address"] = address
        if opening_hours:
            mem["opening_hours"] = opening_hours
        if hours_source:
            mem["hours_source"] = hours_source
        if opening_hours:
            mem["hours_updated_at"] = now
        for key, value in (
            ("rating", rating),
            ("rating_source", rating_source),
            ("rating_count", rating_count),
            ("phone", phone),
            ("website", website),
            ("district", district),
            ("business_area", business_area),
            ("review_tags", review_tags),
            ("review_tags_source", review_tags_source),
            ("ticket_price_min", ticket_price_min),
            ("ticket_price_max", ticket_price_max),
            ("ticket_source", ticket_source),
        ):
            if value is None:
                continue
            if key in ("rating", "rating_source", "rating_count"):
                mem[key] = value  # 回源真相：随刷新
            elif not mem.get(key):
                mem[key] = value  # 富化：只填空
        # duration 特例（2026-10-25 拍板）：真值可升级 heuristic 地板，
        # 真值之间仍只填空；与下方 DB 写法保持同语义
        if suggested_duration_min is not None and (
            mem.get("suggested_duration_min") is None
            or mem.get("duration_source") == "heuristic"
        ):
            mem["suggested_duration_min"] = suggested_duration_min
            if duration_source:
                mem["duration_source"] = duration_source
        if photos and not mem.get("photos"):
            mem["photos"] = photos
            if photos_source:
                mem["photos_source"] = photos_source
        if self._factory is None or not self._db_available():
            return True
        point = make_point(*location) if location else None
        try:
            with self._factory() as session:
                row = (
                    session.query(Poi)
                    .filter_by(source=source, source_poi_id=source_poi_id)
                    .one_or_none()
                )
                if row is None:
                    row = Poi(
                        id=uuid4(),
                        source=source,
                        source_poi_id=source_poi_id,
                        city=city,
                        name_zh=name,
                        address=address,
                        opening_hours=opening_hours,
                        hours_source=hours_source,
                        hours_updated_at=now,
                    )
                    if category:
                        row.category = category
                    if point is not None:
                        row.location = point
                        row.wgs84_location = make_point(*gcj02_to_wgs84(*location))
                    session.add(row)
                else:
                    if city and not row.city:
                        row.city = city
                    if name and not row.name_zh:
                        row.name_zh = name
                    if category and not row.category:
                        row.category = category
                    if point is not None and row.location is None:
                        row.location = point
                        row.wgs84_location = make_point(*gcj02_to_wgs84(*location))
                    if address:
                        row.address = address
                    if opening_hours:
                        row.opening_hours = opening_hours
                    if hours_source:
                        row.hours_source = hours_source
                    if opening_hours:
                        row.hours_updated_at = now
                # 0009 富化字段（新旧行同规则：rating 系刷新，其余只填空）
                if rating is not None:
                    row.rating = rating
                if rating_source:
                    row.rating_source = rating_source
                if rating_count:
                    row.rating_count = rating_count
                if photos and row.photos is None:
                    row.photos = photos
                    if photos_source:
                        row.photos_source = photos_source
                for attr, value in (
                    ("phone", phone),
                    ("website", website),
                    ("district", district),
                    ("business_area", business_area),
                    ("review_tags", review_tags),
                    ("review_tags_source", review_tags_source),
                    ("ticket_price_min", ticket_price_min),
                    ("ticket_price_max", ticket_price_max),
                    ("ticket_source", ticket_source),
                ):
                    if value is None or getattr(row, attr) is not None:
                        continue
                    setattr(row, attr, value)
                # duration 特例（同内存层语义）：真值升级 heuristic 地板
                if suggested_duration_min is not None and duration_upgradable(row):
                    row.suggested_duration_min = suggested_duration_min
                    if duration_source:
                        row.duration_source = duration_source
                session.commit()
            return True
        except Exception:
            self._note_db_failure()
            logger.warning("poi_details: db upsert failed (memory kept)", exc_info=True)
            return True

    def touch_hours_checked(self, source_poi_id: str) -> bool:
        """MISS 冷却：只盖 hours_updated_at=now，不写 hours/source。

        永久缺 hours 的行（骨架不可匹配等）原本每轮重复查询、一天
        多次烧 text 配额（2026-10-24 实测 200 连续超限）；盖戳即进
        24h 静默（stale_pois 窗口外）。内存同步盖；DB UPDATE 失败只
        记日志不抛（冷却失败无害，下轮多查一次而已）。
        """
        now = datetime.now(timezone.utc)
        mem = self._memory.get(source_poi_id)
        if mem is not None:
            mem["hours_updated_at"] = now
        if self._factory is None or not self._db_available():
            return True
        try:
            with self._factory() as session:
                session.query(Poi).filter(Poi.source_poi_id == source_poi_id).update(
                    {Poi.hours_updated_at: now}
                )
                session.commit()
        except Exception:
            self._note_db_failure()
            logger.warning("poi_details: hours touch failed", exc_info=True)
        return True


_store_singleton: PoiDetailStore | None = None


def get_poi_detail_store() -> PoiDetailStore:
    """Process-wide lazy singleton; DB factory wired when available."""
    global _store_singleton
    if _store_singleton is None:
        from app.db import get_session_factory

        try:
            factory = get_session_factory()
        except Exception:
            logger.error(
                "poi_details: session factory unavailable, in-memory only",
                exc_info=True,
            )
            factory = None
        _store_singleton = PoiDetailStore(session_factory=factory)
    return _store_singleton
