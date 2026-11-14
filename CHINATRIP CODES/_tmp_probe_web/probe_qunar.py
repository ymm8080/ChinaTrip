# -*- coding: utf-8 -*-
"""Qunar 景点页探针：搜索落地页 + 详情页形状自查。

礼貌约束：每个景点最多 3 次请求（搜索 1 + 详情 1 + 备选详情 1），
串行执行，超时 10s，浏览器 UA。原始 HTML 存 raw/ 目录供离线分析。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).parent / "raw"
RAW_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://piao.qunar.com/",
}


def fetch(client: httpx.Client, url: str) -> httpx.Response:
    print(f"[req] GET {url[:100]}")
    resp = client.get(url, headers=HEADERS, timeout=10.0, follow_redirects=True)
    print(f"  -> HTTP {resp.status_code}  final={str(resp.url)[:90]}")
    print(f"  -> len={len(resp.text)}  ct={resp.headers.get('content-type', '')[:40]}")
    return resp


def summarize(tag: str, html: str) -> None:
    """快速统计页面里可抽取的图集键路径。"""
    print(f"\n===== {tag} summarize =====")
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    print("title:", (m.group(1).strip()[:80] if m else "(none)"))
    for meta_key in ("og:image", "og:title"):
        mm = re.search(
            rf'<meta[^>]+property="{meta_key}"[^>]+content="([^"]+)"', html
        )
        print(f"{meta_key}:", mm.group(1)[:80] if mm else "(none)")
    # 常见内嵌 JSON 键
    for key in (
        "imageList",
        "imagesList",
        "photoList",
        "sightPhotos",
        "__INITIAL_STATE__",
        "window.__initialState",
        "pageData",
        "gallery",
    ):
        n = html.count(key)
        if n:
            print(f"key '{key}' count={n}")
    # 图床 URL 形态
    domains = {}
    for u in re.findall(r'https?://[A-Za-z0-9.\-]+\.(?:qunar|qunarzz)\.(?:com|net)[^\s"\'<>\)\\]*', html):
        d = re.match(r"https?://([^/]+)/", u + "/")
        if d:
            domains[d.group(1)] = domains.get(d.group(1), 0) + 1
    print("img domains:", domains)
    # 样例图 URL（截断 60）
    samples = []
    for u in re.findall(
        r'https?://[A-Za-z0-9.\-]+\.qunarzz\.com[^\s"\'<>\)\\]+',
        html,
    ):
        if any(ext in u for ext in (".jpg", ".jpeg", ".png", ".webp")) and u not in samples:
            samples.append(u)
    for s in samples[:6]:
        print("img:", s[:60])
    print("samples:", len(samples))


def probe(keyword: str, filename: str) -> None:
    with httpx.Client() as client:
        # req1: 搜索落地页
        search_url = f"https://piao.qunar.com/ticket/list.htm?keyword={keyword}"
        try:
            resp = fetch(client, search_url)
        except Exception as exc:
            print(f"  !! search failed: {type(exc).__name__}: {exc}")
            return
        html = resp.text
        (RAW_DIR / f"{filename}_search.html").write_text(html, "utf-8")
        summarize(f"{keyword} search(list.htm)", html)

        # 详情 id 形状自查
        ids = re.findall(r'/(?:ticket|touch)/detail\.htm\?id=(\w+)', html)
        ids_unique = list(dict.fromkeys(ids))
        print("detail ids found:", ids_unique[:8])

        # req2: 取第一个详情页
        if ids_unique:
            detail_url = f"https://piao.qunar.com/ticket/detail.htm?id={ids_unique[0]}"
            time.sleep(1.5)
            try:
                resp2 = fetch(client, detail_url)
            except Exception as exc:
                print(f"  !! detail failed: {type(exc).__name__}: {exc}")
                return
            dhtml = resp2.text
            (RAW_DIR / f"{filename}_detail.html").write_text(dhtml, "utf-8")
            summarize(f"{keyword} detail({ids_unique[0]})", dhtml)


if __name__ == "__main__":
    for kw, fn in (("兵马俑", "bingmayong"), ("西湖", "xihu")):
        print(f"\n######## QUNAR probe: {kw} ########")
        try:
            probe(kw, fn)
        except Exception as exc:
            print(f"probe error: {type(exc).__name__}: {exc}")
        time.sleep(2.0)
