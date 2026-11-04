# -*- coding: utf-8 -*-
"""抓 ncha.gov.cn《全国博物馆名录》全量（col2267 查询接口，POST /module/search/index.jsp）。

705 页 × ~10 行 ≈ 7,046 家备案博物馆（2025-05 口径，含第五批评估结果）。
逐页 POST currpage=1..N，解析 11 列表格，落 tmp_unesco/ncha_all.json。
断点续抓：已抓页存 ncha_pages_done.txt，重跑跳过。
礼貌间隔 0.3s；失败重试 3 次，仍败则记入 ncha_pages_failed.txt。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

BASE = "http://www.ncha.gov.cn/module/search/index.jsp"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}

COLS = ("idx", "province", "name", "nature", "grade", "free", "collection",
        "precious", "exhibitions", "edu_events", "visitors")
ROW_RE = re.compile(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def post_page(page: int) -> str:
    data = urllib.parse.urlencode({
        "field_1416": "", "field_1434": "",
        "i_columnid": "2275", "field": "field_1416:1,field_1434:1",
        "currentplace": "", "splitflag": "", "fullpath": "0",
        "currpage": str(page), "download": "查询",
    }).encode()
    req = urllib.request.Request(BASE, data=data, headers={
        **UA, "Referer": "http://www.ncha.gov.cn/col/col2267/index.html",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_rows(html: str) -> list[dict]:
    out = []
    for m in ROW_RE.finditer(html):
        cells = [TAG_RE.sub("", c).strip() for c in m.groups()]
        if len(cells) != 11 or not cells[0].isdigit():
            continue
        out.append(dict(zip(COLS, cells)))
    return out


def max_page(html: str) -> int:
    m = re.search(r"checkCurrpage\(1,\s*(\d+)\)", html)
    return int(m.group(1)) if m else 0


def main() -> int:
    pages: dict[int, list[dict]] = {}
    done: set[int] = set()
    try:
        pages = {int(k): v for k, v in
                 json.load(open(r"tmp_unesco/ncha_all.json", encoding="utf-8")).items()}
        done = {int(l) for l in open(r"tmp_unesco/ncha_pages_done.txt") if l.strip()}
        print(f"resume: {len(done)} pages done, {sum(len(v) for v in pages.values())} rows")
    except FileNotFoundError:
        pass

    total_pages = max_page(post_page(1))
    print("total pages:", total_pages)

    for p in range(1, total_pages + 1):
        if p in done and p in pages:
            continue
        rows = None
        for attempt in range(3):
            try:
                rows = parse_rows(post_page(p))
                if rows or p == total_pages:
                    break
            except Exception as e:
                print(f"page {p} attempt {attempt + 1} err: {e}")
                time.sleep(1.5)
        if rows is None:
            print(f"page {p} FAILED permanently")
            with open(r"tmp_unesco/ncha_pages_failed.txt", "a", encoding="utf-8") as f:
                f.write(f"{p}\n")
            continue
        pages[p] = rows
        done.add(p)
        if p % 50 == 0 or p == total_pages:
            with open(r"tmp_unesco/ncha_all.json", "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in pages.items()}, f, ensure_ascii=False)
            with open(r"tmp_unesco/ncha_pages_done.txt", "w", encoding="utf-8") as f:
                f.writelines(f"{d}\n" for d in sorted(done))
            print(f"page {p}/{total_pages} ok ({len(rows)} rows), checkpoint saved")
        time.sleep(0.3)

    with open(r"tmp_unesco/ncha_all.json", "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in pages.items()}, f, ensure_ascii=False)
    all_rows = [r for p in sorted(pages) for r in pages[p]]
    with open(r"tmp_unesco/ncha_pages_done.txt", "w", encoding="utf-8") as f:
        f.writelines(f"{d}\n" for d in sorted(done))
    print("DONE total rows:", len(all_rows))
    from collections import Counter
    print("grade dist:", Counter(r["grade"] for r in all_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
