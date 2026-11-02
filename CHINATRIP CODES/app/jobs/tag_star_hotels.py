"""旅游星级饭店打标作业（CLI，backlog #11，POIS_DATASOURCE §3.2 行12）。

官方星级饭店名单（文旅部全国旅游星级饭店评定委员会年度公布，CSV 审阅包
轨①）-> 已匹配的 pois.tags 打 ``star_5`` / ``star_4``（词表对齐
``michelin_Nstar`` 小写风格）。与 tag_quality 的三点不同：
  1) 只打标、**不补建骨架行**（用户拍板：库内 3,753 行 hotel 全 active，
     名单未命中行进 unmatched_detail 供审阅，不许自动造行）；
  2) star_5/star_4 **互斥**（饭店升/降星时替换旧星标，其余 tags 保留）；
  3) ``--tags-source`` 记体系：官方名单=mct；GLM/ctrip 市场口径抽取=
     glm/ctrip，**不冒充官方**——行已是 mct 时低权威源不得降级覆盖。

匹配条件：城市一致（CITY_ALIASES 归一 + 去「市」后缀）+ 名称归一化
相似度 ≥0.85（名单无坐标，走 tag_quality 无坐标源严阈值；名称比对
覆盖 name_zh / name_en / name_aliases）。

默认 dry-run：只输出命中/未命中报告（即审阅包），``--apply`` 才落库；
落库逐行 commit（运维备忘：批量 UPDATE 必逐条 commit）。

用法：
    python -m app.jobs.tag_star_hotels --csv data/star_hotels.csv
        [--tags-source mct] [--apply] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from difflib import SequenceMatcher

from app.db import get_session_factory
from app.jobs.tag_quality import normalize_entry_city, normalize_name, same_city
from app.models import Poi
from app.services.poi_details import get_poi_detail_store

_NAME_COLS = ("Name", "name", "酒店名称", "名称", "hotel")
_CITY_COLS = ("City", "city", "城市", "所在城市")
_STAR_COLS = ("Star", "star", "星级", "等级", "star_level")

_NAME_THRESHOLD_STRICT = 0.85  # 无坐标源（名单）名称相似度下限，同 tag_quality

# tags_source 权威序：mct（文旅部官方）> glm/ctrip（市场口径抽取）；
# 行已持官方源时低权威源不得覆盖（不冒充官方）。
_SOURCE_RANK = {"mct": 2, "glm": 1, "ctrip": 1}

_STAR_TAG = {5: "star_5", 4: "star_4"}
_STAR_TOKEN_RE = re.compile(r"([45])")
_STAR_WORD = {"五": 5, "四": 4}


def _first(row: dict, cols: tuple[str, ...]) -> str | None:
    for col in cols:
        val = row.get(col)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


def parse_star(val: str | None) -> int | None:
    """星级列值 -> 5/4；其余（三星及以下、空、乱码）返回 None 不打标。

    认「5/4」「五星/四星」「五星级」「5星」「★★★★★/★★★★」；
    设计只落 star_5/star_4，三星及以下不在词表。
    """
    s = (val or "").strip()
    if not s:
        return None
    for ch, star in _STAR_WORD.items():
        if ch in s:
            return star
    stars = s.count("★")
    if stars in _STAR_TAG:
        return stars
    m = _STAR_TOKEN_RE.search(s)
    if m and int(m.group(1)) in _STAR_TAG:
        return int(m.group(1))
    return None


def map_row(row: dict) -> dict | None:
    """CSV 行 -> 统一 entry；缺名称或城市视为无效行（None）。"""
    name = _first(row, _NAME_COLS)
    city = _first(row, _CITY_COLS)
    if not name or not city:
        return None
    return {
        "name": name,
        "city": city,
        "star": parse_star(_first(row, _STAR_COLS)),
    }


def make_star_tag(star: int | None) -> str | None:
    """5/4 -> star_5/star_4；其余 None（词表外不打标）。"""
    if star in _STAR_TAG:
        return _STAR_TAG[star]
    return None


def _strip_city_prefix(norm: str, city_stem: str) -> str:
    """去掉名称开头的同城前缀（「上海和平饭店」->「和平饭店」）。

    城市已单独核验一致，前缀对区分同城两家店没有信息量，却会把
    「和平饭店」vs「上海和平饭店」这种同一家店压到阈值以下。
    """
    stem = normalize_name(city_stem)
    for pref in (f"{stem}市", stem):
        if pref and norm.startswith(pref) and len(norm) > len(pref):
            return norm[len(pref) :]
    return norm


def name_matches(entry_name: str, row, city_stem: str = "") -> float:
    """名单名称 vs 行（name_zh/name_en/name_aliases）的最佳归一相似度。

    每个候选同时比「原名」与「去同城前缀名」，取最大值。
    """
    cands = [getattr(row, "name_zh", None), getattr(row, "name_en", None)]
    cands += [a for a in (getattr(row, "name_aliases", None) or []) if a]
    target = normalize_name(entry_name)
    target_bare = _strip_city_prefix(target, city_stem) if city_stem else target
    best = 0.0
    for cand in cands:
        if not cand:
            continue
        norm = normalize_name(cand)
        best = max(best, SequenceMatcher(None, target, norm).ratio())
        if city_stem:
            bare = _strip_city_prefix(norm, city_stem)
            best = max(best, SequenceMatcher(None, target_bare, bare).ratio())
    return best


def row_matches(entry: dict, row) -> bool:
    """entry（名单行）是否命中 pois 行：城市一致 + 名称 ≥0.85。

    名单无坐标，故不走 tag_quality 的坐标距离闸，直接用严阈值
    （同黑珍珠无坐标口径）；名称比对容忍同城前缀有无。
    """
    city_stem = normalize_entry_city(entry["city"])
    if not same_city(city_stem, normalize_entry_city(getattr(row, "city", None))):
        return False
    return name_matches(entry["name"], row, city_stem) >= _NAME_THRESHOLD_STRICT


def plan_tags(row, tag: str) -> list[str] | None:
    """行打 tag 后的新 tags；无变化返回 None（幂等）。

    star_5/star_4 互斥：先摘掉旧星标再并入新标，其余 tags 保留原序。
    """
    old = list(row.tags or [])
    if tag in old:
        return None
    kept = [t for t in old if t not in _STAR_TAG.values()]
    return kept + [tag]


def load_rows(path: str, limit: int | None = None) -> list[dict]:
    """名单 CSV -> 原始 dict 行列表（utf-8-sig 容 BOM）。"""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return rows if limit is None else rows[:limit]


def collect_jobs(path: str, *, limit: int | None = None) -> tuple[list[dict], dict]:
    """读名单 -> jobs（entry+tag）；无效行/星标词表外行分别计数。"""
    jobs: list[dict] = []
    stats: dict = {
        "read": 0,
        "invalid": 0,
        "no_qualifying_star": 0,
        "no_star_detail": [],
    }
    for row in load_rows(path, limit=limit):
        stats["read"] += 1
        entry = map_row(row)
        if entry is None:
            stats["invalid"] += 1
            continue
        tag = make_star_tag(entry["star"])
        if tag is None:
            stats["no_qualifying_star"] += 1
            if len(stats["no_star_detail"]) < 20:
                stats["no_star_detail"].append(
                    {
                        "name": entry["name"],
                        "city": entry["city"],
                        "star": entry["star"],
                    }
                )
            continue
        jobs.append({"entry": entry, "tag": tag})
    return jobs, stats


def tag_hotels(
    session_factory, jobs: list[dict], *, tags_source: str, apply: bool = False
) -> dict:
    """打标已匹配 hotel 行（dry-run 默认；apply 落库逐行 commit）。

    只打标不建行：未命中进 unmatched_detail 供名单审阅（审阅包轨①）。
    """
    stats: dict = {
        "mode": "apply" if apply else "dry-run",
        "matched": 0,
        "tagged_rows": 0,
        "already_ok": 0,
        "kept_official": 0,
        "unmatched": 0,
        "unmatched_detail": [],
        "tagged_detail": [],
    }

    def add_detail(key: str, detail: dict) -> None:
        if len(stats[key]) < 20:
            stats[key].append(detail)

    cache: dict[str, list] = {}
    with session_factory() as session:
        for job in jobs:
            entry, tag = job["entry"], job["tag"]
            city_stem = normalize_entry_city(entry["city"])
            variants = sorted({city_stem, f"{city_stem}市"})
            key = "|".join(variants)
            candidates = cache.get(key)
            if candidates is None:
                candidates = (
                    session.query(Poi)
                    .filter(
                        Poi.category == "hotel",
                        Poi.status == "active",
                        Poi.city.in_(variants),
                    )
                    .all()
                )
                cache[key] = candidates
            hits = [row for row in candidates if row_matches(entry, row)]
            if not hits:
                stats["unmatched"] += 1
                add_detail(
                    "unmatched_detail",
                    {"name": entry["name"], "city": entry["city"], "tag": tag},
                )
                continue
            stats["matched"] += 1
            for row in hits:
                new_tags = plan_tags(row, tag)
                if new_tags is None and (row.tags_source or "") == tags_source:
                    stats["already_ok"] += 1
                    continue
                if new_tags is None and _SOURCE_RANK.get(
                    tags_source, 0
                ) < _SOURCE_RANK.get(row.tags_source or "", 0):
                    # 行已持更高权威源（如 mct），glm/ctrip 不覆盖
                    stats["kept_official"] += 1
                    continue
                if new_tags is None:
                    # 标已在但溯源缺失/较弱：只补 tags_source
                    row.tags_source = tags_source
                else:
                    row.tags = new_tags
                    row.tags_source = tags_source
                stats["tagged_rows"] += 1
                add_detail(
                    "tagged_detail",
                    {
                        "name": getattr(row, "name_zh", None),
                        "city": getattr(row, "city", None),
                        "tag": tag,
                    },
                )
                if apply:
                    session.commit()  # 逐行 commit（运维备忘）
        if apply:
            session.commit()  # 收尾兜底（dry-run 无脏写）
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "旅游星级饭店名单 -> pois.tags(star_5/star_4)+tags_source；只打标不建行"
        )
    )
    parser.add_argument("--csv", required=True, help="星级饭店名单 CSV 路径")
    parser.add_argument(
        "--tags-source",
        choices=sorted(_SOURCE_RANK),
        default="mct",
        help="体系溯源：mct=文旅部官方（默认）；glm/ctrip=市场口径，不冒充官方",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="落库（默认 dry-run 只出审阅报告）",
    )
    parser.add_argument("--limit", type=int, default=None)
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
        jobs, read_stats = collect_jobs(args.csv, limit=args.limit)
        result = tag_hotels(
            get_session_factory(),
            jobs,
            tags_source=args.tags_source,
            apply=args.apply,
        )
    except Exception as exc:  # 文件缺失 / DB 异常
        print(json.dumps({"error": str(exc)}, ensure_ascii=True))
        return 1
    stats = {
        "mode": result["mode"],
        "read": read_stats["read"],
        "invalid": read_stats["invalid"],
        "no_qualifying_star": read_stats["no_qualifying_star"],
        "matched": result["matched"],
        "tagged_rows": result["tagged_rows"],
        "already_ok": result["already_ok"],
        "kept_official": result["kept_official"],
        "unmatched": result["unmatched"],
        "no_star_detail": read_stats["no_star_detail"],
        "unmatched_detail": result["unmatched_detail"],
        "tagged_detail": result["tagged_detail"],
    }
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
