# -*- coding: utf-8 -*-
"""离线分析 qunar touch 页 HTML：图床域名/JSON 键/样例图。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw"

CDN_RE = re.compile(
    r'https?://[A-Za-z0-9.\-]+\.(?:qunar|qunarzz)\.(?:com|net)'
    r'[^\s"\'<>\\)\]]*'
)


def analyze(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    print(f"=== {path.name} len={len(html)} ===")
    domains: dict[str, int] = {}
    for u in CDN_RE.findall(html):
        d = re.match(r"https?://([^/]+)/", u + "/")
        if d:
            domains[d.group(1)] = domains.get(d.group(1), 0) + 1
    print("img domains:", domains)
    for key in (
        "imageList", "imagesList", "photoList", "sightPhotos",
        "__INITIAL_STATE__", "pageData", "gallery", "imgList",
        '"photos"', '"image"', "window.pageData", "window.__INITIAL_STATE__",
    ):
        n = html.count(key)
        if n:
            print(f"key '{key}': {n}")
    # og/meta image
    for m in re.findall(
        r'<meta[^>]+(?:property|name)="og:[^"]*"[^>]*>', html
    )[:6]:
        print("meta:", m[:150])
    # 样例图（含图片扩展名）
    samples = []
    for u in CDN_RE.findall(html):
        if (
            any(e in u.lower() for e in (".jpg", ".jpeg", ".png", ".webp"))
            and u not in samples
        ):
            samples.append(u)
    for s in samples[:12]:
        print("img:", s[:95])
    print("total img samples:", len(samples))
    # 找 imageList 上下文样例
    idx = html.find("imageList")
    if idx >= 0:
        print("imageList ctx:", html[idx : idx + 300])
    idx2 = html.find('"sightPhotos"')
    if idx2 >= 0:
        print("sightPhotos ctx:", html[idx2 : idx2 + 300])


if __name__ == "__main__":
    for name in sys.argv[1:]:
        p = RAW_DIR / name
        if p.exists():
            analyze(p)
        else:
            print(f"missing: {name}")
