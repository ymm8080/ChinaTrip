"""营业时间/评分四通道活性探针（ops）：一条命令查清今日可填通道。

通道：ctrip（gs html5 目录）、amap（v5 place/text business 块）、
baidu（place v2 scope=2）、overpass（OSM opening_hours）。
每通道单发一枪探测，结果落盘 ops/hours_channel_status.json（带时间戳），
调度器/会话可先读文件避免重复烧探测配额。

用法：python ops/check_hours_channels.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_STATUS = Path(__file__).resolve().parent / "hours_channel_status.json"


def _probe_ctrip() -> str:
    import re

    import httpx

    r = httpx.get(
        "https://gs.ctrip.com/html5/you/sight/hangzhou14.html?pageIndex=1",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        timeout=12,
        follow_redirects=True,
    )
    names = re.findall(
        r"/sight/hangzhou14/\d+\.html[^>]*?title=\"([^\"]{2,20})\"", r.text
    )
    return "alive" if names else "down（目录页变质，slug 闸收口）"


def _probe_amap() -> str:
    import asyncio

    from app.config import get_settings
    from app.services.amap_client import (
        AmapClient,
        AmapPunishedError,
        AmapQuotaExhaustedError,
    )

    async def go() -> str:
        s = get_settings()
        c = AmapClient(key=s.amap_api_key, timeout_seconds=8.0)
        try:
            out = await c.search_hours("西湖风景名胜区", city="杭州")
            return "alive" if out.get("matched") else "alive-but-no-data"
        except AmapPunishedError:
            return "waf-cooling"
        except AmapQuotaExhaustedError:
            return "quota"
        except Exception as e:  # noqa: BLE001 — 探针只报状态
            return f"error:{type(e).__name__}"

    return asyncio.run(go())


def _probe_baidu() -> str:
    import httpx

    from app.jobs.enrich_baidu_map import _key_from_env, _search

    key = _key_from_env()
    if not key:
        return "no-key"
    try:
        with httpx.Client(
            headers={"User-Agent": "chinatrip-enrich/0.1"}, timeout=15
        ) as client:
            _search(client, key, "西湖风景名胜区", "杭州")
        return "alive"
    except Exception as e:  # noqa: BLE001
        st = getattr(e, "status", None)
        if st in (401, 402, 302):
            return f"quota:{st}"
        return f"error:{type(e).__name__}"


def _probe_overpass() -> str:
    import httpx

    q = (
        '[out:json][timeout:20];node(30.20,120.05,30.30,120.20)'
        '["tourism"="attraction"]["opening_hours"];out 1;'
    )
    for ep in ("https://overpass-api.de/api/interpreter",):
        try:
            r = httpx.post(ep, data={"data": q}, timeout=30)
            r.json()
            return "alive"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}"
    return f"unreachable:{last}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="忽略缓存强探")
    args = parser.parse_args()
    if not args.refresh and _STATUS.exists():
        cached = json.loads(_STATUS.read_text(encoding="utf-8"))
        age_h = (time.time() - cached.get("ts", 0)) / 3600
        if age_h < 1:
            print(json.dumps(cached["channels"], ensure_ascii=False))
            return 0
    channels = {
        "ctrip": _probe_ctrip(),
        "amap": _probe_amap(),
        "baidu": _probe_baidu(),
        "overpass": _probe_overpass(),
    }
    _STATUS.write_text(
        json.dumps(
            {"ts": time.time(), "at": datetime.now().isoformat(), "channels": channels},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps(channels, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
