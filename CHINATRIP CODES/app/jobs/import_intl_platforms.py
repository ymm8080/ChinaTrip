"""国际平台中国荐点导入（POIS DATASOURCE 10/11 号审阅文件，2026-10-27）。

数据源：data/intl_platforms.csv（由工作区 build_intl_platforms_picks.py 从
10_国际平台中国荐点_AI规划师与各国Agency.csv 与 11_短视频与社媒中国荐点
_TikTok-Instagram-YouTube.csv 转写：类型过滤（tour/票务/住宿/餐饮/频道/
hashtag 行不入）+ 产品规则过滤（红色/政治场所不入）+ 繁转简 + 集内去重）。

行内动作与 import_intl_picks 同语义（用户 2026-10-26 指令）：
  库内已有正名/别名行 → 追加 intl+明细站点 tags，tags_source=主站点，
  source 列保留原值（enrich/tier/refresh 三条活链不断）；
  查无 → 插入 source=主站点 骨架行（category=attraction，tags=国际+站点）。
本作业的名称匹配在等值之上加「同城双向包含」（短名≥2 字），以覆盖
故宫↔故宫博物院、天坛↔天坛公园 这类缩写/全称跨源行——用户 2026-10-27
指令「add to pois，注意去重」的主诉求。同批行间先集内去重（转换器完成），
作业内仍按行序 append rows 防别名重复二次插入。

站点码（tags 内缩写 / source 列全名一致）：sygic/klook/kkday/waug/mindtrip/
layla/culturetrip/watchmojo/tui/liontravel/his/jtb/itaka/tourtrans/yanolja/
wonderplan/xiaohongshu/tiktok/instagram/youtube。主站点优先级见
_SITE_PRIORITY（编辑榜/OTA 活动榜 > AI 行程 > 社媒）。

用法：
    python -m app.jobs.import_intl_platforms [--csv data/intl_platforms.csv]
        [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import uuid

from app.models import Poi
from app.services.poi_details import order_source_tags

logger = logging.getLogger(__name__)

#: 主站点优先级（编辑榜/OTA 活动榜 > AI 行程 > 社媒；同荐时 source/tags_source 取首选）
_SITE_PRIORITY = (
    "sygic",
    "klook",
    "kkday",
    "waug",
    "mindtrip",
    "layla",
    "culturetrip",
    "watchmojo",
    "tui",
    "liontravel",
    "his",
    "jtb",
    "itaka",
    "tourtrans",
    "yanolja",
    "wonderplan",
    "xiaohongshu",
    "tiktok",
    "instagram",
    "youtube",
)


def _primary_source(sites: list[str]) -> str:
    for s in _SITE_PRIORITY:
        if s in sites:
            return s
    return sites[0] if sites else "curated"


def _norm(s: str | None) -> str:
    return "".join((s or "").split()).lower()


def _contain(a: str, b: str) -> bool:
    """双向包含（短名≥2 字）：故宫⊂故宫博物院、天坛⊂天坛公园。"""
    a, b = a or "", b or ""
    if len(a) < 2 or len(b) < 2:
        return False
    return a in b or b in a


def _same_city(row_city: str | None, want: str) -> bool:
    rc = (row_city or "").strip()
    return bool(rc) and (want in rc or rc in want)


def _name_hit(row: Poi, names: set[str]) -> bool:
    """正名/别名等值，或同城双向包含（与转换器集内去重同口径）。"""
    cands = [row.name_zh, *(row.name_aliases or [])]
    want = {_norm(n) for n in names if n}
    for c in cands:
        cn = _norm(c)
        if not cn:
            continue
        if cn in want:
            return True
        for w in want:
            if _contain(cn, w):
                return True
    return False


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def apply_rows(session, picks: list[dict], *, dry_run: bool = False) -> dict:
    """对 picks（city/name_zh/name_en/sites/aliases）做幂等 merge/insert。"""
    rows = session.query(Poi).all()
    stats = {"insert": 0, "merge": 0, "skip": 0, "errors": 0}
    for p in picks:
        city = (p.get("city") or "").strip()
        name_zh = (p.get("name_zh") or "").strip()
        name_en = (p.get("name_en") or "").strip() or None
        sites = [s for s in (p.get("sites") or "").split(";") if s]
        aliases = [a for a in (p.get("aliases") or "").split(";") if a]
        if not name_zh or not sites:
            stats["skip"] += 1
            continue
        try:
            names = {name_zh, *aliases}
            hits = [r for r in rows if _same_city(r.city, city) and _name_hit(r, names)]
            add_tags = ["intl", *sites]
            primary = _primary_source(sites)
            if hits:
                changed = False
                for hit in hits:
                    merged = [t for t in add_tags if t not in (hit.tags or [])]
                    desired = order_source_tags([*(hit.tags or []), *merged])
                    if (
                        not merged
                        and hit.tags_source == primary
                        and desired == (hit.tags or [])
                    ):
                        continue
                    hit.tags = desired
                    hit.tags_source = primary
                    merged_aliases = [
                        a for a in aliases if a not in (hit.name_aliases or [])
                    ]
                    if merged_aliases:
                        hit.name_aliases = [*(hit.name_aliases or []), *merged_aliases]
                    changed = True
                    logger.info(
                        "intl-platform merge %s/%s onto source=%s tags+=%s",
                        city,
                        hit.name_zh,
                        hit.source,
                        merged,
                    )
                stats["merge" if changed else "skip"] += 1
            else:
                row = Poi(
                    id=uuid.uuid4(),
                    source=primary,
                    source_poi_id=f"{primary}:{city}:{name_zh}"[:100],
                    city=city,
                    name_zh=name_zh,
                    name_en=name_en,
                    category="attraction",
                    status="active",
                    tags=order_source_tags(add_tags),
                    tags_source=primary,
                    name_aliases=aliases or None,
                )
                session.add(row)
                rows.append(row)  # 同批去重
                stats["insert"] += 1
                logger.info("intl-platform insert %s/%s sites=%s", city, name_zh, sites)
        except Exception:
            stats["errors"] += 1
            logger.exception("intl-platform pick failed: %s/%s", city, name_zh)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="国际平台中国荐点导入（幂等）")
    parser.add_argument("--csv", default="data/intl_platforms.csv")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        picks = load_rows(args.csv)
    except FileNotFoundError:
        print(json.dumps({"error": f"csv not found: {args.csv}"}, ensure_ascii=True))
        return 1

    from app.db import get_session_factory

    with get_session_factory()() as session:
        stats = apply_rows(session, picks, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=True))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
