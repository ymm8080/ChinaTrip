"""博物馆分级名单导入作业（v2.5 参考资源域，2026-10-25/26）。

国家文物局定级、中国博物馆协会核定公布的「国家一/二/三级博物馆」
名单，作为参考资源骨架行导入 pois——与 unesco/5a 名单行同构：
source 按级别一源一级（museum1/museum2/museum3），tags 注入人类可读
等级标签（如「国家一级博物馆」，LLM 选点提示词与读侧直接可见），
name_aliases 带曾用名（湖南博物院 ← 湖南省博物馆）。

国家重点美术馆体系（文旅部美术馆评估，与博物馆定级并行）自
2026-10-26 起同作业收录（data/art_museums.csv）：source=artmuseum，
grade=国家重点美术馆 → tags=[国家重点美术馆]（origin=mct）；
grade=未评级 → 仅骨架、无等级标签（origin=curated，如浦东美术馆）。

铁律对齐：只写骨架（名称/城市/类别/标签/别名），不写 hours/price
等时间敏感字段；坐标留空，由回源链（refresh_pois / enrich_*）后续
补齐。权威口径见工作区调研《博物馆分级数据源调研.md》（2026-10-25）：
现行依据《博物馆定级评估办法》2019-12 修订版（文物博发〔2020〕2 号），
定级每三年集中一次；一级名单五批累计 327 家（截至 2026-10 无第六批）。

数据文件 data/museum_grades.csv（UTF-8），列：
    name_zh,province,city,grade,batch,alias_zh,source_url
grade ∈ 国家一级博物馆/国家二级博物馆/国家三级博物馆/国家重点美术馆/
未评级（容忍「一级」等简写）；alias_zh 多别名用 ';' 分隔；city 缺省
回退 province（直辖市省市同名）。判重键 (source, source_poi_id)，
source_poi_id = source 前缀 + 名称 SHA1——幂等重跑只补新增，不覆盖
已有行（骨架铁律，同 poi_seed）。

用法：
    python -m app.jobs.import_museum_grades --csv data/museum_grades.csv
        [--dry-run] [--limit N]
    python -m app.jobs.import_museum_grades --csv data/art_museums.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys

from sqlalchemy import func

from app.models import Poi
from app.services.poi_seed import seed_upsert

_GRADE_SOURCE: dict[str, str] = {
    "国家一级博物馆": "museum1",
    "国家二级博物馆": "museum2",
    "国家三级博物馆": "museum3",
    "国家重点美术馆": "artmuseum",  # 文旅部美术馆评估体系（2026-10-26 并入）
    "未评级": "artmuseum",  # 无全国性等级的策展馆：只进骨架，无标签
}
_SOURCE_LABEL: dict[str, str] = {v: k for k, v in _GRADE_SOURCE.items()}
_SOURCE_SLUG: dict[str, str] = {
    "museum1": "m1",
    "museum2": "m2",
    "museum3": "m3",
    "artmuseum": "a1",
}
_TAGGED_GRADES = frozenset(_GRADE_SOURCE) - {"未评级"}


def grade_source(grade: str | None) -> str | None:
    """等级文案 → source；容忍「一级/二级/三级」简写，未知返回 None。"""
    g = (grade or "").strip()
    if g in _GRADE_SOURCE:
        return _GRADE_SOURCE[g]
    for full, src in _GRADE_SOURCE.items():
        if g and g in full:
            return src
    return None


def slug_for(level: int, name_zh: str) -> str:
    """稳定伪 id：m<级别>_<名称 SHA1 前 12 位>（同 tag_quality 名称哈希口径）。"""
    digest = hashlib.sha1(name_zh.encode("utf-8")).hexdigest()[:12]
    return f"m{level}_{digest}"


def slug_for_source(src: str, name_zh: str) -> str:
    """按 source 前缀的稳定伪 id（artmuseum→a1_ 等），与 slug_for 同哈希。"""
    digest = hashlib.sha1(name_zh.encode("utf-8")).hexdigest()[:12]
    return f"{_SOURCE_SLUG[src]}_{digest}"


def load_rows(csv_path: str) -> tuple[list[dict], int]:
    """CSV → 种子行列表；返回 (rows, invalid)。无效行=缺名称/缺城市/等级不明。"""
    rows: list[dict] = []
    invalid = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            name = (raw.get("name_zh") or "").strip()
            src = grade_source(raw.get("grade"))
            city = (raw.get("city") or "").strip()
            city = city or (raw.get("province") or "").strip()
            if not name or src is None or not city:
                invalid += 1
                continue
            grade = (raw.get("grade") or "").strip()
            aliases = [
                a.strip() for a in (raw.get("alias_zh") or "").split(";") if a.strip()
            ]
            rows.append(
                {
                    "source": src,
                    "source_poi_id": slug_for_source(src, name),
                    "city": city.removesuffix("市"),
                    "name_zh": name,
                    "label": grade if grade in _TAGGED_GRADES else None,
                    "origin": (
                        "cma"
                        if src.startswith("museum")
                        else ("mct" if grade in _TAGGED_GRADES else "curated")
                    ),
                    "batch": (raw.get("batch") or "").strip(),
                    "aliases": aliases,
                }
            )
    return rows, invalid


def run_import(factory, rows: list[dict], *, dry_run: bool = False) -> dict:
    """按行导入；dry_run 只读存在性检查，不触发写路径。"""
    stats: dict = {
        "total": len(rows),
        "created": 0,
        "exists": 0,
        "skipped": 0,
        "by_source": {},
    }
    for r in rows:
        stats["by_source"][r["source"]] = stats["by_source"].get(r["source"], 0) + 1
        if dry_run:
            with factory() as session:
                hit = (
                    session.query(Poi)
                    .filter_by(source=r["source"], source_poi_id=r["source_poi_id"])
                    .one_or_none()
                )
            stats["exists" if hit is not None else "created"] += 1
            continue
        label = r.get("label")
        out = seed_upsert(
            factory,
            Poi,
            source=r["source"],
            source_poi_id=r["source_poi_id"],
            city=r["city"],
            name_zh=r["name_zh"],
            category="博物馆/纪念馆",
            origin=r.get("origin", "cma"),
            tags=[label] if label else None,
            tags_source="cma" if label else None,
            name_aliases=r["aliases"] or None,
        )
        stats[out] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="博物馆分级名单导入（幂等骨架 upsert）"
    )
    parser.add_argument("--csv", required=True, help="data/museum_grades.csv")
    parser.add_argument("--dry-run", action="store_true", help="只读检查，不写库")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 行（调试）")
    args = parser.parse_args(argv)

    if not os.path.exists(args.csv):
        print(json.dumps({"error": f"csv not found: {args.csv}"}, ensure_ascii=True))
        return 1
    rows, invalid = load_rows(args.csv)
    if args.limit > 0:
        rows = rows[: args.limit]

    from app.db import get_session_factory

    factory = get_session_factory()
    try:
        with factory() as session:
            session.query(func.count(Poi.id)).scalar()  # ping
    except Exception:
        print(
            json.dumps(
                {"error": "db_unreachable: check DATABASE_URL / db service"},
                ensure_ascii=True,
            )
        )
        return 1

    stats = run_import(factory, rows, dry_run=args.dry_run)
    stats["invalid_rows"] = invalid
    print(json.dumps(stats, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
