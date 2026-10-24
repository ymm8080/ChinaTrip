"""米其林/黑珍珠品质标签 + 补库作业（CLI，v2.5 餐厅底库）。

外部榜单（.csv/.json，两个源都 codeload.github.com 自动下载，见
ops/poi_monthly.cmd 与 ops/poi_blackpearl.cmd）：米其林指南
ngshiheng/michelin-my-maps（CSV）；黑珍珠 jyb635050-ai/gourmet-map
（blackpearl.json，2026-10-24 起替代人工导出）。做两件事：
  1) 打标签到已匹配的 restaurants.tags（JSONB 字符串数组，并集只升不降）；
  2) 未命中且城市已覆盖的条目 -> **补建骨架行**（用户拍板 2026-10-24
     「米其林黑珍珠的店如果不在表里应该添加」）：只写名称/城市/菜系/
     坐标/标签，不写 address/opening_hours 等时间敏感字段（铁律），
     留给后续回源链补齐。
城市闸门：仅补库内已覆盖城市（restaurants DISTINCT city），海外店
不进表；英文城市名先过 CITY_ALIASES 归一。
坐标系：两源实测均 WGS84 -> 匹配与入库前转 GCJ-02（库内 location
统一 GCJ-02，wgs84_location 存原值，同 osm_diff ingest 口径）。
黑珍珠含坐标的走坐标匹配，未编码成功的（lat/lng null）走严格名称
匹配（无坐标源 ≥0.85）。

匹配条件：城市一致（去「市」后缀）+ 名称归一化相似度：双方有坐标
≥0.75 且 haversine <200m；无坐标源（黑珍珠）≥0.85。

用法：
    python -m app.jobs.tag_quality --csv data/michelin.csv --kind michelin
        [--tag-overwrite] [--limit N]
    python -m app.jobs.tag_quality --csv data/blackpearl.json
        --kind black_pearl [--diamond 2]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
import unicodedata
import uuid
from difflib import SequenceMatcher

from app.db import get_session_factory
from app.models import Restaurant
from app.services.agent.plan import CITY_ALIASES
from app.services.coords import haversine_m, make_point, wgs84_to_gcj02
from app.services.poi_details import get_poi_detail_store

# CSV 列名弹性映射（米其林英文列 / 黑珍珠 gourmet-map json 键 / 中文导出列）。
# 米其林实测列（2026-10-24 codeload tar 包）：城市无独立列，在
# Location="Beijing, Chinese Mainland" 逗号前段；奖项在 Award
# （"1 Star"/"2 Stars"/"Bib Gourmand"），无 Star/Bib Gourmand 列。
# 黑珍珠实测键（2026-10-24 jyb635050-ai/gourmet-map blackpearl.json）：
# name/city/lat/lng/award("bp1".."bp3")，坐标全 WGS84。
_NAME_COLS = ("Name", "name", "餐厅名", "店名")
_LAT_COLS = ("Latitude", "latitude", "lat", "纬度")
_LON_COLS = ("Longitude", "longitude", "lon", "lng", "经度")
_CITY_COLS = ("City", "city", "城市")
_LOCATION_COLS = ("Location", "location", "位置")
_CUISINE_COLS = ("Cuisine", "cuisine", "菜系")
_URL_COLS = ("Url", "URL", "url", "WebsiteUrl", "链接")
_STAR_COLS = ("Star", "star")
_BIB_COLS = ("Bib Gourmand", "Bib_Gourmand", "bib_gourmand")
_AWARD_COLS = ("Award", "award", "奖项")
_DIAMOND_COLS = ("Diamond", "diamond", "钻石")

_NAME_THRESHOLD = 0.75  # 有坐标路径的名称相似度下限
_NAME_THRESHOLD_STRICT = 0.85  # 无坐标源（黑珍珠）名称相似度下限
_MAX_DISTANCE_M = 200.0  # 坐标距离上限（米）

# 港澳台进表（用户拍板 2026-10-24）：品质榜单的港澳台店不受底库
# 城市闸门限制，照常打标/补骨架行（底库 10 城不含它们）。
# 高雄/台中：米其林在台另有指南（2026-10-24 补齐「港澳台」全口径）。
_ALWAYS_COVERED = {"香港", "澳门", "台北", "高雄", "台中"}

_BRACKET_RE = re.compile(r"\([^)]*\)|【[^】]*】|\[[^\]]*\]")
_WKT_POINT_RE = re.compile(r"(?i)POINT\s*\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)")
_AWARD_STAR_RE = re.compile(r"^([123])\s+Stars?$")
_BP_AWARD_RE = re.compile(r"^bp([123])$", re.IGNORECASE)


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


def _entry_city(row: dict) -> str | None:
    """城市值：City 列优先；否则 Location 列「Beijing, Chinese Mainland」取逗号前段。"""
    raw = _first(row, _CITY_COLS)
    if raw is None:
        raw = _first(row, _LOCATION_COLS)
        if raw is None:
            return None
        raw = raw.split(",")[0]
    return raw.strip() or None


def map_row(row: dict) -> dict | None:
    """CSV 行 -> 统一 entry；无 name 列值视为无效行（None）。"""
    name = _first(row, _NAME_COLS)
    if not name:
        return None
    return {
        "name": name,
        "lat": _to_float(_first(row, _LAT_COLS)),
        "lon": _to_float(_first(row, _LON_COLS)),
        "city": _entry_city(row),
        "cuisine": _first(row, _CUISINE_COLS),
        "url": _first(row, _URL_COLS),
        "star": _first(row, _STAR_COLS),
        "bib": _first(row, _BIB_COLS),
        "award": _first(row, _AWARD_COLS),
        "diamond": _first(row, _DIAMOND_COLS),
    }


def make_tags(kind: str, entry: dict, diamond_default: int = 1) -> list[str]:
    """按数据源生成标签；无资格标签（如米其林无星无 Bib）返回空。"""
    tags: list[str] = []
    if kind == "michelin":
        star = (entry.get("star") or "").strip()
        if star in {"1", "2", "3"}:
            tags.append(f"michelin_{star}star")
        m = _AWARD_STAR_RE.match((entry.get("award") or "").strip())
        if m:
            tags.append(f"michelin_{m.group(1)}star")
        bib = (entry.get("bib") or "").strip().upper()
        award = (entry.get("award") or "").strip()
        if bib in {"TRUE", "1"} or award == "Bib Gourmand":
            tags.append("bib_gourmand")
        tags = list(dict.fromkeys(tags))  # 旧/新两种列型并存时去重
    elif kind == "black_pearl":
        diamond = (entry.get("diamond") or "").strip()
        if diamond not in {"1", "2", "3"}:
            m = _BP_AWARD_RE.match((entry.get("award") or "").strip())
            diamond = m.group(1) if m else str(diamond_default)
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


def normalize_entry_city(city: str | None) -> str:
    """CSV 城市 -> 库内口径：英文别名归一（CITY_ALIASES）+ 去「市」后缀。"""
    c = (city or "").strip()
    c = CITY_ALIASES.get(c.lower(), c)
    return c.removesuffix("市")


def entry_gcj02(entry: dict) -> tuple[float, float] | None:
    """entry 坐标 -> GCJ-02 (lon, lat)；无坐标返回 None。"""
    if entry.get("lon") is None or entry.get("lat") is None:
        return None
    if entry.get("datum") == "wgs84":
        return wgs84_to_gcj02(entry["lon"], entry["lat"])
    return (entry["lon"], entry["lat"])


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
    """entry（CSV 行）是否命中 restaurants 行：城市+名称(+坐标)。

    城市两侧都过 normalize_entry_city——米其林城市是英文
    （"Shanghai"），不过别名归一永远匹配不上中文库行。
    """
    if not same_city(
        normalize_entry_city(entry.get("city")),
        normalize_entry_city(getattr(row, "city", None)),
    ):
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
    gcj = entry_gcj02(entry)
    if gcj is not None and coords is not None:
        return within_distance(*gcj, *coords)
    if gcj is None:
        # 无坐标源（黑珍珠）：city+名称，阈值更严
        return best >= _NAME_THRESHOLD_STRICT
    # 源有坐标、库行 location NULL：只按名称+城市
    return True


def _load_rows(path: str) -> list[dict]:
    """榜单文件 -> 原始 dict 行列表（.json 走 list[dict]，其余 CSV）。"""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [row for row in data if isinstance(row, dict)]
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def collect_jobs(
    path: str,
    kind: str,
    *,
    diamond_default: int = 1,
    limit: int | None = None,
) -> tuple[list[dict], dict]:
    """读榜单（CSV/JSON）-> jobs（entry+tags）；无效行/无资格标签行分别计数。"""
    jobs: list[dict] = []
    stats: dict = {"read": 0, "invalid": 0, "no_tags": 0, "no_tags_detail": []}
    # 两个源实测都是 WGS84（米其林 CSV 原始值；黑珍珠 geo 链已统一转
    # WGS84，geo_method 里 dianping/qqmap 的 GCJ-02 均标注 to-wgs84）
    datum = "wgs84"
    for row in _load_rows(path):
        if limit is not None and stats["read"] >= limit:
            break
        stats["read"] += 1
        entry = map_row(row)
        if entry is None:
            stats["invalid"] += 1
            continue
        entry["datum"] = datum
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


def _slug_for(kind: str, city_stem: str, entry: dict) -> str:
    """稳定 source_poi_id：URL 尾段（米其林）或 名称哈希（黑珍珠）。"""
    url = (entry.get("url") or "").strip()
    if url:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug:
            return f"{city_stem}:{slug}"[:100]
    basis = f"{kind}|{city_stem}|{normalize_name(entry['name'])}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"{city_stem}:{digest}"[:100]


def _covered_cities(session) -> set[str]:
    """库内已覆盖城市（去「市」后缀）——补库闸门。"""
    rows = session.query(Restaurant.city).distinct().all()
    return {(c or "").removesuffix("市") for (c,) in rows if c}


def _new_restaurant(
    kind: str, entry: dict, city_stem: str, slug: str, tags: list[str]
) -> Restaurant:
    """补库骨架行：名称/城市/菜系/坐标/标签；时间敏感字段一概不写。"""
    row = Restaurant(
        id=uuid.uuid4(),
        source=kind,
        source_poi_id=slug,
        city=city_stem,
        name_zh=entry["name"],
        cuisine=(entry.get("cuisine") or None),
        tags=list(tags),
        tags_source=kind,
        status="active",
    )
    gcj = entry_gcj02(entry)
    if gcj is not None:
        row.location = make_point(*gcj)
        if entry.get("datum") == "wgs84":
            row.wgs84_location = make_point(entry["lon"], entry["lat"])
    return row


def tag_restaurants(
    session_factory, jobs: list[dict], *, kind: str, overwrite: bool = False
) -> dict:
    """打标已匹配行；未命中且城市已覆盖 -> 补建骨架行（幂等）。"""
    stats = {
        "matched": 0,
        "tagged_rows": 0,
        "appended": 0,
        "appended_detail": [],
        "unmatched": 0,
        "unmatched_detail": [],
    }

    def add_detail(key: str, detail: dict) -> None:
        if len(stats[key]) < 20:
            stats[key].append(detail)

    cache: dict[str, list] = {}
    seen_slugs: set[str] = set()
    with session_factory() as session:
        covered = _covered_cities(session)
        for job in jobs:
            entry, tags = job["entry"], job["tags"]
            city = (entry.get("city") or "").strip()
            if not city:
                stats["unmatched"] += 1
                add_detail(
                    "unmatched_detail",
                    {
                        "name": entry["name"],
                        "city": entry.get("city"),
                        "reason": "no_city",
                    },
                )
                continue
            city_stem = normalize_entry_city(city)
            if city_stem not in covered and city_stem not in _ALWAYS_COVERED:
                stats["unmatched"] += 1
                add_detail(
                    "unmatched_detail",
                    {
                        "name": entry["name"],
                        "city": city,
                        "reason": "city_not_covered",
                    },
                )
                continue
            variants = sorted({city_stem, f"{city_stem}市"})
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
            if hits:
                stats["matched"] += 1
                for row in hits:
                    new_tags = list(tags) if overwrite else merge_tags(row.tags, tags)
                    if new_tags != (row.tags or []):
                        row.tags = new_tags
                        row.tags_source = kind
                        stats["tagged_rows"] += 1
                continue
            slug = _slug_for(kind, city_stem, entry)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            existing = (
                session.query(Restaurant)
                .filter_by(source=kind, source_poi_id=slug)
                .one_or_none()
            )
            if existing is not None:
                # 上次已补建、本次名称匹配没接上：补标不重复建行
                stats["matched"] += 1
                new_tags = list(tags) if overwrite else merge_tags(existing.tags, tags)
                if new_tags != (existing.tags or []):
                    existing.tags = new_tags
                    existing.tags_source = kind
                    stats["tagged_rows"] += 1
                continue
            session.add(_new_restaurant(kind, entry, city_stem, slug, tags))
            stats["appended"] += 1
            add_detail(
                "appended_detail",
                {"name": entry["name"], "city": city_stem, "slug": slug},
            )
        session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="米其林/黑珍珠品质标签 -> restaurants.tags；未命中补建骨架行"
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
        "appended": result["appended"],
        "unmatched": result["unmatched"] + read_stats["no_tags"],
        "invalid": read_stats["invalid"],
        "tagged_rows": result["tagged_rows"],
        "unmatched_detail": (read_stats["no_tags_detail"] + result["unmatched_detail"])[
            :20
        ],
        "appended_detail": result["appended_detail"],
    }
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
