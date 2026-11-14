# -*- coding: utf-8 -*-
"""离线分析 qunar touch 页 HTML：图床域名/JSON 键/样例图。"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
RAW_DIR = Path(__file__).parent / "raw"

CDN_RE = re.compile(
    r"https?://[A-Za-z0-9.\-]+\.(?:qunar|qunarzz)\.(?:com|net)"
    r'[^\s"\'<>\\)\]]*'
)


def analyze(path: Path) -> None:
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        # 权限/编码/IO 故障不得裸奔（评审 rule 3：文件 IO 须 try-except）
        logger.error("read %s failed: %s", path, exc)
        return
    logger.info("=== %s len=%d ===", path.name, len(html))
    domains: dict[str, int] = {}
    for u in CDN_RE.findall(html):
        d = re.match(r"https?://([^/]+)/", u + "/")
        if d:
            domains[d.group(1)] = domains.get(d.group(1), 0) + 1
    logger.info("img domains: %s", domains)
    for key in (
        "imageList",
        "imagesList",
        "photoList",
        "sightPhotos",
        "__INITIAL_STATE__",
        "pageData",
        "gallery",
        "imgList",
        '"photos"',
        '"image"',
        "window.pageData",
        "window.__INITIAL_STATE__",
    ):
        n = html.count(key)
        if n:
            logger.info("key '%s': %d", key, n)
    # og/meta image
    for m in re.findall(r'<meta[^>]+(?:property|name)="og:[^"]*"[^>]*>', html)[:6]:
        logger.info("meta: %s", m[:150])
    # 样例图（含图片扩展名）
    samples = []
    for u in CDN_RE.findall(html):
        if (
            any(e in u.lower() for e in (".jpg", ".jpeg", ".png", ".webp"))
            and u not in samples
        ):
            samples.append(u)
    for s in samples[:12]:
        logger.info("img: %s", s[:95])
    logger.info("total img samples: %d", len(samples))
    # 找 imageList 上下文样例
    idx = html.find("imageList")
    if idx >= 0:
        logger.info("imageList ctx: %s", html[idx : idx + 300])
    idx2 = html.find('"sightPhotos"')
    if idx2 >= 0:
        logger.info("sightPhotos ctx: %s", html[idx2 : idx2 + 300])


if __name__ == "__main__":
    # CLI 直跑：INFO 全量透传（评审 rule 6：print 禁用，输出走 logger）
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in sys.argv[1:]:
        p = RAW_DIR / name
        if p.exists():
            analyze(p)
        else:
            logger.warning("missing: %s", name)
