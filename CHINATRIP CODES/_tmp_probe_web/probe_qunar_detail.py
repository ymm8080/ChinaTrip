# -*- coding: utf-8 -*-
"""Qunar touch 详情页探针（手机 UA）：抓兵马俑详情 + 西湖列表/详情。

预算：兵马俑已耗 2（desktop list 空 + touch list），本脚本抓详情=第 3；
西湖走 touch list + touch detail 共 2。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).parent / "raw"
RAW_DIR.mkdir(exist_ok=True)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
BASE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://touch.piao.qunar.com/touch/",
}


def fetch(client: httpx.Client, url: str) -> httpx.Response:
    print(f"[req] GET {url[:100]}")
    resp = client.get(url, headers=BASE_HEADERS, timeout=10.0, follow_redirects=True)
    print(f"  -> HTTP {resp.status_code} len={len(resp.text)} final={str(resp.url)[:80]}")
    return resp


def touch_list(keyword: str) -> str:
    enc = httpx.QueryParams({"k": keyword}).get("k")
    resp = fetch(client, f"https://piao.qunar.com/touch/list.htm?keyword={enc}")
    return resp.text


def pick_detail_url(html: str, keyword: str) -> str | None:
    """列表页里挑名称含关键词的第一条详情链接（_name_like 口径：双向包含）。"""
    # 形状1: //touch.piao.qunar.com/touch/detail_{id}.html?...
    links = re.findall(
        r'href="(//touch\.piao\.qunar\.com/touch/detail_(\w+)\.html[^"]*)"', html
    )
    names = re.findall(r'data-click-from-value="([^"]+)"', html)
    for href, _id in links:
        url = "https:" + href
        # 同 <a> 附近的名称块匹配
        for name in names:
            core = keyword.replace(" ", "")
            if core and len(core) >= 2 and (core in name or name in core):
                return url
    return ("https:" + links[0][0]) if links else None


def summarize_detail(html: str) -> None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    print("detail title:", (m.group(1).strip()[:80] if m else "(none)"))
    og = re.search(
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html
    )
    print("og:image:", og.group(1)[:80] if og else "(none)")
    for key in (
        "imageList", "imagesList", "photoList", "imgList", "galleryList",
        "__INITIAL_STATE__", "window.pageData", '"photos"', '"image"',
    ):
        n = html.count(key)
        if n:
            print(f"key '{key}': {n}")
    domains: dict[str, int] = {}
    for u in re.findall(
        r'https?://[A-Za-z0-9.\-]+\.(?:qunar|qunarzz)\.(?:com|net)[^\s"\'<>\\)\]]*',
        html,
    ):
        d = re.match(r"https?://([^/]+)/", u + "/")
        if d:
            domains[d.group(1)] = domains.get(d.group(1), 0) + 1
    print("img domains:", domains)
    samples = []
    for u in re.findall(
        r'https?://[A-Za-z0-9.\-]+\.(?:qunar|qunarzz)\.(?:com|net)[^\s"\'<>\\)\]]*',
        html,
    ):
        if (
            any(e in u.lower() for e in (".jpg", ".jpeg", ".png", ".webp"))
            and u not in samples
        ):
            samples.append(u)
    for s in samples[:10]:
        print("img:", s[:95])
    print("total img samples:", len(samples))


client = httpx.Client()

print("######## QUNAR touch detail: 兵马俑 (req 3/3) ########")
time.sleep(1.0)
durl = pick_detail_url(
    (RAW_DIR / "qunar_touch_list.html").read_text(encoding="utf-8"), "兵马俑"
)
print("picked detail url:", (durl or "(none)")[:110])
if durl:
    try:
        resp = fetch(client, durl)
        html = resp.text
        (RAW_DIR / "qunar_detail_bingmayong.html").write_text(html, "utf-8")
        summarize_detail(html)
    except Exception as exc:
        print(f"  !! {type(exc).__name__}: {exc}")

print("\n######## QUNAR touch list: 西湖 (req 1/2) ########")
time.sleep(1.5)
try:
    html = touch_list("西湖")
    (RAW_DIR / "qunar_touch_list_xihu.html").write_text(html, "utf-8")
    ids = re.findall(r'/touch/detail_(\w+)\.html', html)
    names = re.findall(r'data-click-from-value="([^"]+)"', html)
    print("ids:", list(dict.fromkeys(ids))[:6])
    print("names:", names[:8])
    durl = pick_detail_url(html, "西湖")
    print("picked:", (durl or "(none)")[:110])
    if durl:
        time.sleep(1.5)
        print("######## QUNAR touch detail: 西湖 (req 2/2) ########")
        resp = fetch(client, durl)
        html2 = resp.text
        (RAW_DIR / "qunar_detail_xihu.html").write_text(html2, "utf-8")
        summarize_detail(html2)
except Exception as exc:
    print(f"  !! {type(exc).__name__}: {exc}")
