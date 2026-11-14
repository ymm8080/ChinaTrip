# -*- coding: utf-8 -*-
"""qunar / mafengwo 景点图片源探针（一次性调研脚本，不入正式链）。

每站最多 3 次请求：站内搜索落地 → 详情页 HTML 扫图集键路径。
报告写 PROBE.md；绝不打印任何 key（本脚本无 key）。
"""

import re
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "PROBE.md"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
HDRS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")

results: list[str] = []


def log(line: str) -> None:
    print(line)
    results.append(line)


def scan_images(html: str, limit: int = 8) -> dict:
    """递归找 img 域名聚类 + 常见图集键。"""
    domains: dict[str, int] = {}
    for u in URL_RE.findall(html)[:4000]:
        m = re.match(r"https?://([^/]+)/", u)
        if m and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", u, re.I):
            domains[m.group(1)] = domains.get(m.group(1), 0) + 1
    keys = {}
    for pat in ("imageList", "images", "picUrl", "photoList", "og:image"):
        if pat in html:
            keys[pat] = html.count(pat)
    return {"img_domains": dict(sorted(domains.items(), key=lambda kv: -kv[1])[:6]), "keys": keys}


def probe(client: httpx.Client, name: str, url: str) -> None:
    log(f"\n## {name}")
    log(f"- GET {url[:110]}")
    try:
        r = client.get(url, timeout=15.0, follow_redirects=True)
        log(f"- HTTP {r.status_code}, len={len(r.text)}, final={str(r.url)[:110]}")
        if r.status_code != 200:
            log(f"- title段: {r.text[:200]!r}")
            return
        s = scan_images(r.text)
        log(f"- img域名: {s['img_domains']}")
        log(f"- 图集键: {s['keys']}")
        m = re.search(r"<title>([^<]{4,80})</title>", r.text)
        if m:
            log(f"- <title>: {m.group(1)}")
    except Exception as exc:
        log(f"- EXC: {type(exc).__name__}: {str(exc)[:160]}")


def main() -> int:
    with httpx.Client(headers=HDRS) as c:
        # qunar：搜索落地页 → 若 302 到详情则已含详情
        probe(c, "qunar 搜索 兵马俑", "https://piao.qunar.com/touch/list.htm?keyword=%E5%85%B5%E9%A9%AC%E4%BF%91&city=%E8%A5%BF%E5%AE%89")
        probe(c, "qunar 搜索 西湖", "https://piao.qunar.com/touch/list.htm?keyword=%E8%A5%BF%E6%B9%96&city=%E6%9D%AD%E5%B7%9E")
        # mafengwo：poi 页（11 号西湖经典 poi id 已知形状，搜索页需 JS 时直接试已知 poi）
        probe(c, "mafengwo 西湖 poi/2", "https://www.mafengwo.cn/poi/2.html")
        probe(c, "mafengwo 兵马俑搜索", "https://www.mafengwo.cn/search/q.php?q=%E5%85%B5%E9%A9%AC%E4%BF%91")
    OUT.write_text("\n".join(results), encoding="utf-8")
    print("\nsaved:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
