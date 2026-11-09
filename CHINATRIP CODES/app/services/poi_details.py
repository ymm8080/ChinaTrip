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

from sqlalchemy import String, and_, cast, func, or_

from app.models import Poi
from app.services.coords import gcj02_to_wgs84, make_point
from app.services.poi_classify import duration_upgradable

# 层级档位共享模块（2026-11-03 名录序全站唯一定义点）：catalog_rank 判档；
# order_source_tags 在下方薄委托 source_tag_key（app/jobs 从本模块
# import 该名，签名不变）
from app.services.source_tier import (
    INTL_PLATFORM_TAGS,
    INTL_SITE_TAGS,
    catalog_rank,
    source_tag_key,
)

logger = logging.getLogger(__name__)

# ST_AsText(点几何) → "POINT(lon lat)"（geography 同样 lon 在前）
_POINT_WKT_RE = re.compile(r"POINT\((\S+) (\S+)\)")

# 回源刷新目标窗口（2026-10-28 用户拍板：地址/营业时间一行一月）——
# hours_updated_at 距今超 30 天（或 NULL）才进 stale_pois；每日作业照跑，
# 只是每行最多一月被碰一次（命中/未命中盖戳同权），配额烧耗降一个量级
_STALE_AFTER = timedelta(days=30)
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

# 层级档号（2026-11-03 名录序拍板，共享模块 source_tier 全站唯一定义点）：
# 0=unesco 1=5a 2=国际旅行网站 3=国际平台 4=短视频 5=小红书 6=街区
# 7=风景名胜 8=4a 9=3a 10=未分层——取代 2026-10-25 四档（4/3/2/1）与
# 2026-10-25/26「intl 与 5A 同档」拍板。小值优先；boost 逐档递减
# （未列=1.0）；6 街区/7 风景名胜不打层级牌（_TIER_TAG 缺档即不注入）。
_TIER_BOOST = {
    0: 1.8,
    1: 1.6,
    2: 1.5,
    3: 1.4,
    4: 1.3,
    5: 1.25,
    6: 1.2,
    7: 1.15,
    8: 1.1,
    9: 1.05,
}
_TIER_TAG = {
    0: "unesco",
    1: "5a",
    2: "intl",
    3: "intl",
    4: "intl",
    5: "intl",
    8: "4a",
    9: "3a",
}


# 功能标签愿望词 → tags 内核（2026-10-29 功能标签批打后的读侧接线）：
# 「看演出 / citywalk / 逛古镇」按玩法标签检索，不再只 LIKE 名称/类别——
# 《驼铃传奇》秀 名称无「演出」二字，靠 tags=['show'] 命中。
_LABEL_TOKENS: dict[str, str] = {
    "演出": "show",
    "看演出": "show",
    "show": "show",
    "citywalk": "citywalk",
    "city walk": "citywalk",
    "压马路": "citywalk",
    "古镇": "historical_town",
    "名镇": "historical_town",
    "历史名镇": "historical_town",
    "世界遗产": "unesco",
    "unesco": "unesco",
    "5a": "5a",
    "5a级": "5a",
}


def _token_label(token: str) -> str | None:
    return _LABEL_TOKENS.get((token or "").strip().lower())


def _norm_label_tag(t: object) -> str:
    return str(t).strip().lower()


def _hit_has_label(h: dict, label: str | None) -> bool:
    """命中行 tags 是否带某功能标签（愿望词→标签后的读侧判定）。"""
    if not label:
        return False
    return label in {_norm_label_tag(t) for t in (h.get("tags") or [])}


def order_source_tags(tags: list[str]) -> list[str]:
    """多来源打标序——委托共享模块 source_tier（2026-11-03 名录序取代
    2026-10-26「国外榜单放前」：unesco 族最先）。jobs 从本模块 import
    此名，签名 (tags: list[str]) -> list[str] 不变。"""
    return sorted(tags, key=source_tag_key)


