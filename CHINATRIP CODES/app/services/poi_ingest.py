"""POI 底库补全/去重（2026-11-16 用户拍板）。

用户口径（原话）：
* 「if sites is not in pois table, we should get address and transportation from
  amap, save into pois table, then arrange in the same way of other sites」
* 「we should set one record valid with all necessary information, another record
  to be inactive」

朱家角案就是第二条：`pois` 里同一个地方有三行（`ctrip` 骨架无坐标无地址、
`histown` 朱家角镇有坐标有地址、`4a` 朱家角古镇已 inactive）。心愿/简报按名字
命中哪一行全看运气——命中空骨架那行，卡面就没地址、没坐标、没腿；两行都进
候选就变成「两天各一张朱家角」。

本模块三件事：

1. ``merge_place``：同城 + 同地名内核（「朱家角古镇」↔「朱家角镇」，见
   ``poi_names.place_core``）的行合并成**一条有效记录**——保留信息最全的
   那行，把其余行**只填空**抄过去，其余行置 ``status='inactive'``（不删行，
   可回溯）。「有效记录」的选择顺序：active > 信息完整度 > 最近更新。
2. ``ensure_poi``：规划/建心愿时保证这个点「有坐标 + 有地址」——先查库，
   缺了就先用兄弟行补（不联网），再缺才走图商检索链（高德 → 腾讯 → 百度）
   补建/补全，距城心 ≥8km 的点顺带补 ``access_*`` 交通摘要（与
   ``app.jobs.backfill_poi_access`` 同源、同归一函数）。
3. 只填空、绝不覆盖：任何一步都不动已有值，图商挂掉只退回旧行为，不抛异常。

用法（运维/数据修复）：

    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --dry-run
    python -m app.jobs.dedupe_pois --city 上海 --apply
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Callable

from geoalchemy2 import Geometry
from sqlalchemy import cast, func

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.coords import make_point
from app.services.itinerary.models import GeoPoint
from app.services.itinerary.rules import haversine_km
from app.services.map_provider import build_client_chain
from app.services.poi_access import summarize
from app.services.poi_classify import classify
from app.services.poi_names import place_core
from app.services.poi_seed import mark_status, normalize_category, seed_upsert
from app.services.vendor_chain import run_vendor_chain
from app.services.weather_open_meteo import CITY_COORDS

logger = logging.getLogger(__name__)

#: 距城心多远才值得算「怎么去」（城心步行圈内的点打车/走路就够，省配额）。
ACCESS_MIN_KM = 8.0

#: 这些类别不是「去玩的目的地」，不补到达方式、不参与景点去重。
_SERVICE_CATEGORIES = ("hotel", "food", "transport", "service")

#: 同地名合并的地理闸：同名内核但相距超过这个距离，视为两地（不合并）。
MERGE_MAX_KM = 10.0

#: geography → geometry 强转（ST_X/ST_Y 只接 geometry；直接上 geography 会
#: 报 function st_x(geography) does not exist）。
_GEOM = Geometry("POINT", srid=4326)


def _lon():
    return func.ST_X(cast(Poi.location, _GEOM))


def _lat():
    return func.ST_Y(cast(Poi.location, _GEOM))


@dataclass
class MapHit:
    """一条图商命中（高德/百度/腾讯 search_poi 归一后的形状）。"""

    name: str
    city: str | None = None
    lon: float | None = None
    lat: float | None = None
    address: str | None = None
    category: str | None = None
    opening_hours: str | None = None
    source: str = "amap"
    source_poi_id: str | None = None
    score: float = 0.0


@dataclass
class PoiRow:
    """底库行快照（脱离 session 也能读；合并/补全都只认这些字段）。"""

    id: Any
    name: str
    city: str
    status: str | None = None
    source: str | None = None
    source_poi_id: str | None = None
    category: str | None = None
    address: str | None = None
    lon: float | None = None
    lat: float | None = None
    duration_minutes: int | None = None
    opening_hours: str | None = None
    name_en: str | None = None
    intro: str | None = None
    intro_en: str | None = None
    name_aliases: list[str] | None = None
    rating: float | None = None
    rating_count: int | None = None
    rain_ok: str | None = None
    indoor: str | None = None
    best_visit_time: str | None = None
    access_mode: str | None = None
    access_minutes: int | None = None
    access_note: str | None = None
    access_updated_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def has_location(self) -> bool:
        return self.lon is not None and self.lat is not None

    @property
    def active(self) -> bool:
        return (self.status or "active") == "active"

    @property
    def completeness(self) -> int:
        """信息完整度打分（合并时选「有效记录」用）。"""
        score = 0
        if self.has_location:
            score += 3
        if (self.address or "").strip():
            score += 2
        if self.category:
            score += 1
        if self.duration_minutes:
            score += 1
        if (self.intro or "").strip():
            score += 1
        if (self.name_en or "").strip():
            score += 1
        return score


@dataclass
class EnsureResult:
    """``ensure_poi`` 的返回：seed 形状 + 地址/图商 id/到达方式。"""

    name: str
    city: str | None = None
    poi_id: str | None = None
    row_id: Any = None
    address: str | None = None
    location: dict[str, float] | None = None
    kind: str | None = None
    duration_minutes: int | None = None
    opening_hours: str | None = None
    access_mode: str | None = None
    access_minutes: int | None = None
    access_note: str | None = None
    source: str | None = None
    created: bool = False
    merged: list[str] = field(default_factory=list)
    enriched: list[str] = field(default_factory=list)

    @property
    def latitude(self) -> float | None:
        return (self.location or {}).get("lat")

    @property
    def longitude(self) -> float | None:
        return (self.location or {}).get("lon")

    def as_dict(self) -> dict[str, Any]:
        """给仓储/心愿层用的扁平字典（与 ``wish_seed.seed_from_pois`` 兼容）。"""
        return {
            "poi_id": self.poi_id,
            "name": self.name,
            "city": self.city,
            "address": self.address,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "kind": self.kind,
            "duration_minutes": self.duration_minutes,
            "opening_hours": self.opening_hours,
            "access_mode": self.access_mode,
            "access_minutes": self.access_minutes,
            "access_note": self.access_note,
            "source": self.source,
            "created": self.created,
            "merged": list(self.merged),
            "enriched": list(self.enriched),
        }


@dataclass
class MergeResult:
    """一次同地名合并的结果（``dry_run`` 时只算不写）。"""

    keeper: PoiRow
    retired: list[PoiRow] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)
    filled_from: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "keeper": _row_dict(self.keeper),
            "retired": [_row_dict(r) for r in self.retired],
            "filled": list(self.filled),
            "filled_from": list(self.filled_from),
        }


def _row_dict(row: PoiRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "city": row.city,
        "status": row.status,
        "source": row.source,
        "source_poi_id": row.source_poi_id,
        "category": row.category,
        "address": row.address,
        "lon": row.lon,
        "lat": row.lat,
        "duration_minutes": row.duration_minutes,
        "name_aliases": list(row.name_aliases or []),
        "has_location": row.has_location,
        "completeness": row.completeness,
    }


def _norm(value: str | None) -> str:
    """名称归一：去括号补充/空白/大小写，用于比对（不改展示名）。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(value or ""))
    return re.sub(r"\s+", "", s).strip().lower()


