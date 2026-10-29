"""演艺演出种子导入（POIS DATASOURCE 04，show_booking_design P0，2026-10-27）。

数据源：DESIGN/POIS DATASOURCE/04_演艺演出_主要旅游城市.csv（50 行，
列 name_zh/province/city/show_type/venue/operator/season_note/ctrip_url/
source_url/remark）。show_booking_design §5 P0：04 入库（source=show）+
路径 A 预填（ctrip sight 页=booking_url，SKU 即订）。

行内动作（与 import_intl_platforms 同语义，但匹配收紧为**等值**）：
  库内同城市正名/别名等值行 → 追加 show tag、booking_url 只填空、
  别名并入，source 保留原值（enrich/tier/refresh 活链不断）；
  查无 → 插入 source=show 骨架行（category=entertainment，tags=[show]，
  best_visit_time=show（S5 晚间场演档），suggested_duration_min=80 场演
  基准，intro=season_note 只填空——S4 档期守护数据随行入库）。

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

from app.models import Poi
from app.services.poi_details import order_source_tags

logger = logging.getLogger(__name__)

#: 场演基准时长（分钟）：长恨歌 70 / 千古情 60-70，取 80 含入场余量
SHOW_DURATION_MIN = 80


def _norm(s: str | None) -> str:
    return "".join((s or "").split()).lower()


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
                    url_filled = None
                    if ctrip_url and not (hit.booking_url or "").strip():
                        hit.booking_url = ctrip_url
                        url_filled = ctrip_url
                    merged_aliases = [
                        a for a in aliases if a not in (hit.name_aliases or [])
                    ]
                    if merged_aliases:
                        hit.name_aliases = [*(hit.name_aliases or []), *merged_aliases]
                    if not merged and not url_filled and not merged_aliases:
                        continue
                    hit.tags = desired
                    hit.tags_source = "show"
                    changed = True
                    logger.info(
                        "show merge %s/%s onto source=%s tags+show url=%s",
                        city,
                        hit.name_zh,
                        hit.source,
                        "filled" if url_filled else "kept",
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
                        {"intro": season_note, "intro_source": "show"}
                        if season_note
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

    from app.db import get_session_factory

    with get_session_factory()() as session:
        stats = apply_rows(session, rows, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=True))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
