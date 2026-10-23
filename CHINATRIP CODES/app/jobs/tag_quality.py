"""米其林/黑珍珠品质标签作业（CLI，v2.5 餐厅底库）。

外部 CSV（米其林指南 github ngshiheng/michelin-my-maps / 美团黑珍珠
人工导出）打标签到 restaurants.tags（JSONB 字符串数组），铁律：
  - 只匹配**已存在**的 restaurants 行，绝不新建行；
  - 未命中进 unmatched 报告；
  - 匹配条件：城市一致（去「市」后缀）+ 名称归一化相似度：
    双方有坐标 ≥0.75 且 haversine <200m；无坐标源（黑珍珠）≥0.85。

用法：
    python -m app.jobs.tag_quality --csv data/michelin.csv --kind michelin
        [--tag-overwrite] [--limit N]
    python -m app.jobs.tag_quality --csv data/black_pearl.csv
        --kind black_pearl [--diamond 2]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import sys
import unicodedata
from difflib import SequenceMatcher

from app.db import get_session_factory
from app.models import Restaurant
from app.services.coords import haversine_m
from app.services.poi_details import get_poi_detail_store

# CSV 列名弹性映射（米其林英文列 / 黑珍珠中文导出列）
_NAME_COLS = ("Name", "name", "餐厅名", "店名")
_LAT_COLS = ("Latitude", "latitude", "lat", "纬度")
_LON_COLS = ("Longitude", "longitude", "lon", "经度")
_CITY_COLS = ("City", "city", "城市")
_STAR_COLS = ("Star", "star")
_BIB_COLS = ("Bib Gourmand", "Bib_Gourmand", "bib_gourmand")
_DIAMOND_COLS = ("Diamond", "diamond", "钻石")

_NAME_THRESHOLD = 0.75  # 有坐标路径的名称相似度下限
_NAME_THRESHOLD_STRICT = 0.85  # 无坐标源（黑珍珠）名称相似度下限
_MAX_DISTANCE_M = 200.0  # 坐标距离上限（米）

_BRACKET_RE = re.compile(r"\([^)]*\)|【[^】]*】|\[[^\]]*\]")
_WKT_POINT_RE = re.compile(r"(?i)POINT\s*\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)")


def _first(row: dict, cols: tuple[str, ...]) -> str | None:
    for col in cols:
        val = row.get(col)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


def _to_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def map_row(row: dict) -> dict | None:
    """CSV 行 -> 统一 entry；无 name 列值视为无效行（None）。"""
    name = _first(row, _NAME_COLS)
    if not name:
        return None
    return {
        "name": name,
        "lat": _to_float(_first(row, _LAT_COLS)),
        "lon": _to_float(_first(row, _LON_COLS)),
        "city": _first(row, _CITY_COLS),
        "star": _first(row, _STAR_COLS),
        "bib": _first(row, _BIB_COLS),
        "diamond": _first(row, _DIAMOND_COLS),
    }


def make_tags(kind: str, entry: dict, diamond_default: int = 1) -> list[str]:
    """按数据源生成标签；无资格标签（如米其林无星无 Bib）返回空。"""
    tags: list[str] = []
    if kind == "michelin":
        star = (entry.get("star") or "").strip()
        if star in {"1", "2", "3"}:
            tags.append(f"michelin_{star}star")
        if (entry.get("bib") or "").strip().upper() in {"TRUE", "1"}:
            tags.append("bib_gourmand")
    elif kind == "black_pearl":
        diamond = (entry.get("diamond") or "").strip()
        if diamond not in {"1", "2", "3"}:
            diamond = str(diamond_default)
        tags.append(f"black_pearl_{diamond}diamond")
    return tags


def normalize_name(name: str) -> str:
    """名称归一化：全角转半角、去括号内容、去空白、lower。"""
    s = unicodedata.normalize("NFKC", name or "")
    s = _BRACKET_RE.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def name_similar(a: str, b: str, threshold: float = _NAME_THRESHOLD) -> bool:
    return (
        SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio() >= threshold
    )


def same_city(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.strip().removesuffix("市") == b.strip().removesuffix("市")


def within_distance(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    max_m: float = _MAX_DISTANCE_M,
) -> bool:
    return haversine_m(lon1, lat1, lon2, lat2) < max_m


def merge_tags(old: list | None, new: list[str]) -> list[str]:
    """旧 tags ∪ 新标签，去重保序。"""
    merged = [t for t in (old or [])]
    for tag in new:
        if tag not in merged:
            merged.append(tag)
    return merged


def _wkb_point_xy(data) -> tuple[float, float] | None:
    """解析 PostGIS EWKB POINT（兼容 SRID 前缀），返回 (lon, lat)。"""
    if isinstance(data, memoryview):
        data = bytes(data)
    if not isinstance(data, (bytes, bytearray)) or len(data) < 21:
        return None
    endian = "<" if data[0] == 1 else ">"
    try:
        gtype = struct.unpack_from(f"{endian}I", data, 1)[0]
        offset = 5
        if gtype & 0x2000_0000:  # EWKB SRID flag
            offset += 4
        if gtype & 0xFF != 1:  # 非 POINT
            return None
        return struct.unpack_from(f"{endian}dd", data, offset)
    except struct.error:
        return None


def _point_coords(element) -> tuple[float, float] | None:
    """geoalchemy2 location（WKT/WKB Element）-> (lon, lat)，失败 None。"""
    if element is None:
        return None
    data = getattr(element, "data", None)
    if isinstance(data, str):  # WKTElement
        m = _WKT_POINT_RE.match(data.strip())
        return (float(m[1]), float(m[2])) if m else None
    if data is None:
        return None
    return _wkb_point_xy(data)


def row_matches(entry: dict, row) -> bool:
    """entry（CSV 行）是否命中 restaurants 行：城市+名称(+坐标)。"""
    if not same_city(entry.get("city"), getattr(row, "city", None)):
        return False
    best = 0.0
    for cand in (getattr(row, "name_zh", None), getattr(row, "name_en", None)):
        if cand:
            best = max(
                best,
                SequenceMatcher(
                    None, normalize_name(entry["name"]), normalize_name(cand)
                ).ratio(),
            )
    if best < _NAME_THRESHOLD:
        return False
    coords = _point_coords(getattr(row, "location", None))
    has_src = entry.get("lon") is not None and entry.get("lat") is not None
    if has_src and coords is not None:
        return within_distance(entry["lon"], entry["lat"], *coords)
    if not has_src:
        # 无坐标源（黑珍珠）：city+名称，阈值更严
        return best >= _NAME_THRESHOLD_STRICT
    # 源有坐标、库行 location NULL：只按名称+城市
    return True


def collect_jobs(
    path: str,
    kind: str,
    *,
    diamond_default: int = 1,
    limit: int | None = None,
) -> tuple[list[dict], dict]:
    """读 CSV -> jobs（entry+tags）；无效行/无资格标签行分别计数。"""
    jobs: list[dict] = []
    stats: dict = {"read": 0, "invalid": 0, "no_tags": 0, "no_tags_detail": []}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if limit is not None and stats["read"] >= limit:
                break
            stats["read"] += 1
            entry = map_row(row)
            if entry is None:
                stats["invalid"] += 1
                continue
            tags = make_tags(kind, entry, diamond_default=diamond_default)
            if not tags:
                stats["no_tags"] += 1
                if len(stats["no_tags_detail"]) < 20:
                    stats["no_tags_detail"].append(
                        {
                            "name": entry["name"],
                            "city": entry["city"],
                            "reason": "no_qualifying_tag",
                        }
                    )
                continue
            jobs.append({"entry": entry, "tags": tags})
    return jobs, stats


def tag_restaurants(
    session_factory, jobs: list[dict], *, kind: str, overwrite: bool = False
) -> dict:
    """把标签打到已存在的 restaurants 行上；未命中只记录不建行。"""
    stats = {"matched": 0, "tagged_rows": 0, "unmatched": 0, "unmatched_detail": []}

    def add_detail(detail: dict) -> None:
        if len(stats["unmatched_detail"]) < 20:
            stats["unmatched_detail"].append(detail)

    cache: dict[str, list] = {}
    with session_factory() as session:
        for job in jobs:
            entry, tags = job["entry"], job["tags"]
            city = (entry.get("city") or "").strip()
            if not city:
                stats["unmatched"] += 1
                add_detail(
                    {
                        "name": entry["name"],
                        "city": entry.get("city"),
                        "reason": "no_city",
                    }
                )
                continue
            stem = city.removesuffix("市")
            variants = sorted({city, stem, f"{stem}市"})
            key = "|".join(variants)
            candidates = cache.get(key)
            if candidates is None:
                candidates = (
                    session.query(Restaurant)
                    .filter(Restaurant.city.in_(variants))
                    .all()
                )
                cache[key] = candidates
            hits = [row for row in candidates if row_matches(entry, row)]
            if not hits:
                stats["unmatched"] += 1
                add_detail(
                    {"name": entry["name"], "city": city, "reason": "no_db_match"}
                )
                continue
            stats["matched"] += 1
            for row in hits:
                new_tags = list(tags) if overwrite else merge_tags(row.tags, tags)
                if new_tags != (row.tags or []):
                    row.tags = new_tags
                    row.tags_source = kind
                    stats["tagged_rows"] += 1
        session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="米其林/黑珍珠品质标签 -> restaurants.tags（只改已存在行）"
    )
    parser.add_argument("--csv", required=True, help="外部 CSV 路径")
    parser.add_argument("--kind", required=True, choices=["michelin", "black_pearl"])
    parser.add_argument(
        "--tag-overwrite",
        action="store_true",
        dest="tag_overwrite",
        help="替换 tags 而非并集（源方修正重跑用）",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--diamond",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="黑珍珠钻级（CSV 无 Diamond 列时用）",
    )
    args = parser.parse_args(argv)

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
    try:
        jobs, read_stats = collect_jobs(
            args.csv, args.kind, diamond_default=args.diamond, limit=args.limit
        )
        result = tag_restaurants(
            get_session_factory(),
            jobs,
            kind=args.kind,
            overwrite=args.tag_overwrite,
        )
    except Exception as exc:  # 文件缺失 / DB 异常
        print(json.dumps({"error": str(exc)}, ensure_ascii=True))
        return 1
    stats = {
        "read": read_stats["read"],
        "matched": result["matched"],
        "unmatched": result["unmatched"] + read_stats["no_tags"],
        "invalid": read_stats["invalid"],
        "tagged_rows": result["tagged_rows"],
        "unmatched_detail": (read_stats["no_tags_detail"] + result["unmatched_detail"])[
            :20
        ],
    }
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