def _city_names(city: str | None) -> set[str]:
    c = (city or "").strip()
    if not c:
        return set()
    return {c, f"{c}市", c.removesuffix("市")} - {""}


def _px(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 图商检索 ---


def _score_hit(query: str, city: str | None, hit: MapHit) -> float:
    """命中打分：同名 100 / 命中名含查询词 60 / 查询词含命中名 40 / 形似 0-30。

    同城 +10、有地址 +5；低于 30 视为不相关（宁缺毋滥——绝不拿隔壁城市同
    名酒店当景点）。
    """
    q = _norm(query)
    h = _norm(hit.name)
    if not q or not h:
        return 0.0
    if h == q:
        score = 100.0
    elif q in h:
        score = 60.0
    elif h in q:
        score = 40.0
    else:
        score = 30.0 * SequenceMatcher(None, q, h).ratio()
    if city and hit.city:
        if _norm(hit.city).removesuffix("市") == _norm(city).removesuffix("市"):
            score += 10.0
    if hit.address:
        score += 5.0
    return score


def pick_hit(name: str, city: str | None, hits: list[MapHit]) -> MapHit | None:
    """从图商命中里挑最像的那个（有坐标才可用）。"""
    best: MapHit | None = None
    for hit in hits:
        if hit.lon is None or hit.lat is None:
            continue
        hit.score = _score_hit(name, city, hit)
        if hit.score < 30.0:
            continue
        if best is None or hit.score > best.score:
            best = hit
    return best


def _hit_from_dict(row: dict) -> MapHit:
    loc = row.get("location") or {}
    lon = lat = None
    if isinstance(loc, dict):
        lon, lat = loc.get("lon"), loc.get("lat")
    elif isinstance(loc, (tuple, list)) and len(loc) == 2:
        lon, lat = loc[0], loc[1]
    return MapHit(
        name=str(row.get("name") or "").strip(),
        city=row.get("city"),
        lon=_px(lon),
        lat=_px(lat),
        address=(row.get("address") or None),
        category=row.get("category"),
        opening_hours=row.get("opening_hours"),
        source=str(row.get("source") or "amap"),
        source_poi_id=row.get("source_poi_id"),
    )


async def search_map(
    name: str,
    city: str | None,
    *,
    chain: list[Any] | None = None,
    latch: dict[str, str] | None = None,
) -> list[MapHit]:
    """图商检索链取命中（高德在前，见 map_provider）。失败返回空表。"""
    probe = (name or "").strip()
    if not probe:
        return []
    if chain is None:
        try:
            chain = build_client_chain(get_settings(), "search")
        except Exception:  # noqa: BLE001 — 配置缺失按无图商处理
            logger.warning("poi_ingest: build search chain failed", exc_info=True)
            return []
    if not chain:
        return []

    async def run(client: Any) -> Any:
        return await client.search_poi(probe, city=city)

    try:
        result = await run_vendor_chain(
            chain, run, latch=latch if latch is not None else {}, function="search"
        )
    except Exception:  # noqa: BLE001 — 链执行器已兜底，这里防御
        logger.warning("poi_ingest: search chain raised", exc_info=True)
        return []
    if not isinstance(result, list):
        return []
    return [_hit_from_dict(row) for row in result if isinstance(row, dict)]


# ---------------------------------------------------------------- 底库读写 ---


def _row_snapshot(poi: Any, lon: Any, lat: Any) -> PoiRow:
    return PoiRow(
        id=poi.id,
        name=(poi.name_zh or "").strip(),
        city=poi.city,
        status=poi.status,
        source=poi.source,
        source_poi_id=poi.source_poi_id,
        category=poi.category,
        address=poi.address,
        lon=_px(lon),
        lat=_px(lat),
        duration_minutes=poi.suggested_duration_min,
        opening_hours=poi.opening_hours,
        name_en=poi.name_en,
        intro=poi.intro,
        intro_en=poi.intro_en,
        name_aliases=[a for a in (poi.name_aliases or []) if isinstance(a, str)],
        rating=_px(poi.rating),
        rating_count=poi.rating_count,
        rain_ok=poi.rain_ok,
        indoor=poi.indoor,
        best_visit_time=poi.best_visit_time,
        access_mode=poi.access_mode,
        access_minutes=poi.access_minutes,
        access_note=poi.access_note,
        access_updated_at=poi.access_updated_at,
        updated_at=poi.updated_at,
    )


def _query_rows(
    session: Any,
    *,
    city: str | None,
    exact: str | None = None,
    like: str | None = None,
    active_only: bool = True,
    limit: int = 50,
) -> list[PoiRow]:
    q = session.query(Poi, _lon(), _lat())
    if active_only:
        q = q.filter((Poi.status.is_(None)) | (Poi.status == "active"))
    names = _city_names(city)
    if names:
        q = q.filter(Poi.city.in_(names))
    if exact is not None:
        q = q.filter(Poi.name_zh == exact)
    elif like is not None:
        q = q.filter(Poi.name_zh.like(f"%{like}%"))
    return [_row_snapshot(poi, lon, lat) for poi, lon, lat in q.limit(limit).all()]


def find_poi_row(
    name: str, city: str | None = None, *, factory: Callable[[], Any] | None = None
) -> PoiRow | None:
    """取最合适的**有效**底库行：精确同名优先（同名多行取信息最全），无精确
    同名再按地名内核包含匹配；住宿/餐饮行不当景点补。库不可用返回 None。"""
    factory = factory or get_session_factory()
    probe = (name or "").strip()
    if not probe:
        return None
    try:
        with factory() as session:
            rows = _query_rows(session, city=city, exact=probe, limit=20)
            if not rows:
                core = place_core(probe)
                # 内核包含回退只认「内核完全相等」且内核 ≥2 字（2026-11-16：
                # 宽松 LIKE 会把单字母/短名当成命中——测试里建心愿「a」被
                # 回退成某条名字含 a 的 POI，poi_id 相同的两条愿望还被建行
                # 去重并成一条）。
                if not core or len(core) < 2:
                    return None
                rows = [
                    r
                    for r in _query_rows(session, city=city, like=core, limit=50)
                    if place_core(r.name) == core
                ]
                if len(rows) > 1:
                    rows = [
                        r for r in rows if (r.category or "") not in _SERVICE_CATEGORIES
                    ] or rows
    except Exception:  # noqa: BLE001 — 补建是增强，不是主链路
        logger.warning("poi_ingest: find row %s failed", name, exc_info=True)
        return None
    if not rows:
        return None
    return max(rows, key=_keeper_rank)


def _keeper_rank(row: PoiRow) -> tuple:
    """「有效记录」排序：active > 完整度 > 最近更新。"""
    return (
        1 if row.active else 0,
        row.completeness,
        row.updated_at.timestamp() if row.updated_at is not None else 0.0,
    )


def _same_place(a: PoiRow, b: PoiRow) -> bool:
    """同地名判定：内核相同 + 同城 + 坐标相近（缺坐标只信内核）。"""
    if place_core(a.name) != place_core(b.name) or not place_core(a.name):
        return False
    if a.has_location and b.has_location:
        return (
            haversine_km(
                GeoPoint(lon=a.lon, lat=a.lat),
                GeoPoint(lon=b.lon, lat=b.lat),
            )
            <= MERGE_MAX_KM
        )
    return True


def _copy_from_row(session: Any, poi: Any, src: PoiRow) -> list[str]:
    """兄弟行 → 目标行，**只填空**（不覆盖已有值）。"""
    filled: list[str] = []
    if poi.location is None and src.has_location:
        poi.location = make_point(float(src.lon), float(src.lat))
        filled.append("location")
    if not (poi.address or "").strip() and (src.address or "").strip():
        poi.address = src.address[:200]
        filled.append("address")
    if not (poi.category or "").strip() and src.category:
        poi.category = src.category
        filled.append("category")
    if poi.suggested_duration_min is None and src.duration_minutes:
        poi.suggested_duration_min = src.duration_minutes
        poi.duration_source = "merge"
        filled.append("duration_minutes")
    if not (poi.opening_hours or "").strip() and src.opening_hours:
        poi.opening_hours = src.opening_hours[:500]
        filled.append("opening_hours")
    if not (poi.name_en or "").strip() and (src.name_en or "").strip():
        poi.name_en = src.name_en[:200]
        filled.append("name_en")
    if not (poi.intro or "").strip() and (src.intro or "").strip():
        poi.intro = src.intro
        filled.append("intro")
    if not (poi.intro_en or "").strip() and (src.intro_en or "").strip():
        poi.intro_en = src.intro_en
        filled.append("intro_en")
    if poi.rating is None and src.rating is not None:
        poi.rating = src.rating
        filled.append("rating")
    if poi.rating_count is None and src.rating_count is not None:
        poi.rating_count = src.rating_count
        filled.append("rating_count")
    if not (poi.rain_ok or "").strip() and (src.rain_ok or "").strip():
        poi.rain_ok = src.rain_ok
        filled.append("rain_ok")
    if not (poi.indoor or "").strip() and (src.indoor or "").strip():
        poi.indoor = src.indoor
        filled.append("indoor")
    if not (poi.best_visit_time or "").strip() and (src.best_visit_time or "").strip():
        poi.best_visit_time = src.best_visit_time
        filled.append("best_visit_time")
    # 别名并入（2026-11-16 用户问「what are 别名 of two sites above」）：两行
    # 互为别名——退役行的名字/别名写进幸存行，名字检索（match_text_names
    # 读 name_aliases）仍能按旧名找到这唯一一条有效记录。
    aliases = [a for a in (poi.name_aliases or []) if isinstance(a, str)]
    extra = [src.name, *(src.name_aliases or [])]
    added = [
        a
        for a in extra
        if isinstance(a, str)
        and a.strip()
        and a.strip() != (poi.name_zh or "")
        and a.strip() not in aliases
    ]
    if added:
        poi.name_aliases = [*aliases, *added]
        filled.append("name_aliases")
    return filled


def _fill_row(session: Any, poi: Any, hit: MapHit) -> list[str]:
    """把图商命中**只填空**写进行，返回实际写入的字段名。"""
    filled: list[str] = []
    if hit.lon is not None and hit.lat is not None and poi.location is None:
        poi.location = make_point(float(hit.lon), float(hit.lat))
        filled.append("location")
    if hit.address and not (poi.address or "").strip():
        poi.address = hit.address[:200]
        filled.append("address")
    if not (poi.category or "").strip():
        cat = normalize_category(hit.category) if hit.category else None
        if cat is None and hit.category:
            cat, _indoor, _rain, _floor = classify(poi.name_zh or "", hit.category)
        if cat:
            poi.category = cat
            filled.append("category")
    if hit.opening_hours and not (poi.opening_hours or "").strip():
        poi.opening_hours = hit.opening_hours[:500]
        filled.append("opening_hours")
    if poi.suggested_duration_min is None:
        _cat, _indoor, _rain, floor = classify(
            poi.name_zh or "",
            poi.category or hit.category,
            address=poi.address or hit.address,
            city=poi.city,
        )
        if floor:
            poi.suggested_duration_min = int(floor)
            poi.duration_source = "heuristic"
            filled.append("duration_minutes")
    return filled


def _snapshot_after(session: Any, poi_id: Any) -> PoiRow | None:
    row = session.query(Poi, _lon(), _lat()).filter(Poi.id == poi_id).first()
    if row is None:
        return None
    return _row_snapshot(row[0], row[1], row[2])


def merge_place(
    name: str,
    city: str | None = None,
    *,
    factory: Callable[[], Any] | None = None,
    dry_run: bool = False,
    keep_id: Any = None,
) -> MergeResult | None:
    """同一个地方只留一条有效记录：信息最全的当 keeper，其余置 inactive。

    「同一个地方」= 同城 + ``place_core`` 相同 + 坐标相距 ≤ ``MERGE_MAX_KM``
    （任一方缺坐标时只信内核）。keeper 缺的字段从其余行**只填空**抄过来；
    其余行 ``status='inactive'``（不删行）。``keep_id`` 可指定 keeper（数据
    修复时用），但仍只在同地名族内生效。``dry_run`` 只算不写。
    """
    factory = factory or get_session_factory()
    probe = (name or "").strip()
    core = place_core(probe)
    if not core:
        return None
    try:
        with factory() as session:
            rows = _query_rows(
                session, city=city, like=core, active_only=False, limit=50
            )
            rows = [r for r in rows if place_core(r.name) == core]
    except Exception:  # noqa: BLE001
        logger.warning("poi_ingest: merge lookup %s failed", probe, exc_info=True)
        return None
    if not rows:
        return None
    # ``keep_id`` 只换「谁当幸存行」，不能拿它过滤候选（否则 others 恒空）
    keeper: PoiRow | None = None
    if keep_id is not None:
        keeper = next((r for r in rows if str(r.id) == str(keep_id)), None)
    if keeper is None:
        keeper = max(rows, key=_keeper_rank)
    others = [r for r in rows if r.id != keeper.id and _same_place(keeper, r)]
    if not others:
        return None

    retired = [r for r in others if r.active]
    filled: list[str] = []
    filled_from: list[str] = []
    if dry_run:
        # 只算「会补哪些字段」：按完整度从高到低模拟填空
        probe_flags: set[str] = set()
        if not keeper.has_location:
            probe_flags.add("location")
        if not (keeper.address or "").strip():
            probe_flags.add("address")
        if not (keeper.category or "").strip():
            probe_flags.add("category")
        if not keeper.duration_minutes:
            probe_flags.add("duration_minutes")
        if not (keeper.intro or "").strip():
            probe_flags.add("intro")
        if not (keeper.name_en or "").strip():
            probe_flags.add("name_en")
        if any(
            other.name != keeper.name and other.name not in (keeper.name_aliases or [])
            for other in others
        ):
            probe_flags.add("name_aliases")
        filled = sorted(probe_flags)
        filled_from = [r.name for r in others]
        return MergeResult(
            keeper=keeper, retired=retired, filled=filled, filled_from=filled_from
        )

    try:
        with factory() as session:
            fresh = session.get(Poi, keeper.id)
            if fresh is None:
                return None
            # 「一条有效记录」：显式指定 inactive 行当 keeper 时复活它
            # （数据修复：4a「4a_0064 朱家角古镇」比骨架/行政区行更像景点本体）。
            if (fresh.status or "active") != "active":
                fresh.status = "active"
            for other in sorted(others, key=_keeper_rank, reverse=True):
                filled += [
                    key
                    for key in _copy_from_row(session, fresh, other)
                    if key not in filled
                ]
                filled_from.append(other.name)
            session.commit()
        for other in retired:
            if other.source and other.source_poi_id:
                mark_status(factory, Poi, other.source, other.source_poi_id, "inactive")
        snapshot = None
        with factory() as session:
            snapshot = _snapshot_after(session, keeper.id)
    except Exception:  # noqa: BLE001
        logger.warning("poi_ingest: merge %s failed", probe, exc_info=True)
        return None
    if snapshot is None:
        return None
    logger.info(
        "poi_ingest: merged place %s keeper=%s retired=%s filled=%s",
        probe,
        snapshot.name,
        [r.name for r in retired],
        filled,
    )
    return MergeResult(
        keeper=snapshot, retired=retired, filled=filled, filled_from=filled_from
    )


# ---------------------------------------------------------------- 到达方式 ---


async def _access_summary(
    city: str | None,
    lon: float,
    lat: float,
    *,
    chain: list[Any] | None = None,
    latch: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """城心 → 该点的公交最优方案（与 backfill_poi_access 同源）。"""
    anchor = CITY_COORDS.get(str(city or "").strip())
    if not anchor:
        return None
    if chain is None:
        try:
            chain = build_client_chain(get_settings(), "transit")
        except Exception:  # noqa: BLE001
            return None
    if not chain:
        return None
    city_name = str(city or "").strip()

    async def run(client: Any) -> Any:
        return await client.transit_route(
            f"{float(anchor[1]):.6f},{float(anchor[0]):.6f}",
            f"{lon:.6f},{lat:.6f}",
            city=city_name,
            cityd=city_name,
        )

    try:
        result = await run_vendor_chain(
            chain, run, latch=latch if latch is not None else {}, function="transit"
        )
    except Exception:  # noqa: BLE001
        logger.warning("poi_ingest: transit chain raised", exc_info=True)
        return None
    if not isinstance(result, list):
        return None
    return summarize(result, poi_point=(lon, lat))


async def fill_access(
    poi_id: Any,
    *,
    city: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    factory: Callable[[], Any] | None = None,
    chain: list[Any] | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """给一行补 ``access_*``（只填空；``force`` 重算）。失败返回 None。"""
    factory = factory or get_session_factory()
    try:
        with factory() as session:
            poi = session.get(Poi, poi_id)
            if poi is None:
                return None
            city_name = city or poi.city
            if (poi.category or "") in _SERVICE_CATEGORIES:
                return None
            if lon is None or lat is None:
                point = session.query(_lon(), _lat()).filter(Poi.id == poi_id).first()
                if point is not None:
                    lon, lat = point[0], point[1]
            if lon is None or lat is None:
                return None
            if poi.access_updated_at is not None and not force:
                return {
                    "access_mode": poi.access_mode,
                    "access_minutes": poi.access_minutes,
                    "access_note": poi.access_note,
                }
            summary = await _access_summary(
                city_name, float(lon), float(lat), chain=chain
            )
            if not summary:
                return None
            for key, value in summary.items():
                if hasattr(poi, key):
                    setattr(poi, key, value)
            poi.access_source = "amap-transit"
            poi.access_updated_at = datetime.now()
            session.commit()
            return summary
    except Exception:  # noqa: BLE001 — 交通是增强，失败不影响排期
        logger.warning("poi_ingest: fill access %s failed", poi_id, exc_info=True)
        return None


async def _maybe_fill_access(
    result: EnsureResult,
    row: PoiRow | None,
    *,
    factory: Callable[[], Any],
    access: Callable[[Any, str | None, float, float], Any] | None = None,
    chain: list[Any] | None,
) -> None:
    """远点补交通（只填空）；结果写回 ``result``。"""
    lon, lat = result.longitude, result.latitude
    if lon is None or lat is None or result.access_mode:
        return
    anchor = CITY_COORDS.get(str(result.city or "").strip())
    if anchor is not None:
        km = haversine_km(
            GeoPoint(lon=lon, lat=lat),
            GeoPoint(lon=float(anchor[1]), lat=float(anchor[0])),
        )
        if km < ACCESS_MIN_KM:
            return
    poi_id = row.id if row is not None else None
    if poi_id is None:
        found = find_poi_row(result.name, result.city, factory=factory)
        poi_id = found.id if found is not None else None
    if poi_id is None:
        return
    if access is not None:
        try:
            summary = await access(poi_id, result.city, lon, lat)
        except Exception:  # noqa: BLE001
            summary = None
    else:
        summary = await fill_access(
            poi_id, city=result.city, lon=lon, lat=lat, factory=factory, chain=chain
        )
    if not isinstance(summary, dict):
        return
    result.access_mode = summary.get("access_mode")
    result.access_minutes = summary.get("access_minutes")
    result.access_note = summary.get("access_note")


def _result_from_row(row: PoiRow) -> EnsureResult:
    return EnsureResult(
        name=row.name,
        city=row.city,
        poi_id=row.source_poi_id,
        row_id=row.id,
        address=row.address,
        location={"lon": row.lon, "lat": row.lat} if row.has_location else None,
        kind=row.category,
        duration_minutes=row.duration_minutes,
        opening_hours=row.opening_hours,
        access_mode=row.access_mode,
        access_minutes=row.access_minutes,
        access_note=row.access_note,
        source=row.source,
    )


async def ensure_poi(
    name: str,
    city: str | None = None,
    *,
    create: bool = True,
    want_access: bool = True,
    dedupe: bool = True,
    map_lookup: bool = True,
    factory: Callable[[], Any] | None = None,
    search: Callable[[str, str | None], Any] | None = None,
    access: Callable[[Any, str | None, float, float], Any] | None = None,
    chain: list[Any] | None = None,
) -> EnsureResult | None:
    """保证「名字」在 pois 底库里有坐标/地址（必要时建行），返回补好的点。

    顺序：查库（同名多行先合并成一条有效记录）→ 缺骨架用兄弟行补（不联网）
    → 仍缺才图商检索补建/补全 → 远点补交通。任何一步失败都退化为「返回已
    有什么」，绝不抛。
    """
    probe = (name or "").strip()
    if not probe:
        return None
    factory = factory or get_session_factory()
    row = find_poi_row(probe, city, factory=factory)
    merged: list[str] = []

    # 同名多行（同一地点）：先按拍板「一条有效、其余 inactive」收口
    if dedupe and row is not None:
        try:
            merged_ret = merge_place(
                row.name, row.city or city, factory=factory, keep_id=row.id
            )
        except Exception:  # noqa: BLE001
            merged_ret = None
        if merged_ret is not None:
            row = merged_ret.keeper
            merged = [r.name for r in merged_ret.retired]

    if row is not None and row.has_location and (row.address or "").strip():
        result = _result_from_row(row)
        result.merged = merged
        if want_access:
            await _maybe_fill_access(
                result, row, factory=factory, access=access, chain=chain
            )
        return result

    # 兄弟行只要知道，就先抄过来——不为已有信息再打图商
    if row is not None:
        sibling = _best_sibling(row, factory=factory)
        if sibling is not None:
            filled = _copy_from_sibling(factory, row.id, sibling)
            if filled:
                row = _reload(row.id, factory=factory) or row
                merged = [*merged, f"{sibling.name}:{'/'.join(filled)}"]
        if row.has_location and (row.address or "").strip():
            result = _result_from_row(row)
            result.merged = merged
            if want_access:
                await _maybe_fill_access(
                    result, row, factory=factory, access=access, chain=chain
                )
            return result

    # ---- 仍缺：图商检索（用库里的真名搜，命中率更高）----
    if not map_lookup:
        # 建行/看板链路只做库内合并与兄弟行回填（零网络、零延迟）——
        # 图商补建留给规划绑定与运维作业（那里才需要地址/交通排期）。
        if row is None:
            return None
        result = _result_from_row(row)
        result.merged = merged
        return result
    target = row.name if row is not None and row.name else probe
    if search is not None:
        try:
            hits = await search(target, city)
            hits = hits if isinstance(hits, list) else []
        except Exception:  # noqa: BLE001
            logger.warning("poi_ingest: injected search failed for %s", probe)
            hits = []
    else:
        hits = await search_map(target, city, chain=chain)
    if not hits and target != probe:
        hits = await search_map(probe, city, chain=chain)
    hit = pick_hit(target, city or (row.city if row is not None else None), hits)
    if hit is None:
        logger.info("poi_ingest: no map hit for %s (%s)", probe, city)
        if row is None:
            return None
        result = _result_from_row(row)
        result.merged = merged
        return result

    result: EnsureResult | None = None
    if row is not None:
        try:
            with factory() as session:
                fresh = session.get(Poi, row.id)
                if fresh is not None:
                    filled = _fill_row(session, fresh, hit)
                    if filled:
                        session.commit()
                    snapshot = _snapshot_after(session, row.id)
                    if snapshot is not None:
                        result = _result_from_row(snapshot)
                        result.merged = merged
                        result.enriched = filled
        except Exception:  # noqa: BLE001
            logger.warning("poi_ingest: fill row %s failed", probe, exc_info=True)
    elif create and hit.source_poi_id:
        try:
            city_name = (city or hit.city or "").strip().removesuffix("市")
            status = seed_upsert(
                factory,
                Poi,
                source=hit.source or "amap",
                source_poi_id=hit.source_poi_id,
                city=city_name,
                name_zh=hit.name or probe,
                category=hit.category,
                lonlat=(hit.lon, hit.lat) if hit.lon is not None else None,
                origin=hit.source or "amap",
            )
            created = find_poi_row(
                hit.name or probe, city_name or city, factory=factory
            )
            if created is not None:
                with factory() as session:
                    fresh = session.get(Poi, created.id)
                    if fresh is not None:
                        filled = _fill_row(session, fresh, hit)
                        if filled:
                            session.commit()
                        snapshot = _snapshot_after(session, created.id)
                        if snapshot is not None:
                            result = _result_from_row(snapshot)
                            result.created = status == "created"
                            result.merged = merged
                            result.enriched = filled
        except Exception:  # noqa: BLE001
            logger.warning("poi_ingest: create row %s failed", probe, exc_info=True)

    if result is None:
        if row is None:
            return None
        result = _result_from_row(row)
        result.merged = merged
        return result
    if want_access:
        await _maybe_fill_access(
            result, row, factory=factory, access=access, chain=chain
        )
    return result


def _reload(poi_id: Any, *, factory: Callable[[], Any]) -> PoiRow | None:
    try:
        with factory() as session:
            return _snapshot_after(session, poi_id)
    except Exception:  # noqa: BLE001
        return None


def _best_sibling(row: PoiRow, *, factory: Callable[[], Any]) -> PoiRow | None:
    """同城、同内核、不是自己；挑信息最全的一条（缺坐标/地址时抄它）。"""
    core = place_core(row.name)
    if not core:
        return None
    try:
        with factory() as session:
            rows = _query_rows(
                session, city=row.city, like=core, active_only=False, limit=50
            )
    except Exception:  # noqa: BLE001
        return None
    pool = [r for r in rows if r.id != row.id and _same_place(row, r)]
    if not pool:
        return None
    return max(pool, key=_keeper_rank)


def _copy_from_sibling(
    factory: Callable[[], Any], poi_id: Any, sibling: PoiRow
) -> list[str]:
    try:
        with factory() as session:
            fresh = session.get(Poi, poi_id)
            if fresh is None:
                return []
            filled = _copy_from_row(session, fresh, sibling)
            if filled:
                session.commit()
            return filled
    except Exception:  # noqa: BLE001
        logger.warning("poi_ingest: sibling fill %s failed", poi_id, exc_info=True)
        return []
