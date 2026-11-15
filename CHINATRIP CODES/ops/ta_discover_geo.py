r"""城市 gID 滚雪球发现（0 配额，2026-11-14）。

原理：已验证城市的 Tourism 页互链其它中国城市 → 拿到候选 gID →
抓候选页标题验证城市名（CITY_TITLE_RE 兼容"旅游景点攻略/旅游攻略/
旅游住宿"等后缀）→ 逐城**即时**写缓存（防超时丢进度）。

覆盖目标：ranked CSV 里 ≥3 行 POI 的城市（规划页数据源），减去已缓存。

用法：
    python ops/ta_discover_geo.py [--max-cities 40] [--delay 0.8]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

_OPS = Path(__file__).resolve().parent
_GEO_CACHE = _OPS / "ta_city_geo.json"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CITY_TITLE_RE = re.compile(r"2026年\d+月(.+?)(?:旅游景点攻略|旅游攻略|景点攻略|旅游住宿|景点大全|美食攻略)")
_LINK_RE = re.compile(r"Tourism-g(\d{5,8})-([A-Za-z0-9_%-]+?)-Vacations\.html")

# 规划页城市清单（与 index.html PLAN_CITIES / 后端 KNOWN_CITIES 同步）
PLAN_CITIES = [
    "北京", "上海", "杭州", "苏州", "南京", "西安", "成都", "重庆", "广州",
    "深圳", "天津", "武汉", "长沙", "厦门", "青岛", "大连", "三亚", "丽江",
    "桂林", "洛阳", "敦煌", "兰州", "拉萨", "昆明", "大理", "张家界", "黄山",
    "无锡", "绍兴", "嘉兴", "舟山", "哈尔滨", "沈阳", "长春", "郑州", "济南",
    "福州", "泉州", "威海", "珠海",
]


def title_city(title: str) -> str:
    m = CITY_TITLE_RE.match(title or "")
    return m.group(1) if m else ""


def load_targets(cache: dict) -> list[str]:
    """规划页城市 - 已缓存 gID 的城市。"""
    return [c for c in PLAN_CITIES if c not in cache]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()

    cache = json.load(_GEO_CACHE.open(encoding="utf-8"))
    targets = load_targets(cache)
    print(f"待发现城市 {len(targets)}:", targets[:12], "…")

    client = httpx.Client(headers=_UA, follow_redirects=True, timeout=20.0)

    def verify(g: str, slug: str) -> str:
        """gID+slug → 页面自报的城市名（失败空串）。"""
        url = f"https://www.tripadvisor.cn/Tourism-g{g}-{slug}-Vacations.html"
        for _ in range(2):
            try:
                r = client.get(url)
                return title_city(re.search(r"<title>([^<]*)</title>", r.text).group(1))
            except Exception:
                time.sleep(1.5)
        return ""

    discovered = 0
    # 种子：已缓存城市，每轮从它们的页面上 harvesting 互链
    seeds = list(cache.items())
    pending = set(targets)
    for round_no in range(3):
        if not pending:
            break
        progressed = False
        for seed_city, gid in list(seeds):
            if not pending:
                break
            try:
                r = client.get(
                    f"https://www.tripadvisor.cn/Tourism-g{gid}-{seed_city}-Vacations.html"
                )
            except Exception:
                time.sleep(2)
                continue
            links = _LINK_RE.findall(r.text)
            for cg, slug in links[:40]:
                slug = unquote(slug)
                if cg in {v for v in cache.values()}:
                    continue
                cname = verify(cg, slug)
                if cname and cname in pending:
                    cache[cname] = cg
                    pending.discard(cname)
                    discovered += 1
                    progressed = True
                    print(f"  [OK] {cname} = g{cg}")
                    # 新验证城市立即成为下一轮种子
                    json.dump(cache, _GEO_CACHE.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
                time.sleep(args.delay)
            time.sleep(args.delay)
        seeds = [(c, g) for c, g in cache.items()]
        if not progressed:
            print("  [info] 本轮无进展，停止")
            break

    client.close()
    json.dump(cache, _GEO_CACHE.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n本轮新发现 {discovered} 城 | 缓存总数 {len(cache)} | 仍缺 {len(pending)}")


if __name__ == "__main__":
    main()
