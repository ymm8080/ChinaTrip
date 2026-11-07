"""演艺演出种子导入（POIS DATASOURCE 04，show_booking_design P0，2026-10-27）。

数据源：DESIGN/POIS DATASOURCE/04_演艺演出_主要旅游城市.csv（50 行，
列 name_zh/province/city/show_type/venue/operator/season_note/ctrip_url/
source_url/remark/session_time）。show_booking_design §5 P0：04 入库
（source=show）+ 路径 A 预填（ctrip sight 页=booking_url，SKU 即订）。

场次与内容（2026-11-07 扩列）：session_time（人工核好的场次时刻，如
「仅夜场（约20:10/21:35两场…）」）→ opening_hours + hours_source='show'
+ hours_updated_at 盖戳——S5 晚档分桶（_show_night_only）读的就是这列，
10-31 批次已手工回填 45 行但从未过 import 链、无权威戳（refresh 链
每 30 天一轮会拿图商「开放时间」覆掉场次，护闸见 refresh_pois）。
show_type/venue（山水实景演出；华清宫·九龙湖）拼进 intro——内容与
当地特色随行可见。

行内动作（与 import_intl_platforms 同语义，但匹配收紧为**等值**）：
  库内同城市正名/别名等值行 → 追加 show tag、booking_url 只填空、
  别名并入，source 保留原值（enrich/tier/refresh 活链不断）；
  tags_source 带权威闸（2026-11-03 铁律「导入不降权威」：show 权威 2
  挡不住 mct/mohurd 3，低于既有归因时保留旧 tags_source）；
  source=show 本命行：opening_hours←session_time（同源刷新）+
  hours_source='show' 权威戳 + hours_updated_at 冷却戳；他源行 hours
  只填空（图商场馆开放时间不覆盖，除非本来为 NULL）；
  intro←「show_type；venue；season_note」只填空 / intro_source='show'
  时升级；
  查无 → 插入 source=show 骨架行（category=entertainment，tags=[show]，
  best_visit_time=show（S5 晚间场演档），suggested_duration_min=80 场演
  基准，opening_hours/intro 随行入库）。

匹配不走双向包含（与 intl 荐点不同）：演出与所在景区是两个实体
（「西安千古情」≠「西安千古情景区」），包含匹配会把景区行误标成
晚间演出档，故只认正名/别名等值。《》括名剥饰后的裸名作为别名
等值可命中（「长恨歌」≈「《长恨歌》演出」）。

用法：
    python -m app.jobs.import_shows [--csv <path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

from app.models import Poi
from app.services.source_tier import order_source_tags, tags_source_wins

logger = logging.getLogger(__name__)

#: 场演基准时长（分钟）：长恨歌 70 / 千古情 60-70，取 80 含入场余量
SHOW_DURATION_MIN = 80


def _norm(s: str | None) -> str:
    return "".join((s or "").split()).lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def compose_intro(show_type: str | None, venue: str | None, season_note: str | None):
    """「山水实景演出；华清宫·九龙湖；演出季约4–10月」——内容+场地+档期。"""
    parts = [p.strip() for p in (show_type, venue, season_note) if p and p.strip()]
    return "；".join(parts) or None


def bare_name(name: str) -> str | None:
    """《长恨歌》演出 → 长恨歌（先剥「演出/秀」尾缀，再剥书名号）。"""
    n = (name or "").strip()
    for suffix in ("演出", "秀"):
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)]
            break
    while n and (n[0] in "《〈「" or n[-1] in "》〉」"):
        if n[0] in "《〈「":
            n = n[1:]
        if n and n[-1] in "》〉」":
            n = n[:-1]
    n = n.strip()
    return n or None


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("name_zh") or "").strip()]


def apply_rows(session, rows: list[dict], *, dry_run: bool = False) -> dict:
    """对 CSV 行做幂等 merge/insert（等值匹配，无包含）。"""
    pois = session.query(Poi).all()
    stats = {"insert": 0, "merge": 0, "skip": 0, "errors": 0}
    for r in rows:
        name = (r.get("name_zh") or "").strip()
        city = (r.get("city") or "").strip()
        ctrip_url = (r.get("ctrip_url") or "").strip() or None
        season_note = (r.get("season_note") or "").strip() or None
        session_time = (r.get("session_time") or "").strip() or None
        show_type = (r.get("show_type") or "").strip() or None
        venue = (r.get("venue") or "").strip() or None
        intro_val = compose_intro(show_type, venue, season_note)
        if not name or not city:
            stats["skip"] += 1
            continue
        alias = bare_name(name)
        aliases = [alias] if alias and alias != name else []
        try:
            names = {_norm(n) for n in [name, *aliases] if n}
            hits = [
                p
                for p in pois
                if (p.city or "").strip() == city
                and any(
                    _norm(c) in names for c in [p.name_zh, *(p.name_aliases or [])] if c
                )
            ]
            if hits:
                changed = False
                for hit in hits:
                    merged = [t for t in ("show",) if t not in (hit.tags or [])]
                    desired = order_source_tags([*(hit.tags or []), *merged])
                    # 归因权威闸（2026-11-03 铁律「导入不降权威」）：show 权威
                    # 2 挡不住 mct/mohurd 3——权威低于既有时 tags_source 保留
                    # 原值，tags 并集照写。
                    source_wins = tags_source_wins("show", hit.tags_source)
                    url_filled = None
                    if ctrip_url and not (hit.booking_url or "").strip():
                        hit.booking_url = ctrip_url
                        url_filled = ctrip_url
                    merged_aliases = [
                        a for a in aliases if a not in (hit.name_aliases or [])
                    ]
                    if merged_aliases:
                        hit.name_aliases = [*(hit.name_aliases or []), *merged_aliases]
                    # 场次（2026-11-07）：本命行（source=show）opening_hours
                    # 承载人工核好的场次时刻，同源刷新 + 权威戳/冷却戳；他源
                    # 行只填空——图商场馆「开放时间」描述的是场馆不是场次。
                    hours_written = False
                    if session_time:
                        hours_now = (hit.opening_hours or "").strip()
                        if (hit.source or "").strip() == "show":
                            if hours_now != session_time:
                                hit.opening_hours = session_time
                                hours_written = True
                            if (hit.hours_source or "").strip() != "show":
                                hit.hours_source = "show"
                                hours_written = True
                            if hours_written or hit.hours_updated_at is None:
                                hit.hours_updated_at = _now()
                        elif not hours_now:
                            hit.opening_hours = session_time
                            hit.hours_source = "show"
                            hit.hours_updated_at = _now()
                            hours_written = True
                    # intro（内容+场地+档期）：只填空；intro_source='show' 同源升级
                    intro_written = False
                    if intro_val:
                        intro_now = (hit.intro or "").strip()
                        if not intro_now or (hit.intro_source or "").strip() == "show":
                            if intro_now != intro_val:
                                hit.intro = intro_val
                                hit.intro_source = "show"
                                intro_written = True
                    if (
                        not merged
                        and not url_filled
                        and not merged_aliases
                        and not hours_written
                        and not intro_written
                        and (hit.tags_source == "show" or not source_wins)
                    ):
                        continue
                    hit.tags = desired
                    if source_wins:
                        hit.tags_source = "show"
                    changed = True
                    logger.info(
                        "show merge %s/%s onto source=%s tags+show url=%s"
                        " hours=%s intro=%s",
                        city,
                        hit.name_zh,
                        hit.source,
                        "filled" if url_filled else "kept",
                        "written" if hours_written else "kept",
                        "written" if intro_written else "kept",
                    )
                stats["merge" if changed else "skip"] += 1
            else:
                row = Poi(
                    id=uuid.uuid4(),
                    source="show",
                    source_poi_id=f"show:{city}:{name}"[:100],
                    city=city,
                    name_zh=name,
                    category="entertainment",
                    status="active",
                    tags=order_source_tags(["show"]),
                    tags_source="show",
                    name_aliases=aliases or None,
                    booking_url=ctrip_url,
                    best_visit_time="show",
                    best_visit_time_source="show",
                    suggested_duration_min=SHOW_DURATION_MIN,
                    duration_source="show",
                    **(
                        {
                            "opening_hours": session_time,
                            "hours_source": "show",
                            "hours_updated_at": _now(),
                        }
                        if session_time
                        else {}
                    ),
                    **(
                        {"intro": intro_val, "intro_source": "show"}
                        if intro_val
                        else {}
                    ),
                )
                session.add(row)
                pois.append(row)  # 同批幂等（重跑不二插）
                stats["insert"] += 1
                logger.info("show insert %s/%s url=%s", city, name, ctrip_url)
        except Exception:
            stats["errors"] += 1
            logger.exception("show row failed: %s/%s", city, name)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="演艺演出种子导入（幂等）")
    parser.add_argument(
        "--csv",
        default="../DESIGN/POIS DATASOURCE/04_演艺演出_主要旅游城市.csv",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        rows = load_rows(args.csv)
    except FileNotFoundError:
        print(json.dumps({"error": f"csv not found: {args.csv}"}, ensure_ascii=True))
        return 1
    # §4 产品过滤（2026-11-03 拍板：红色题材演艺不入——红秀/西安事变影画出池）
    import os

    from app.services.product_filter import apply_product_filter, write_excluded_csv

    rows, excluded = apply_product_filter(rows)
    if excluded:
        write_excluded_csv(
            os.path.splitext(args.csv)[0] + "_excluded.csv",
            excluded,
            fields=("city", "name_zh", "exclusion_reason"),
        )

    from app.db import get_session_factory

    with get_session_factory()() as session:
        stats = apply_rows(session, rows, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=True))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