def hit_tier(h: dict, heritage: list[tuple[str, int]]) -> int:
    """单行层级判定（读侧通用，2026-10-28 从 top_pois_in_city 提出共用）：
    名录序 catalog_rank（2026-11-03 拍板，取代 2026-10-25/26「intl 与
    5A 同档」；unesco_* 前缀族视同全量世遗）→ 3a 兜底档 → 全库名单
    互含 → 10=未分层。返回档号小值优先：0=unesco 1=5a 2=国际旅行网站
    3=国际平台 4=短视频 5=小红书 6=街区 7=风景名胜 8=4a 9=3a。"""
    r = catalog_rank(h.get("source"), h.get("tags"))
    if r is not None:
        return r
    tags = {str(t).strip().lower() for t in (h.get("tags") or [])}
    source = str(h.get("source") or "").strip().lower()
    if "3a" in tags or source == "3a":
        return 9
    name = h.get("name") or ""
    for ref, tier in heritage:
        if _name_overlap(name, ref):
            return tier
    return 10


def apply_tier_tag(h: dict, heritage: list[tuple[str, int]]) -> int:
    """判定层级并把层级标签并入 tags（档 2-5 统一打 intl 牌；6 街区/
    7 风景名胜无牌不注入），返回层级。读侧（top_pois_in_city /
    search_keyword / api/pois）共用。"""
    tier = hit_tier(h, heritage)
    tag = _TIER_TAG.get(tier)
    if tag and tag not in (h.get("tags") or []):
        h["tags"] = order_source_tags([*(h.get("tags") or []), tag])
    return tier


_GENERIC_TAILS = (
    "景区",
    "风景区",
    "旅游区",
    "风景名胜区",
    "名胜区",
    "公园",
    "国家公园",
    "森林公园",
    "湿地公园",
    "地质公园",
    "遗址",
    "遗址公园",
    "博物馆",
    "博物院",
    "纪念馆",
    "陈列馆",
    "故居",
    "陵",
    "园区",
    "度假区",
    "旅游度假区",
    "古城",
    "古镇",
    "老街",
    "街区",
)


def _name_overlap(a: str | None, b: str | None) -> bool:
    """名单互含匹配,仅认头/尾相接:尾接多余段须为通用类尾词(灵隐飞来峰↔
    灵隐飞来峰景区),头接多余段须 ≤3 字地市前缀(北京颐和园);中段嵌含
    不再认——挡「颐和园-船坞」类子设施借本体世遗牌升档。"""
    a, b = (a or "").strip(), (b or "").strip()
    if len(a) < 3 or len(b) < 3:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if long_.startswith(short):
        extra = re.sub(r"[\s\-—·・]", "", long_[len(short) :])
        return not extra or extra in _GENERIC_TAILS
    if long_.endswith(short):
        extra = re.sub(r"[\s\-—·・]", "", long_[: -len(short)])
        return 0 < len(extra) <= 3
    return False


