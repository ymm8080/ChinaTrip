"""一次性：省级 place 页收全下级目的地 slug，合并进 ctrip_city_slugs.json。

与 app/jobs/discover_ctrip_slugs.py（BFS+覆写）不同，本脚本：
- 先抓 beijing1 热榜拿全部省级 slug（id≥100000）；
- 逐省抓 place 页，提取全部下级目的地配对（id<100000，含县级市——
  五大连池/峨眉山/香格里拉这类在携程即独立目的地）；
- **合并**写入缓存：base ∪ new，绝不覆盖既有 187 城；
- 只收 DB 里 active 行出现过的城市名（wanted），礼貌 1.5s/页，~35 页。

用法：python ops/discover_ctrip_slugs_provinces.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session_factory  # noqa: E402

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_PAIR_RE = re.compile(
    r'/(?:place|sight)/([a-z]+\d+)\.html"[^>]*>([\u4e00-\u9fa5]{2,10})'
)
_CACHE = "../DESIGN/ctrip_city_slugs.json"
_ROOT = "https://you.ctrip.com/place/beijing1.html"


def _clean(label: str) -> str:
    return re.sub(r"(旅游攻略|攻略|旅游|景点)$", "", label)


# 国内省级行政区短名（beijing1 热榜配对剥后缀即这些），防海外目的地占预算
_CN_PROVINCES = {
    "北京",
    "上海",
    "天津",
    "重庆",
    "香港",
    "澳门",
    "台湾",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

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
    base: dict[str, str] = json.load(open(_CACHE, encoding="utf-8"))
    print(f"base={len(base)} wanted={len(wanted)}")

    found: dict[str, str] = {}
    provinces: dict[str, str] = {}
    with httpx.Client(headers=_UA, timeout=20, follow_redirects=True) as c:
        r = c.get(_ROOT)
        if r.status_code != 200:
            print(f"root fetch fail {r.status_code}")
            return 1
        for slug, label in _PAIR_RE.findall(r.text):
            if (
                re.sub(r"[a-z]+", "", slug).isdigit()
                and len(re.sub(r"[a-z]+", "", slug)) >= 6
            ):
                name = _clean(label)
                if name in _CN_PROVINCES:
                    provinces[name] = slug
        head = sorted(provinces.values())[:5]
        print(f"provinces found: {len(provinces)} -> {head}...")

        fetched = 0
        for pname, pslug in sorted(provinces.items()):
            if fetched >= 40:
                break
            try:
                r = c.get(f"https://you.ctrip.com/place/{pslug}.html")
            except Exception as e:
                print(f"  fetch fail {pslug}: {type(e).__name__}")
                continue
            fetched += 1
            if r.status_code != 200:
                continue
            new_hits = 0
            for slug, label in _PAIR_RE.findall(r.text):
                num = re.sub(r"[a-z]+", "", slug)
                # 省级 id 恒为 1000xx（100000-100099）；6-7 位其它数字是
                # 县级/海外目的地（阿尔山 aershan120084 属此列），照收
                if not num or num.startswith("1000"):
                    continue
                city = _clean(label)
                if city in wanted and city not in base and city not in found:
                    found[city] = slug
                    new_hits += 1
            print(f"  {pname}({pslug}): +{new_hits}")
            time.sleep(1.5)

    merged = {**base, **found}
    print(f"fetched={fetched} new={len(found)} total={len(merged)}")
    if not args.dry_run and found:
        with open(_CACHE, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
        print(f"merged -> {_CACHE}")
    elif args.dry_run:
        for k, v in sorted(found.items()):
            print(f"  dry {k} -> {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
