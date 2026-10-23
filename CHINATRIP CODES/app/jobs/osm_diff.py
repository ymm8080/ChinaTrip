"""OSM 每日增量导入作业（Geofabrik 中国区 .osc change file）。

数据链（DESIGN/feature_gap_and_dev_plan_2026-10-23.md §4.2）：
Geofabrik 日增文件（https://download.geofabrik.de/asia/china-updates/，
本 job 只管本地文件处理，不下载）→ osmium 流式解析 → 标签过滤 →
seed_upsert 落 pois 底库。

铁律：OSM 只发现骨架（名称/坐标/类别），绝不写时间字段（address /
opening_hours 等 display 细节归 app.jobs.refresh_pois 回源链维护）。

坐标系：OSM 是 WGS84，库内 pois.location 统一 GCJ-02（高德系），
wgs84_location 存原值——两列在 ingest 时成对写入。

城市语义：OSM 无城市概念，city 取 tag addr:city（去「市」后缀）；
缺失则 city="" 并计入 stats.no_city（idx_pois_city 命中率靠后续
回源补齐）。

餐厅类骨架（amenity=restaurant/cafe/bar/pub/nightclub）本期跳过
restaurants 表：其回源链稳定后再接，避免混入 pois 表语义。

用法：
    python -m app.jobs.osm_diff --osc <path.osc.gz|path.osc> \
        [--state data/osm_state.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from datetime import datetime, timezone

from app.models import Poi
from app.services.coords import make_point, wgs84_to_gcj02
from app.services.poi_seed import mark_status, seed_upsert

try:  # pyosmium 是可选重依赖（requirements.txt 已声明 osmium>=4.0）
    import osmium
except ImportError:  # pragma: no cover - 环境相关
    osmium = None

# 骨架发现范围（标签过滤）
TOURISM_CATEGORIES = {
    "attraction",
    "museum",
    "gallery",
    "zoo",
    "theme_park",
    "viewpoint",
}
AMENITY_CATEGORIES = {"restaurant", "cafe", "bar", "pub", "nightclub"}
LEISURE_CATEGORIES = {"park", "garden"}

_CJK = re.compile(r"[一-鿿]")


def should_import(tags: dict[str, str]) -> str | None:
    """骨架过滤：命中返回类别值（tourism/amenity/leisure 的值），否则 None。

    必须带中文 name（含 CJK 字符即算）；英文-only 或无名的对象一律放过。
    """
    if not _CJK.search(tags.get("name") or ""):
        return None
    for key, allowed in (
        ("tourism", TOURISM_CATEGORIES),
        ("amenity", AMENITY_CATEGORIES),
        ("leisure", LEISURE_CATEGORIES),
    ):
        val = tags.get(key)
        if val in allowed:
            return val
    return None


def _city_from_tags(tags: dict[str, str]) -> str:
    """addr:city 去掉「市」后缀（北京市 -> 北京），缺失返回空串。"""
    raw = (tags.get("addr:city") or "").strip()
    return raw[:-1] if raw.endswith("市") else raw


def handle_change(
    action: str,
    osm_type: str,
    osm_id: int,
    tags: dict[str, str],
    lonlat: tuple[float, float] | None,
    session_factory=None,
    *,
    stats: dict[str, int] | None = None,
    seed=seed_upsert,
    mark=mark_status,
) -> str:
    """处理单条 change 记录，返回 per-object 结果；stats 就地累加（可为 None）。

    create/modify 统一走 seed_upsert（upsert 语义自区分 created/exists）；
    delete 走 mark_status(status="inactive")。seed/mark 可注入替身便于测试。
    """
    source_poi_id = f"{osm_type[0]}{osm_id}"  # n123 / w456 / r789

    def _tick(key: str) -> None:
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1

    if action == "delete":
        marked = bool(mark(session_factory, Poi, "osm", source_poi_id, "inactive"))
        _tick("deleted")
        if marked:
            _tick("inactive_marked")
        return "deleted"

    category = should_import(tags)
    if category is None:
        _tick("skipped_no_name")
        return "skipped_no_name"
    if category in AMENITY_CATEGORIES:
        # 餐厅类本期不入库（restaurants 表待回源链稳定后接）
        _tick("skipped_restaurant")
        return "skipped_restaurant"
    if lonlat is None:
        # way/relation 无独立坐标（bbox 中心误差过大，本期不取）
        _tick("skipped_no_coords")
        return "skipped_no_coords"

    city = _city_from_tags(tags)
    if not city:
        _tick("no_city")

    wgs_lon, wgs_lat = lonlat
    gcj_lon, gcj_lat = wgs84_to_gcj02(wgs_lon, wgs_lat)
    result = seed(
        session_factory,
        Poi,
        source="osm",
        source_poi_id=source_poi_id,
        city=city,
        name_zh=tags.get("name"),
        category=category,
        lonlat=make_point(gcj_lon, gcj_lat),
        wgs84_lonlat=make_point(wgs_lon, wgs_lat),
        name_en=tags.get("name:en") or None,
        origin="osm",
    )
    if result in ("created", "exists"):
        _tick(result)
    return result


def _tags_dict(tag_list) -> dict[str, str]:
    """pyosmium TagList -> dict（兼容 3.x 成对迭代与 4.x mapping 两种协议）。"""
    out: dict[str, str] = {}
    for item in tag_list:
        if isinstance(item, str):  # 4.x：迭代产出 key，索引取值
            out[item] = tag_list[item]
        else:  # 3.x：迭代产出 (k, v) / Tag 对象
            out[item[0]] = item[1]
    return out


def parse_osc(
    path: str,
) -> Iterator[tuple[str, str, int, dict[str, str], tuple[float, float] | None]]:
    """流式迭代 osc change file（.osc / .osc.gz，osmium 自动识别压缩）。

    yield (action, osm_type, osm_id, tags, wgs84_lonlat)。osc 的
    create/modify 统一映射为 "modify"（seed_upsert 的 upsert 语义自区分
    created/exists），delete 由 visible=False 识别；仅 node 携带坐标，
    way/relation 恒为 None。
    """
    if osmium is None:
        raise RuntimeError(
            "pyosmium 未安装 — pip install 'osmium>=4.0'（requirements.txt 已声明）"
        )
    for obj in osmium.FileProcessor(path).with_locations():
        if isinstance(obj, osmium.osm.Node):
            osm_type = "node"
            loc = obj.location
            lonlat = (loc.lon, loc.lat) if loc.valid() else None
        elif isinstance(obj, osmium.osm.Way):
            osm_type, lonlat = "way", None
        else:
            osm_type, lonlat = "relation", None
        action = "modify" if obj.visible else "delete"
        yield action, osm_type, obj.id, _tags_dict(obj.tags), lonlat


def _new_stats() -> dict[str, int]:
    return {
        "processed": 0,
        "created": 0,
        "exists": 0,
        "skipped_no_name": 0,
        "skipped_no_coords": 0,
        "no_city": 0,
        "deleted": 0,
        "inactive_marked": 0,
        # 骨架过滤命中但本期不入库（restaurants 表待回源链稳定后接）
        "skipped_restaurant": 0,
    }


def _write_state(path: str, osc_path: str, stats: dict[str, int]) -> None:
    """写水位文件（应用幂等，重复跑只是多一批 exists）。"""
    state = {
        "last_osc": os.path.basename(osc_path),
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "created": stats["created"],
        "deleted": stats["deleted"],
    }
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OSM 日增 (.osc) 增量导入 pois 底库（骨架：名称/坐标/类别）"
    )
    parser.add_argument(
        "--osc", required=True, help="Geofabrik 日增文件路径（.osc / .osc.gz）"
    )
    parser.add_argument("--state", default="data/osm_state.json", help="水位文件路径")
    args = parser.parse_args(argv)

    if osmium is None:
        print(
            json.dumps(
                {
                    "error": "pyosmium not installed — "
                    "install osmium>=4.0 (declared in requirements.txt)"
                },
                ensure_ascii=True,
            )
        )
        return 3

    from app.services.poi_details import get_poi_detail_store

    if not get_poi_detail_store().ping():
        print(
            json.dumps(
                {
                    "error": "database unreachable — "
                    "start docker db (docker compose up -d db) "
                    "or check database_url"
                },
                ensure_ascii=True,
            )
        )
        return 1

    from app.db import get_session_factory

    stats = _new_stats()
    session_factory = get_session_factory()
    for action, osm_type, osm_id, tags, lonlat in parse_osc(args.osc):
        stats["processed"] += 1
        handle_change(
            action,
            osm_type,
            osm_id,
            tags,
            lonlat,
            session_factory=session_factory,
            stats=stats,
        )
    _write_state(args.state, args.osc, stats)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
