"""火车班次日缓存刷新作业（CLI 入口，供计划任务/手动调用）。

用法：
    python -m app.jobs.refresh_trains
    python -m app.jobs.refresh_trains --pairs 北京,上海;上海,杭州
    python -m app.jobs.refresh_trains --date 2026-10-21
"""

import argparse
import json
import sys

from app.config import get_settings
from app.services.train_cache import refresh_train_cache


def _parse_pairs(raw: str) -> list[tuple[str, str]]:
    """--pairs 北京,上海;上海,杭州 -> [("北京","上海"), ("上海","杭州")]。"""
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(";"):
        cities = [city.strip() for city in chunk.split(",")]
        if len(cities) != 2 or not all(cities):
            raise SystemExit(f"--pairs 片段格式错误（应为 城市,城市）: {chunk!r}")
        pairs.append((cities[0], cities[1]))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="刷新火车班次日缓存（拉取 -> 落库 train_schedule_cache）"
    )
    parser.add_argument(
        "--pairs",
        help="分号分隔 pair、逗号分隔城市（如 北京,上海;上海,杭州）；"
        "缺省=库内已有 pair ∪ mock 核心 8 对",
    )
    parser.add_argument("--date", help="查询日期 YYYY-MM-DD；缺省=今日+3")
    args = parser.parse_args(argv)

    pairs = _parse_pairs(args.pairs) if args.pairs else None
    result = refresh_train_cache(get_settings(), pairs=pairs, date=args.date)
    # ensure_ascii=True：GBK 控制台下中文转义输出，不炸编码。
    print(json.dumps(result, ensure_ascii=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
