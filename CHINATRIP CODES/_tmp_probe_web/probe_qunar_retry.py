# -*- coding: utf-8 -*-
"""Qunar 软反爬复查：空响应体时试 touch 端点/手机 UA/看响应头。

预算：沿用每景点 ≤3 次请求（search 已耗 1，本脚本每景点再耗 ≤2）。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).parent / "raw"
RAW_DIR.mkdir(exist_ok=True)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def show(tag: str, resp: httpx.Response) -> str:
    print(f"\n[{tag}] HTTP {resp.status_code} len={len(resp.text)}")
    for h in ("server", "content-type", "set-cookie", "location", "x-powered-by"):
        v = resp.headers.get(h)
        if v:
            print(f"  {h}: {str(v)[:90]}")
    body = resp.text
    if body:
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S)
        print("  title:", (m.group(1).strip()[:70] if m else "(no title)"))
        print("  head400:", body[:400].replace("\n", " ")[:400])
    return body


def probe(keyword: str) -> None:
    kw_enc = httpx.QueryParams({"k": keyword}).get("k")
    # touch 端点 + 手机 UA
    with httpx.Client() as client:
        time.sleep(1.2)
        url = f"https://piao.qunar.com/touch/list.htm?keyword={kw_enc}"
        try:
            resp = client.get(
                url,
                headers={**BASE_HEADERS, "User-Agent": MOBILE_UA,
                         "Referer": "https://piao.qunar.com/touch/"},
                timeout=10.0,
                follow_redirects=True,
            )
        except Exception as exc:
            print(f"touch/list mobile-UA failed: {type(exc).__name__}: {exc}")
            return
        html = show("touch/list mobile-UA", resp)
        (RAW_DIR / "qunar_touch_list.html").write_text(html, "utf-8")
        ids = re.findall(r'detail(?:/\w+)?\.htm\?id=(\w+)', html)
        print("  detail ids:", list(dict.fromkeys(ids))[:6])

        # 第二次：travel.qunar.com 桌面 UA（景点库落地页形状）
        time.sleep(1.5)
        url2 = f"https://travel.qunar.com/search/q-{kw_enc}"
        try:
            resp2 = client.get(
                url2,
                headers={**BASE_HEADERS, "User-Agent": DESKTOP_UA,
                         "Referer": "https://travel.qunar.com/"},
                timeout=10.0,
                follow_redirects=True,
            )
        except Exception as exc:
            print(f"travel search failed: {type(exc).__name__}: {exc}")
            return
        html2 = show("travel.qunar.com search", resp2)
        (RAW_DIR / "qunar_travel_search.html").write_text(html2, "utf-8")
        poi_ids = re.findall(r'/p-oi(\d+)-', html2)
        print("  travel poi ids:", list(dict.fromkeys(poi_ids))[:6])


if __name__ == "__main__":
    probe("兵马俑")
