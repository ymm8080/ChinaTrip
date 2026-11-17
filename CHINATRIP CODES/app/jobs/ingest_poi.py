"""单点 POI 补建/补全（运维/数据修复入口）。

    python -m app.jobs.ingest_poi 朱家角古镇 --city 上海
    python -m app.jobs.ingest_poi 朱家角古镇 --city 上海 --no-access
    python -m app.jobs.ingest_poi 朱家角古镇 --city 上海 --no-create

走 ``app.services.poi_ingest.ensure_poi``：库里有骨架就只填空（坐标/地址/
类别/时长），库里没有就建行，距城心 ≥8km 的点顺带补 ``access_*``（城心 →
该点的公交最优方案，卡面「怎么去」用）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.services.poi_ingest import ensure_poi


def main() -> None:
    parser = argparse.ArgumentParser(description="单点 POI 补建/补全")
    parser.add_argument("name", help="地点名（如 朱家角古镇）")
    parser.add_argument("--city", default=None, help="城市（如 上海）")
    parser.add_argument("--no-create", action="store_true", help="库里没有也不建行")
    parser.add_argument("--no-access", action="store_true", help="不补到达方式")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(
        ensure_poi(
            args.name,
            args.city,
            create=not args.no_create,
            want_access=not args.no_access,
        )
    )
    if result is None:
        print(f"✗ {args.name}（{args.city or '?'}）库里没有、图商也没命中")
        return
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
