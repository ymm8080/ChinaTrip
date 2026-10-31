"""POI 骨架行回源校验（外部源仅候选，高德/携程拥有真相）.

铁律（DESIGN §4.2 / 用户拍板 2026-10-23）：pois/restaurants 里的外部源
骨架行（source="chinatravel"/"osm"，只有名称/坐标/类别，无
hours/phone）不能直接当真相用。本模块用当前图商（vendor 参数）
关键词搜索匹配骨架行——"amap" 走高德 place/text，"baidu" 走
百度 place/v2/search（候选坐标已在客户端边界统一转 GCJ-02）：

  命中（名称相似度 ≥ min_similarity 且距离 ≤ max_distance_m）→
    「升级」该行：source→vendor、source_poi_id→图商 POI ID
    （高德 ID / 百度 uid），顺手回填 address/phone/rating/photos
    （只填空字段），rating_source/photos_source 标 vendor；
    origin 不动（保留初始发现渠道）；hours 不在此层写
    （refresh_pois 链② place/detail 补）。
  高德/图商 ID 已被其它行占用 → duplicate，不升级（防串行）。
  无候选/相似度不足/距离超限 → miss，行原样保留（不 inactive 不删除）。
  amap=None → error，不 crash；单行异常 → 记 warning 按 miss 保留
  （2026-10-30 起主源报错可由 fallback 客户端重试：百度主源、
  失败行回退高德，用户拍板）。

坐标提取：骨架行 location 为 geoalchemy2 点几何——真实库行为
WKBElement，测试/导入路径为 WKTElement（coords.make_point）。shapely
不在依赖里，故此处手解两种格式（纯 stdlib struct），不引新依赖。
"""

from __future__ import annotations

import difflib
import logging
import re
import struct
import unicodedata
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.elements import WKBElement, WKTElement

from app.services.amap_client import AmapQuotaExhaustedError
from app.services.coords import haversine_m

logger = logging.getLogger(__name__)

# 括号内容（中英文圆/方/花/六角括号）多为分店名/说明，匹配前剔除
_BRACKETS_RE = re.compile(r"\([^)]*\)|（[^）]*）|【[^】]*】|\[[^\]]*\]|\{[^}]*\}")
_WS_RE = re.compile(r"\s+")


def normalize_name(s: str) -> str:
    """匹配用名称归一：NFKC 全角→半角、去括号内容、去空白、lower。"""
    text = unicodedata.normalize("NFKC", s or "")
    text = _BRACKETS_RE.sub("", text)
    return _WS_RE.sub("", text).lower()


def name_similar(a: str, b: str) -> float:
    """归一化后的 0-1 相似度（difflib SequenceMatcher.ratio）。"""
    return difflib.SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def _point_lonlat(geom: Any) -> tuple[float, float] | None:
    """geoalchemy2 点几何 → (lon, lat)；解析失败/非点返回 None。"""
    if geom is None:
        return None
    try:
        if isinstance(geom, WKTElement):
            desc = (geom.desc or "").strip()
            inner = desc[desc.index("(") + 1 : desc.rindex(")")]
            parts = inner.split()
            if len(parts) < 2:
                return None
            return float(parts[0]), float(parts[1])
        if isinstance(geom, WKBElement):
            data = geom.data
            # psycopg2 给 hex str，psycopg3 给 bytes（真实 PostGIS 路径）
            raw = bytes.fromhex(data) if isinstance(data, str) else bytes(data)
            bo = "<" if raw[0] else ">"  # 首字节：字节序标记
            gtype = struct.unpack(bo + "I", raw[1:5])[0]
            if gtype & 0xFF != 1:  # 非 POINT
                return None
            off = 5 + (4 if gtype & 0x20000000 else 0)  # EWKB SRID 前缀
            lon, lat = struct.unpack(bo + "dd", raw[off : off + 16])
            return lon, lat
    except (ValueError, struct.error, IndexError):
        return None
    return None


def _rating_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_hit(
    candidates: list[Any],
    row_ll: tuple[float, float],
    name: str,
    *,
    min_similarity: float,
    max_distance_m: float,
) -> dict | None:
    """双闸选首个命中候选（名称相似度 + 距离；候选缺坐标直接跳过）。"""
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        if name_similar(name, cand.get("name") or "") < min_similarity:
            continue
        cand_ll = cand.get("location") or {}
        if not cand_ll:
            continue  # 缺坐标无法确认距离，铁律：宁缺勿错
        dist = haversine_m(row_ll[0], row_ll[1], cand_ll["lon"], cand_ll["lat"])
        if dist > max_distance_m:
            continue
        return cand
    return None


