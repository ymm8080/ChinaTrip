r"""批量城市 gID 发现（Terra /locations/search，每城 1 次调用）。

对排名文件里缺 gID 的城市：query="{city_en} China" 搜一次，取首个结果的
geo_id（Terra 权威），再用猫途鹰 CN 标题免费复核城市名。逐城即时写缓存。

用法：
    python ops/ta_discover_geo_api.py [--delay 1.0]
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

_OPS = Path(__file__).resolve().parent
_GEO_CACHE = _OPS / "ta_city_geo.json"
_RANKED_CSV = Path(
    r"D:/CHINATRIP/DESIGN/POIS DATASOURCE/chinatrip_active_ranked_pois_2026-11-14.csv"
)
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CITY_TITLE_RE = re.compile(r"2026年\d+月(.+?)(?:旅游景点攻略|旅游攻略|景点攻略|旅游住宿|景点大全|美食攻略)")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    cache = json.load(_GEO_CACHE.open(encoding="utf-8"))
    # 缺 gID 的城市（全部 CSV 城市，不分规划页内外）
    cities: dict[str, str] = {}
    with _RANKED_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            city = (row.get("city") or "").strip()
            if city and city not in cache:
                cities.setdefault(city, (row.get("city_en") or "").strip())
    print(f"缺 gID 城市: {len(cities)}")

    api_key = get_settings().ta_api_key if hasattr(get_settings(), "ta_api_key") else None
    # API key 从环境/配置取，回退已知值来源（Windows 用户环境变量）
    import os

    api_key = api_key or os.environ.get("TRIPADVISOR_API_KEY") or ""
    if not api_key:
        print("未找到 TRIPADVISOR_API_KEY")
        return

    client = httpx.Client(headers=_UA, follow_redirects=True, timeout=25.0)
    ok = 0
    for i, (city, city_en) in enumerate(cities.items()):
        q = f"{city_en} China" if city_en else f"{city} China"
        try:
            r = client.get(
                "https://terra.tripadvisor.com/api/locations/search",
                params={"query": q, "size": 3},
                headers={"X-API-Key": api_key},
            )
            data = r.json().get("data", [])
            gid = data[0].get("location", {}).get("geo_id") if data else None
        except Exception as e:
            print("ERR", city, str(e)[:50])
            gid = None
        if gid:
            try:
                vr = client.get(
                    f"https://www.tripadvisor.cn/Tourism-g{gid}-{quote(city_en or city)}-Vacations.html"
                )
                m = re.search(r"<title>([^<]*)</title>", vr.text)
                cname = ""
                mm = CITY_TITLE_RE.match(m.group(1) if m else "")
                if mm:
                    cname = mm.group(1)
                if cname == city:
                    cache[city] = str(gid)
                    ok += 1
                    print(f"  [OK] {city} = g{gid}")
                else:
                    print(f"  [??] {city} = g{gid} | 标题城市: {cname or (m.group(1) if m else '')[:30]}")
                    # geo 名对但标题模式不符时也接受（小城标题格式多变）
                    if cname == "" and m and city in (m.group(1) or ""):
                        cache[city] = str(gid)
                        ok += 1
                        print(f"       [OK-弱] {city} 标题含城市名，接受")
            except Exception as e:
                print("VERR", city, str(e)[:50])
        else:
            print(f"  [??] {city} 搜索无 geo")
        # 即时落盘
        json.dump(cache, _GEO_CACHE.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(args.delay)

    client.close()
    print(f"\n解决 {ok}/{len(cities)} 城")


if __name__ == "__main__":
    main()
