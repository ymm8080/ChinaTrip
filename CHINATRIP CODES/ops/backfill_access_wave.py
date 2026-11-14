"""远郊 POI 到达方式回填的批量驱动（按城市顺序，供后台跑）。

为什么不用 .ps1 里写中文城市名：PowerShell 5.1 读无 BOM 的 .ps1 时按 ANSI
解码，中文字面量变乱码 → `--city` 匹配不到任何行（实测 9 城全 0 候选）。
本文件是 UTF-8 源码，Python 直接读，零编码风险。

用法：python ops/backfill_access_wave.py [--limit 300] [--concurrency 4]
只填空，可反复重跑（已填行跳过）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jobs.backfill_poi_access import run  # noqa: E402

CITIES = ("北京", "上海", "杭州", "成都", "苏州", "重庆", "深圳", "广州", "南京")


def main() -> None:
    parser = argparse.ArgumentParser(description="九城远郊 POI 到达方式批量回填")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--cities", nargs="*", default=list(CITIES))
    args = parser.parse_args()
    for city in args.cities:
        print(f"=== {city} ===", flush=True)
        asyncio.run(
            run(
                city=city,
                limit=args.limit,
                concurrency=args.concurrency,
                sleep=args.sleep,
            )
        )
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
