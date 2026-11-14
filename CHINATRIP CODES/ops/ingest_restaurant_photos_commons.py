# -*- coding: utf-8 -*-
"""restaurants 照片免费确定性回填（Commons 站内搜 + 官网 og:image）。

2026-11-12 用户指示「另一个 agent 看餐厅」——本脚本即该工作：串行、
礼貌 0.5s 间隔、只填空、尝试即落戳，不烧图商配额、无验证码。
复用 app.services.poi_photos 的唯一实现（合规 UA/防错图闸/收口），
import 不抄。

用法（CHINATRIP CODES 目录下）：
    python ops/ingest_restaurant_photos_commons.py [--limit 150] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ops/ → 仓库根

from sqlalchemy import or_  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.models import Restaurant  # noqa: E402
from app.services.poi_photos import (  # noqa: E402
    _commons_search_sync,
    _official_og_sync,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("ingest_restaurant_photos")

_REQUEST_GAP_SECONDS = 0.5


def select_rows(session_factory, *, limit: int) -> list[Restaurant]:
    deadline = datetime.now() - timedelta(hours=24)
    with session_factory() as session:
        return (
            session.query(Restaurant)
            .filter(
                Restaurant.status == "active",
                Restaurant.photos.is_(None),
                Restaurant.name_zh.isnot(None),
                or_(
                    Restaurant.photos_fetched_at.is_(None),
                    Restaurant.photos_fetched_at < deadline,
                ),
            )
            .order_by(
                # 名店优先：米其林 tags_source > 黑珍珠 > curated 源 > 其余
                Restaurant.tags_source.is_(None),
                Restaurant.rating.desc().nullslast(),
                Restaurant.id,
            )
            .limit(limit)
            .all()
        )


def fill_one(restaurant: Restaurant, stats: dict) -> None:
    """单行回填：Commons → og:image → 全空落戳。异常记 warning 不炸。"""
    name = (restaurant.name_zh or "").strip()
    photos = None
    source = None
    try:
        photos = _commons_search_sync(name)
        if photos:
            source = "wikimedia"
    except Exception:
        logger.warning("commons failed: %s", name, exc_info=True)
    if not photos and restaurant.website:
        try:
            photos = _official_og_sync(restaurant.website)
            if photos:
                source = "official"
        except Exception:
            logger.warning("og failed: %s", name, exc_info=True)
    restaurant.photos_fetched_at = datetime.now()  # 尝试即落戳
    if photos:
        restaurant.photos = photos
        restaurant.photos_source = source
        stats["hits_" + (source or "?")] = stats.get("hits_" + (source or "?"), 0) + 1
    else:
        stats["no_data"] += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="restaurants photos free ingest")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    rows = select_rows(factory, limit=args.limit)
    stats: dict = {
        "targets": len(rows),
        "hits_wikimedia": 0,
        "hits_official": 0,
        "no_data": 0,
        "errors": 0,
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=False))
        return 0
    for row in rows:
        try:
            fill_one(row, stats)
            with factory() as session:
                merged = session.merge(row)
                session.commit()
                del merged
        except Exception:
            stats["errors"] += 1
            logger.warning("row failed: %s", row.name_zh, exc_info=True)
        time.sleep(_REQUEST_GAP_SECONDS)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
