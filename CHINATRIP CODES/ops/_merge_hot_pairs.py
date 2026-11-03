"""临时：把热榜 4001 配对里命中 wanted 的目的地 slug 合并进 slug 缓存。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.db import get_session_factory

PAIRS = "../DESIGN/POIS DATASOURCE/_src/ctrip_hot_pairs.json"
CACHE = "../DESIGN/ctrip_city_slugs.json"


def main() -> None:
    with get_session_factory()() as s:
        wanted = {
            r[0]
            for r in s.execute(
                text(
                    "SELECT DISTINCT city FROM pois"
                    " WHERE status='active' AND city IS NOT NULL AND city != ''"
                )
            ).fetchall()
        }
    pairs = json.load(open(PAIRS, encoding="utf-8"))
    cache = json.load(open(CACHE, encoding="utf-8"))
    clean = lambda s: re.sub(r"(旅游攻略|攻略|旅游|景点|地区|盟|自治州)$", "", s)  # noqa: E731
    add: dict[str, str] = {}
    for slug, label in pairs:
        num = re.sub(r"[a-z]+", "", slug)
        if not num or num.startswith("1000"):
            continue
        for name in (label, clean(label)):
            if name in wanted and name not in cache and name not in add:
                add[name] = slug
                break
    merged = {**cache, **add}
    json.dump(merged, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("added:", len(add), "total:", len(merged))
    for k in ("兴安", "周口", "大兴安岭", "漠河", "五大连池", "峨眉山"):
        print(" ", k, "->", merged.get(k))


if __name__ == "__main__":
    main()
