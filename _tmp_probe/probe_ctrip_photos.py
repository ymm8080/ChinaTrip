# -*- coding: utf-8 -*-
"""探针：携程 sight 详情页 HTML 是否携带可用图 URL（任务3 扩展，2026-11-12）。

背景：ctrip_hours 链已在产（hours/ticket/tags 回源），若同一 detail HTML
本就含图 URL，等于零新增接口白捡一个图源。只读 import ctrip_hours 的
_URL/_UA/正则；不改任何文件；无 key；串行 ≤7 次 GET（2 目录 + 4 详情
+ 1 美食试探），远低于 reader 硬顶。

输出：每页图 URL 计数（按域名分组）、gallery 结构标记、样例（截断）。
"""
from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from urllib.parse import urlsplit

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")

import httpx  # noqa: E402

from app.services.ctrip_hours import (  # noqa: E402  只读复用
    _DETAIL_URL_RE,
    _LIST_ENTRY_RES,
    _LIST_URL,
    _UA,
    CITY_SLUGS,
)

TIMEOUT = 15.0
IMG_RE = re.compile(r"https?://[^\s\"'<>\\]+\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)
GALLERY_MARKERS = (
    "__INITIAL_STATE__", "photoList", "imageList", "galleryList",
    "sightImage", "resourceJson", "window.SIGHT", "coverImage",
)
CDN_HINT = re.compile(r"c-ctrip\.com|ctrip\.com|tripcdn", re.IGNORECASE)


def trunc(u: str, n: int = 90) -> str:
    try:
        p = urlsplit(u)
        core = p.netloc + p.path
    except ValueError:
        core = u
    q = ("?" + p.query[:40] + "…") if p.query else ""
    return core[:n] + q


def scan_html(label: str, html: str) -> None:
    print(f"\n===== {label} =====")
    print(f"html bytes: {len(html)}")
    imgs = IMG_RE.findall(html)
    domains = Counter(urlsplit(u).netloc for u in imgs)
    ctrip_imgs = [u for u in imgs if CDN_HINT.search(u)]
    print(f"img urls total: {len(imgs)}  (ctrip-cdn: {len(ctrip_imgs)})")
    for d, c in domains.most_common(6):
        print(f"  {d}: {c}")
    hits = [m for m in GALLERY_MARKERS if m in html]
    print(f"gallery markers: {hits or 'none'}")
    seen: set[str] = set()
    for u in imgs:
        key = urlsplit(u).netloc
        if key in seen:
            continue
        seen.add(key)
        print(f"  sample[{key}]: {trunc(u)}")
        if len(seen) >= 4:
            break


async def detail_urls_for(client: httpx.AsyncClient, slug: str, want: int = 2):
    r = await client.get(_LIST_URL.format(slug=slug, page=1))
    if r.status_code != 200:
        print(f"[{slug}] directory HTTP {r.status_code}")
        return []
    urls: list[str] = []
    for rex in _LIST_ENTRY_RES:
        for m in rex.finditer(r.text):
            u, name = m.group(1).strip(), m.group(2).strip()
            if not _DETAIL_URL_RE.search(u):
                continue
            if u.startswith("/"):
                u = "https://gs.ctrip.com" + u
            if u not in urls:
                urls.append(u)
            print(f"[{slug}] entry: {name} -> {trunc(u, 60)}")
            if len(urls) >= want:
                return urls
    return urls


async def main() -> int:
    async with httpx.AsyncClient(
        headers=_UA, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        # 真身页捕获：产线能间歇命中 SSR 真页，同一真实 slug 详情页重抓 2 次
        for name, u in (
            ("深圳世界之窗", "https://gs.ctrip.com/html5/you/sight/Shenzhen26/2778.html"),
            ("深圳欢乐谷", "https://gs.ctrip.com/html5/you/sight/Shenzhen26/13720.html"),
        ):
            try:
                r = await client.get(u)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                print(f"[{name}] fetch failed: {type(exc).__name__}")
                continue
            if r.status_code == 200:
                scan_html(f"REAL-HUNT {name}", r.text)
            else:
                print(f"[{name}] HTTP {r.status_code}")
            await asyncio.sleep(3)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