async def match_and_enrich(
    session_factory: Any,
    model: Any,
    rows: list[Any],
    amap: Any,
    *,
    max_distance_m: float = 500,
    min_similarity: float = 0.75,
    vendor: str = "amap",
    fallback: Any = None,
    fallback_vendor: str = "amap",
) -> dict:
    """逐行图商关键词匹配并升级骨架行；返回分类统计。

    vendor 决定升级命名空间："amap"→source="amap"+高德 ID（默认，
    兼容既有调用）；"baidu"→source="baidu"+百度 uid（2026-10-30 起
    refresh_pois --match 百度同权生效）。候选 dict 由各客户端归一成
    同构形状（AmapClient/BaiduClient._normalize_poi）。

    每行流程：amap.search_poi(f"{city}{name}", city=city) → 候选逐个
    判 name_similar + haversine 距离 → 首个全过的候选升级该行
    （source→vendor、source_poi_id→图商 ID、只填空的 address/phone/
    rating/photos）。任一侧缺坐标 → 候选无法确认距离 → 不过
    （行缺坐标时不烧搜索配额，直接 miss）。

    fallback（2026-10-30 用户拍板「失败行回退高德」）：主源无候选或
    搜索报错（非配额）时，用该客户端重试同一查询、同一双闸；命中按
    fallback_vendor 命名空间升级（百度主源→高德兜底）。fallback 配额
    尽只停 fallback 重试，不中止主源循环。
    amap=None → 全部 error；单行异常 → 该行 error 后继续；
    quota 尽（AmapQuotaExhaustedError，高德 10021 / 百度 301/302
    共用同一异常）→ stats["quota_exhausted"]=1 并中止剩余行
    （别再逐行硬敲烧尽配额，2026-10-24 实测）。
    """
    stats = {"matched": 0, "duplicate": 0, "miss": 0, "error": 0}
    if amap is None:
        stats["error"] = len(rows)
        return stats
    quota_dead = False
    fb_dead = False
    for row in rows:
        if quota_dead:
            break
        try:
            name = (row.name_zh or "").strip()
            city = (row.city or "").removesuffix("市")
            if not name:
                stats["error"] += 1
                continue
            row_ll = _point_lonlat(row.location)
            if row_ll is None:
                # 铁律：行缺坐标无法确认距离，宁缺勿错；
                # 别白烧一次搜索配额（2026-10-30 移到搜索前）
                stats["miss"] += 1
                continue
            try:
                candidates = await amap.search_poi(f"{city}{name}", city=city or None)
            except AmapQuotaExhaustedError:
                quota_dead = True
                stats["quota_exhausted"] = 1
                break
            except Exception:
                logger.warning(
                    "poi_backfill: primary search failed for row %s",
                    getattr(row, "id", "?"),
                    exc_info=True,
                )
                candidates = []
            hit = _pick_hit(
                candidates,
                row_ll,
                name,
                min_similarity=min_similarity,
                max_distance_m=max_distance_m,
            )
            hit_vendor = vendor
            if hit is None and fallback is not None and not fb_dead and not quota_dead:
                # 主源无候选/报错 → fallback 客户端重试同查询（百度主源、高德兜底）
                try:
                    fb_cands = await fallback.search_poi(
                        f"{city}{name}", city=city or None
                    )
                except AmapQuotaExhaustedError:
                    fb_dead = True  # 只停 fallback 重试，不动主源循环
                except Exception:
                    logger.warning(
                        "poi_backfill: fallback search failed for row %s",
                        getattr(row, "id", "?"),
                        exc_info=True,
                    )
                else:
                    hit = _pick_hit(
                        fb_cands,
                        row_ll,
                        name,
                        min_similarity=min_similarity,
                        max_distance_m=max_distance_m,
                    )
                    if hit is not None:
                        hit_vendor = fallback_vendor
            if hit is None:
                # 无候选/相似度不足：保留骨架，不 inactive 不删除
                stats["miss"] += 1
                continue
            matched_id = hit.get("source_poi_id")
            if not matched_id:
                stats["error"] += 1
                continue
            with session_factory() as session:
                target = session.get(model, row.id)
                if target is None:
                    stats["error"] += 1
                    continue
                taken = (
                    session.query(model)
                    .filter_by(source=hit_vendor, source_poi_id=matched_id)
                    .all()
                )
                if any(r.id != target.id for r in taken):
                    # 图商 ID 已被其它行占用：不升级，防两行串成同一点
                    stats["duplicate"] += 1
                    continue
                target.source = hit_vendor
                target.source_poi_id = matched_id
                if hit.get("address") and not target.address:
                    target.address = hit["address"]
                if hit.get("phone") and not target.phone:
                    target.phone = hit["phone"]
                rating = _rating_float(hit.get("rating"))
                if rating is not None and target.rating is None:
                    target.rating = rating
                    target.rating_source = hit_vendor
                photos = hit.get("photos")
                if photos and not target.photos:
                    target.photos = photos
                    target.photos_source = hit_vendor
                target.updated_at = datetime.now(timezone.utc)
                session.commit()
            stats["matched"] += 1
        except Exception:
            logger.warning(
                "poi_backfill: match failed for row %s",
                getattr(row, "id", "?"),
                exc_info=True,
            )
            stats["error"] += 1
    return stats


def skeleton_targets(
    session_factory: Any,
    model: Any,
    *,
    sources: tuple[str, ...] = ("chinatravel", "osm"),
    limit: int = 200,
) -> list[Any]:
    """指定 source 且 active 的骨架行（回源校验目标），DB 异常返回 []。"""
    try:
        with session_factory() as session:
            rows = (
                session.query(model)
                .filter(model.source.in_(list(sources)), model.status == "active")
                .limit(limit)
                .all()
            )
    except Exception:
        logger.warning("poi_backfill: skeleton query failed", exc_info=True)
        return []
    # Python 侧复筛：SQL 过滤已被 fake session 简化时仍保证语义
    return [
        r for r in rows if (r.source or "") in sources and (r.status or "") == "active"
    ]
