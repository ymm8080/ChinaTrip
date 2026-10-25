"""一次性：BFS 发现携程城市 slug，缓存到 DESIGN/ctrip_city_slugs.json。

原理：城市 place 页面包屑/热榜带 `/place/{slug}.html">城市名` 配对
（实测 changsha148 页 1963 对）。从 9 个种子城出发抓配对，剥
「旅游攻略」后缀、滤省级（slug id≥100000），命中 DB 城市名即收。
预算 120 页顺序抓取（礼貌 ~2s/页）。幂等：已覆盖的城不再需要。
"""

import json
import re
import sys
import time

import httpx

from app.db import get_session_factory

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_PAIR_RE = re.compile(
    r'/(?:place|sight)/([a-z]+\d+)\.html"[^>]*>([\u4e00-\u9fa5]{2,8})'
)
_CACHE = "../DESIGN/ctrip_city_slugs.json"
_MAX_FETCH = 120

# 与 ctrip_hours.CITY_SLUGS 一致的 9 城种子 + 已知补充
SEEDS = {
    "beijing1": "北京",
    "shanghai2": "上海",
    "hangzhou14": "杭州",
    "xian7": "西安",
    "chengdu104": "成都",
    "chongqing158": "重庆",
    "guangzhou152": "广州",
    "sanya61": "三亚",
    "guilin32": "桂林",
    "wuhan148": "武汉",
    "changsha148": "长沙",
}


def _clean(label: str) -> str:
    return re.sub(r"(旅游攻略|攻略|旅游|景点)$", "", label)


def main() -> int:
    with get_session_factory()() as s:
        from sqlalchemy import text

        wanted = {
            r[0]
            for r in s.execute(
                text(
                    "SELECT DISTINCT city FROM pois"
                    " WHERE status='active' AND city IS NOT NULL AND city != ''"
                )
            ).fetchall()
        }
    print(f"want {len(wanted)} cities")
    found: dict[str, str] = {}
    queue = list(SEEDS)
    seen_slugs = set(SEEDS)
    fetched = 0
    with httpx.Client(headers=_UA, timeout=20, follow_redirects=True) as c:
        while queue and fetched < _MAX_FETCH:
            slug = queue.pop(0)
            if (
                slug in seen_slugs
                and slug not in SEEDS
                and fetched > 0
                and slug in queue
            ):
                continue
            seen_slugs.add(slug)
            try:
                r = c.get(f"https://you.ctrip.com/place/{slug}.html")
            except Exception as e:
                print(f"  fetch fail {slug}: {type(e).__name__}")
                continue
            fetched += 1
            if r.status_code != 200:
                continue
            for s2, label in _PAIR_RE.findall(r.text):
                city = _clean(label)
                num = re.sub(r"[a-z]+", "", s2)
                if city in wanted and len(num) < 5 and city not in found:
                    found[city] = s2
                    print(f"  ✓ {city} -> {s2}")
                if s2 not in seen_slugs and len(num) < 5:
                    queue.append(s2)
                    seen_slugs.add(s2)
            time.sleep(1.5)
    with open(_CACHE, "w", encoding="utf-8") as fh:
        json.dump(found, fh, ensure_ascii=False, indent=1)
    print(f"fetched={fetched} found={len(found)} -> {_CACHE}")
    missing = sorted(wanted - set(found))
    print(f"missing {len(missing)}: {' '.join(missing[:20])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