# 内存行 mimic ORM attrs（top_pois_in_city / candidate_by_name 的回退路共用）
_MEM_ROW_SLOTS = (
    "source_poi_id",
    "name_zh",
    "city",
    "category",
    "address",
    "opening_hours",
    "source",
    "rating",
    "rating_count",
    "rating_source",
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


class _MemRow:
    """Memory fallback row with the same attribute surface as the ORM Poi."""

    __slots__ = _MEM_ROW_SLOTS


def _candidate_from_row(row, loc_txt: str | None) -> dict:
    """ORM Poi 行 → 引擎候选 dict（top_pois_in_city / candidate_by_name
    共用，2026-11-01 从 top_pois_in_city 内的 build 提出）。"""
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
        # 评分跨源贴标尺（2026-11-07 拍板）：引擎 _quality 对 baidu 评分
        # ×0.9——rating_source 必须随候选投影下传（292 行有 baidu 评分，
        # 多为 baidu enrich 回填到非 baidu 行，不能按 source 推断）。
        "rating_source": row.rating_source,
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


def _memory_candidate_row(pid: str, v: dict, loc_txt: str | None) -> dict:
    """内存条目 → 引擎候选 dict（属性面与 ORM 行对齐后走同一构造器）。"""
    r = _MemRow()
    for slot in _MEM_ROW_SLOTS:
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
    return _candidate_from_row(r, loc_txt)


class PoiDetailStore:
    """Read/upsert POI display details; DB-backed with memory fallback."""

    def __init__(self, session_factory=None) -> None:
        self._factory = session_factory
        self._memory: dict[str, dict] = {}
        self._db_down_until = 0.0  # time.monotonic() deadline
        self._nonactive_pids_cache: set[str] | None = None
        self._nonactive_pids_at = 0.0

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
                        # 双语 P1 补链（2026-10-30）：_en 并出（空回退中文）
                        "name_en": row.name_en,
                        "address_en": row.address_en,
                        "intro_en": row.intro_en,
                        "opening_hours_en": row.opening_hours_en,
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
    ) -> list[tuple[str, str | None, str | None, str | None, str | None, str | None]]:
        """POIs whose hours are missing or older than 30 days (job targets;
        _STALE_AFTER 月度节奏 2026-10-28 定稿).

        返回 (source_poi_id, city, name_zh, source, location, hours_source)
        六元组；location 为 amap-ready "lon,lat"（GCJ-02，无坐标行
        None）——链③ text 配额尽(10021)时 client 降级 around-search 要用
        （2026-10-24）；hours_source 供 refresh 链行级护闸（'show' 行的
        opening_hours 是人工核好的场次时刻，不接受图商开放时间覆写，
        2026-11-07）。
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
                                r.hours_source,
                            )
                        )
                    return out
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db unreachable, memory fallback",
                    exc_info=True,
                )
        out: list[
            tuple[str, str | None, str | None, str | None, str | None, str | None]
        ] = []
        nonactive = self._nonactive_pids()
        for pid, v in self._memory.items():
            if pid in nonactive:
                continue
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
                        v.get("hours_source"),
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
        """Exact-name lookup so appended rows serve later no-poi_id items.

        city 口径（2026-11-01 多城重名 POI 案，用户拍板「应选目标城行而不是
        异地同名行」）：带 city 时只认同城行——多城重名 POI，
        旧版全库 .first() 把异地行过继给本城条目（poi_id/地址/英文简介
        整套易主）。同城无行宁可 None（零配额自愈链会走图商补齐），
        绝不用异地行冒充；city=None（fast_lane 语义）维持全库命中。
        """
        name = (name or "").strip()
        if not name:
            return None
        city_names = None
        if city:
            c = city.strip()
            city_names = {c, f"{c}市", c.removesuffix("市")} - {""}
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(Poi.name_zh == name)
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    # 去重轮收口（2026-11-01）：下线行不过继（与主池同口径）
                    q = q.filter((Poi.status.is_(None)) | (Poi.status == "active"))
                    pair = q.first()
                    if pair is None:
                        return None
                    row, loc_txt = pair
                    m = _POINT_WKT_RE.match(loc_txt or "")
                    return {
                        "poi_id": row.source_poi_id,
                        "city": row.city,
                        "address": row.address,
                        "opening_hours": row.opening_hours,
                        "hours_source": row.hours_source,
                        # 双语 P1 补链（2026-10-30）：_en 并出（空回退中文）
                        "name_en": row.name_en,
                        "address_en": row.address_en,
                        "intro_en": row.intro_en,
                        "opening_hours_en": row.opening_hours_en,
                        # 2026-10-30 补坐标（零配额治愈路径）：条目缺坐标时
                        # _backfill_locations 靠本跳直接拿库内坐标自愈，
                        # 不必烧图商配额（坐标 GCJ-02 (lon, lat) 或 None）。
                        "location": (
                            (float(m.group(1)), float(m.group(2))) if m else None
                        ),
                    }
            except Exception:
                self._note_db_failure()
                logger.warning("poi_details: db get_by_name failed", exc_info=True)
        nonactive = self._nonactive_pids()
        for key, v in self._memory.items():
            if key in nonactive:
                continue
            if v.get("name") != name:
                continue
            if city_names and (v.get("city") or "") not in city_names:
                continue  # 异地行不过继（与 DB 路同口径，2026-11-01）
            return dict(v, poi_id=key)
        return None

    def search_keyword(
        self, city: str | None, tokens: list[str], *, limit: int = 5
    ) -> list[dict]:
        """POI 底库关键字搜索（心愿落实先查库再打高德，用户拍板
        2026-10-24）。city 匹配同 stale_pois 三态；tokens 对 name_zh/
        category 做 LIKE，愿望词另按功能标签检索（2026-10-29：演出→show、
        citywalk、古镇→historical_town…打在 tags，名称无内核词的行如
        《驼铃传奇》秀 也能命中）。返回 amap 形状的骨架 dict（name/city/
        category/tags/source_poi_id/location/address/opening_hours/source/
        rating），按（名字精确命中，标签命中，有坐标，类别命中，hit_tier:
        名录序小值优先 unesco>5A>国际网站>国际平台>…>4A>3A>名单互含）
        降序——tier 只作同档并列裁决（2026-10-28 泛称愿望落地要同类最佳，
        与 top_pois_in_city 同一套层级判定；专名精确命中仍稳居首位不受
        影响）。"""

        toks = [t for t in (tokens or []) if t]
        if not toks:
            return []
        city_names = None
        if city:
            c = city.strip()
            city_names = {c, f"{c}市", c.removesuffix("市")} - {""}

        def rank(h: dict, heritage: list[tuple[str, int]]) -> tuple:
            n = (h.get("name") or "").strip()
            labels = [_token_label(t) for t in toks]
            return (
                any(n == t for t in toks),
                any(_hit_has_label(h, lb) for lb in labels),
                h.get("location") is not None,
                any(t in (h.get("category") or "") for t in toks),
                # 名录序档号小值优先（2026-11-03）：取负并入降序键
                -hit_tier(h, heritage),
            )

        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    )
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    # 去重轮收口（2026-11-01）：愿望解析/H5 检索不见下线行
                    q = q.filter((Poi.status.is_(None)) | (Poi.status == "active"))
                    conds = []
                    for t in toks:
                        pat = f"%{t}%"
                        conds.append(Poi.name_zh.like(pat))
                        conds.append(Poi.category.like(pat))
                        label = _token_label(t)
                        if label:
                            # JSONB tags 文本化匹配功能标签（"show" 子串唯一，
                            # 词表无前缀碰撞）；tags 为 NULL 的行不命中该条件
                            conds.append(cast(Poi.tags, String).like(f'%"{label}"%'))
                            if label == "unesco":
                                # unesco_* 前缀族（丝路 unesco_silk_road/喀斯特
                                # unesco_karst…）与 hit_tier 同属世界遗产族
                                # （2026-11-02 拍板），精确串吃不到前缀行——
                                # 加起始引号锚定的前缀 LIKE：JSONB 文本化每个
                                # tag 形如 "unesco_silk_road"，%"unesco 只命中
                                # tag 开头（也涵盖 "unesco" 本尊），不出泛子串。
                                conds.append(cast(Poi.tags, String).like('%"unesco%'))
                    # 取 10× 再 Python 排序：LIMIT 内没有 tier 概念，取太少
                    # 会把同类的 unesco/5A 行截在排序之前（内存回退全库扫，
                    # 两路池深对齐）。
                    rows = q.filter(or_(*conds)).limit(limit * 10).all()
                    hits = []
                    for row, loc_txt in rows:
                        m = _POINT_WKT_RE.match(loc_txt or "")
                        hits.append(
                            {
                                "source_poi_id": row.source_poi_id,
                                "name": row.name_zh,
                                "city": row.city,
                                "category": row.category,
                                "tags": row.tags or [],
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
                    heritage = self._heritage_names() if hits else []
                    hits.sort(key=lambda h: rank(h, heritage), reverse=True)
                    return hits[:limit]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: db keyword search failed, memory fallback",
                    exc_info=True,
                )
        hits = []
        tok_labels = [(t, _token_label(t)) for t in toks]
        nonactive = self._nonactive_pids()
        for pid, v in self._memory.items():
            if pid in nonactive:
                continue
            if city_names and v.get("city") not in city_names:
                continue
            name = v.get("name") or ""
            hay = f"{name} {v.get('category') or ''}"
            vtags = {_norm_label_tag(t) for t in (v.get("tags") or [])}
            # 标签内核命中（DB 路 cast LIKE 的内存对应）：愿望词→玩法标签；
            # unesco 再吃前缀族（unesco_silk_road 等），对齐 DB 路锚定前缀
            # LIKE 与 hit_tier 的世界遗产族口径（2026-11-02 拍板）。
            if not any(
                t in hay
                or (
                    lb is not None
                    and (
                        lb in vtags
                        or (
                            lb == "unesco"
                            and any(vt.startswith("unesco") for vt in vtags)
                        )
                    )
                )
                for t, lb in tok_labels
            ):
                continue
            loc = v.get("location")
            hits.append(
                {
                    "source_poi_id": pid,
                    "name": name,
                    "city": v.get("city"),
                    "category": v.get("category"),
                    "tags": list(v.get("tags") or []),
                    "address": v.get("address"),
                    "opening_hours": v.get("opening_hours"),
                    "source": v.get("source") or "amap",
                    "rating": None,
                    "location": tuple(loc) if loc else None,
                }
            )
        heritage = self._heritage_names() if hits else []
        hits.sort(key=lambda h: rank(h, heritage), reverse=True)
        return hits[:limit]

    def candidate_by_name(self, city: str | None, name: str) -> dict | None:
        """精确同名完整候选（2026-11-01 行程卡「换景点」）：name_zh 精确
        相等取行（city 三态收窄），同名多源行按 有坐标>tier>口碑 择一；
        返回 top_pois_in_city 同形状（含时段/时长/露天/预约字段），无
        命中返回 None——调用方提示用户，不静默换点。"""
        n = (name or "").strip()
        if not n:
            return None
        c = (city or "").strip().removesuffix("市")
        city_names = ({c, f"{c}市"} - {""}) if c else None
        rows_out: list[dict] = []
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(Poi.name_zh == n)
                    if city_names:
                        q = q.filter(Poi.city.in_(city_names))
                    # 去重轮收口（2026-11-01）：换景点不见下线行
                    q = q.filter((Poi.status.is_(None)) | (Poi.status == "active"))
                    rows_out = [_candidate_from_row(r, t) for r, t in q.limit(50).all()]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: candidate_by_name db failed, memory fallback",
                    exc_info=True,
                )
                rows_out = []
        if not rows_out:
            nonactive = self._nonactive_pids()
            for pid, v in self._memory.items():
                if pid in nonactive:
                    continue
                if (v.get("name") or "").strip() != n:
                    continue
                if city_names and (v.get("city") or "").removesuffix("市") != c:
                    continue
                loc = v.get("location")
                rows_out.append(
                    _memory_candidate_row(
                        pid, v, f"POINT({loc[0]} {loc[1]})" if loc else None
                    )
                )
        if not rows_out:
            return None
        heritage = self._heritage_names()

        def pick(h: dict) -> tuple:
            return (
                1 if h.get("location") else 0,
                # 名录序档号小值优先（2026-11-03）：取负供 max 择优
                -apply_tier_tag(h, heritage),
                h.get("rating") or 0.0,
            )

        best = max(rows_out, key=pick)
        return best

    _FOOD_CATEGORY_MARKS = ("food", "餐饮", "美食", "餐厅")
    # 主池住宿出池（2026-11-07 实测：成都 top-30 窗口混入 2 家 intl/layla
    # 标签酒店——易宁阁/西金中心，top_pois_in_city 只排 food 不排 hotel）
    _STAY_CATEGORY_MARKS = ("hotel", "酒店", "宾馆", "民宿", "客栈")
    # 餐饮入池豁免标（2026-11-07 用户指令「WE CAN CHOOSE RESTRANT IN SITE
    # IN CASE THEY ARE HV TAG LIKE KLOOK TRIPADVISOR ETC」）：带国际荐点
    # 标（ta/lp/viator/curated + 16 平台含 klook/裸 intl 伞标）的餐饮行
    # 当知名餐厅入主池（选点提示词本有用餐锚点消费口径）；住宿无此豁免。
    _REC_TAGS: frozenset[str] = frozenset(INTL_SITE_TAGS | INTL_PLATFORM_TAGS)

    @classmethod
    def _row_is_food(cls, category: str | None) -> bool:
        c = (category or "").strip()
        return any(mark in c for mark in cls._FOOD_CATEGORY_MARKS)

    @classmethod
    def _row_has_rec_tag(cls, tags: list | tuple | set | None) -> bool:
        tagset = {str(t).strip().lower() for t in (tags or [])}
        return bool(tagset & cls._REC_TAGS)

    @classmethod
    def _row_is_nonvisit(cls, category: str | None, tags: list | None = None) -> bool:
        """住宿恒出池；餐饮出池但带国际荐点标（ta/lp/viator/curated/klook
        等）的知名餐厅豁免入池（2026-11-07 用户指令，top_pois_in_city
        专用，search_keyword/备选池不受影响）。"""
        c = (category or "").strip()
        if any(mark in c for mark in cls._STAY_CATEGORY_MARKS):
            return True
        return cls._row_is_food(c) and not cls._row_has_rec_tag(tags)

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
                    # 档号随 2026-11-03 名录序：unesco=0、5a=1（小值优先）
                    return [(name, 0 if src == "unesco" else 1) for name, src in rows]
            except Exception:
                self._note_db_failure()
                logger.warning("poi_details: heritage list query failed", exc_info=True)
        for v in self._memory.values():
            src = v.get("source")
            if src in ("unesco", "5a"):
                out.append((v.get("name") or "", 0 if src == "unesco" else 1))
        return out

    def _nonactive_pids(self) -> set[str]:
        """全库下线行 source_poi_id 集（300s TTL 缓存）——内存回退路的
        退役闸：_memory 行由 upsert 写入、不带 status，靠身份集对齐
        DB 路的 (status IS NULL OR 'active') 口径（2026-11-04 公园/遗址
        下线后，DB 抖动 300s 回退窗会把已下线行重新捞进候选/检索）。"""
        now = time.monotonic()
        if (
            self._nonactive_pids_cache is not None
            and now - self._nonactive_pids_at < _DB_DOWN_COOLDOWN_SECONDS
        ):
            return self._nonactive_pids_cache
        if self._db_available():
            try:
                with self._factory() as session:
                    rows = (
                        session.query(Poi.source_poi_id)
                        .filter(Poi.status.isnot(None), Poi.status != "active")
                        .all()
                    )
                    self._nonactive_pids_cache = {r[0] for r in rows}
                    self._nonactive_pids_at = now
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: nonactive pid list query failed", exc_info=True
                )
        return self._nonactive_pids_cache or set()

    def nonactive_names(self, city: str | None) -> set[str]:
        """同城下线行名字集（含别名）——图商补量旁路的退役闸：库命中
        <10 时 live 捞回的同名行若在库已下线，不得重新进候选池
        （2026-11-04）。DB 不可达时返回空集（有日志，不拦）。"""
        names: set[str] = set()
        if not self._db_available():
            return names
        try:
            with self._factory() as session:
                q = session.query(Poi.name_zh, Poi.name_aliases).filter(
                    Poi.status.isnot(None), Poi.status != "active"
                )
                c = (city or "").strip().removesuffix("市")
                if c:
                    q = q.filter(Poi.city.in_({c, f"{c}市"} - {""}))
                for name, aliases in q.all():
                    if name:
                        names.add(name)
                    for a in aliases or []:
                        if a:
                            names.add(str(a))
        except Exception:
            self._note_db_failure()
            logger.warning("poi_details: nonactive names query failed", exc_info=True)
        return names

    def top_pois_in_city(
        self, city: str, limit: int = 30, *, exclude_food: bool = True
    ) -> list[dict]:
        """引擎候选主池（DESIGN 8.1.1，2026-10-24）：同城确定性排序取 top N。
        住宿出池（2026-11-07：住宿行此前一直占窗口席位）；餐饮出池但带
        国际荐点标（ta/lp/viator/curated/klook 等）的知名餐厅豁免入池
        （2026-11-07 用户指令——选点提示词「用餐锚点」消费口径接通）。

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

        def score(h: dict) -> tuple:
            # A 级优先（2026-10-25 用户拍板，2026-11-03 起名录序小值优先）：
            # tier 取负在前——无评分的 5A/unesco 名单行也要压过裸 4.8 的
            # 边缘点（城市阳台事件）。
            rating = h.get("rating") or 0.0
            count = h.get("rating_count") or 0
            quality = rating * (1 + (log2(1 + count) if count else 0))
            tier = h.get("_tier")
            if tier is None:
                tier = 10  # 未分层（防御：出库前必经 apply_tier_tag）
            boost = _TIER_BOOST.get(tier, 1.0)
            if tier == 10:
                tags = {str(t) for t in (h.get("tags") or [])}
                if tags & {"michelin", "black_pearl"}:
                    boost = 1.5
            # 2026-10-30 拍板（修「距下一站距离/步行不显示」第二刀）：有坐标
            # 行整体压过无坐标骨架行——top-N 截断发生在排序后，若骨架行靠
            # tier 挤进前 30，消费端坐标闸剔除后池子只剩 3-6 行，检索配额
            # 一死整城落占位（10-30 成都/上海/重庆实录 no_loc_skipped=24-27）。
            # 骨架行垫底保留，backfill 补齐坐标后自动回到前列。
            return (
                1 if h.get("location") else 0,
                -tier,
                round(quality * boost, 3),
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
                                    for mark in (
                                        *self._FOOD_CATEGORY_MARKS,
                                        *self._STAY_CATEGORY_MARKS,
                                    )
                                ]
                            )
                        )
                    q = q.limit(2000)
                    rows_out = [_candidate_from_row(r, t) for r, t in q.all()]
                    if exclude_food:
                        # 荐点餐厅豁免（2026-11-07 用户指令）：带国际荐点标
                        # 的餐饮行单独捞回（主流 food 行已在上一查询被 SQL
                        # 排除，带 tags 的 food 行全库个位数，二次小查询
                        # 不构成池稀释；住宿不享豁免照旧排除）。
                        fq = session.query(
                            Poi, func.ST_AsText(Poi.location).label("loc_txt")
                        ).filter(
                            Poi.city.in_(city_names),
                            (Poi.status.is_(None)) | (Poi.status == "active"),
                            Poi.tags.isnot(None),
                            or_(
                                *[
                                    Poi.category.like(f"%{mark}%")
                                    for mark in self._FOOD_CATEGORY_MARKS
                                ]
                            ),
                        )
                        rows_out.extend(
                            _candidate_from_row(r, t)
                            for r, t in fq.all()
                            if self._row_has_rec_tag(r.tags)
                        )
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: top_pois_in_city db failed, memory fallback",
                    exc_info=True,
                )
                rows_out = []
        if not rows_out:
            nonactive = self._nonactive_pids()
            for pid, v in self._memory.items():
                if pid in nonactive:
                    continue
                if (v.get("city") or "").removesuffix("市") != c:
                    continue
                if exclude_food and self._row_is_nonvisit(
                    v.get("category"), v.get("tags")
                ):
                    continue
                loc = v.get("location")
                rows_out.append(
                    _memory_candidate_row(
                        pid, v, f"POINT({loc[0]} {loc[1]})" if loc else None
                    )
                )
        heritage = self._heritage_names()

        for h in rows_out:
            tier = apply_tier_tag(h, heritage)
            h["_tier"] = tier
        rows_out.sort(key=score, reverse=True)
        for h in rows_out:  # 私有排序键，出库前剥掉
            h.pop("_tier", None)
        return rows_out[:limit]

    def recommendation_food_in_city(self, city: str, limit: int = 10) -> list[dict]:
        """荐点餐厅（2026-11-07 用户指令「有标记推荐的没进槽位…FIX IT」）：
        库内带国际荐点标（ta/lp/viator/curated/klook 等，同主池豁免
        _REC_TAGS 判定）的餐饮行，供餐槽位与图商实时检索并池——live
        amap 关键词搜索覆盖不到我们点名的店（红鼎宴/失重餐厅类）。

        返回 top_pois_in_city 同形状 hit + `rec_tagged: True` 键；无坐标
        骨架行照回（餐槽位由 rank_by_detour 的 999 垫底带兜住，无动线
        时不挡点名店进槽）。排序=有坐标>口碑（荐点行全库个位数，无需
        名录档细化）。DB 故障回落内存库，与读侧其他口径同款。"""
        c = (city or "").strip().removesuffix("市")
        city_names = ({c, f"{c}市"} - {""}) if c else set()
        if not city_names:
            return []
        hits: list[dict] = []
        if self._db_available():
            try:
                with self._factory() as session:
                    q = session.query(
                        Poi, func.ST_AsText(Poi.location).label("loc_txt")
                    ).filter(
                        Poi.city.in_(city_names),
                        (Poi.status.is_(None)) | (Poi.status == "active"),
                        Poi.tags.isnot(None),
                        or_(
                            *[
                                Poi.category.like(f"%{mark}%")
                                for mark in self._FOOD_CATEGORY_MARKS
                            ]
                        ),
                    )
                    for row, loc_txt in q.limit(50).all():
                        if not self._row_has_rec_tag(row.tags):
                            continue
                        hit = _candidate_from_row(row, loc_txt)
                        hit["rec_tagged"] = True
                        hits.append(hit)
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: recommendation_food db failed, memory fallback",
                    exc_info=True,
                )
                hits = []
        if not hits:
            nonactive = self._nonactive_pids()
            for pid, v in self._memory.items():
                if pid in nonactive:
                    continue
                if (v.get("city") or "").removesuffix("市") != c:
                    continue
                if not self._row_is_food(v.get("category")):
                    continue
                if not self._row_has_rec_tag(v.get("tags")):
                    continue
                loc = v.get("location")
                loc_txt = f"POINT({loc[0]} {loc[1]})" if loc else None
                hit = _memory_candidate_row(pid, v, loc_txt)
                hit["rec_tagged"] = True
                hits.append(hit)
        hits.sort(
            key=lambda h: (h.get("location") is not None, h.get("rating") or 0),
            reverse=True,
        )
        return hits[:limit]

    def alternatives_pool(self, city: str) -> list[dict]:
        """同城全量候选池（备选功能 2026-11-05 专用，与 top_pois_in_city
        同一套 DB/内存双路）：不按热度截 top N——同级备选按档号过滤后
        池子本来就小，截断会把同档冷门行提前埋掉。返回 search_keyword
        同形状 hit + `_tier`（hit_tier 名录档号，0=unesco..10=未分层，
        私有键不剥——消费方 poi_alternatives 直接用）。含餐行（备选规则
        自己按主点类别筛）；DB 故障回落内存库，与 top_pois_in_city 同款。
        """
        c = (city or "").strip().removesuffix("市")
        city_names = ({c, f"{c}市"} - {""}) if c else set()
        if not city_names:
            return []
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
                    q = q.limit(3000)
                    rows_out = [_candidate_from_row(r, t) for r, t in q.all()]
            except Exception:
                self._note_db_failure()
                logger.warning(
                    "poi_details: alternatives_pool db failed, memory fallback",
                    exc_info=True,
                )
                rows_out = []
        if not rows_out:
            nonactive = self._nonactive_pids()
            for pid, v in self._memory.items():
                if pid in nonactive:
                    continue
                if (v.get("city") or "").removesuffix("市") != c:
                    continue
                loc = v.get("location")
                rows_out.append(
                    _memory_candidate_row(
                        pid, v, f"POINT({loc[0]} {loc[1]})" if loc else None
                    )
                )
        heritage = self._heritage_names()
        for h in rows_out:
            h["_tier"] = apply_tier_tag(h, heritage)
        return rows_out

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
        多次烧 text 配额（2026-10-24 实测 200 连续超限）；盖戳即出
        stale_pois 窗口（2026-10-28 起窗口 30 天，未命中同样静默一月）。
        内存同步盖；DB UPDATE 失败只记日志不抛（冷却失败无害，下轮
        多查一次而已）。
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
