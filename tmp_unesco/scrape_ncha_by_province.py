# -*- coding: utf-8 -*-
"""按省抓 ncha《全国博物馆名录》二级博物馆（补 museum2 六省缺口数据源）。

field_1434=省份全名 过滤有效（LIKE 匹配）；七省各翻至尾页，只留 质量等级=二级。
断点续抓：ncha_prov_all.json 按省累计；失败页记 ncha_prov_failed.txt。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

BASE = "http://www.ncha.gov.cn/module/search/index.jsp"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}

PROVINCES = ["天津市", "吉林省", "贵州省", "西藏自治区", "青海省",
             "宁夏回族自治区", "新疆维吾尔自治区"]

COLS = ("idx", "province", "name", "nature", "grade", "free", "collection",
        "precious", "exhibitions", "edu_events", "visitors")
ROW_RE = re.compile(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*"
                    r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def post_page(prov: str, page: int) -> tuple[int, list[dict]]:
    data = urllib.parse.urlencode({
        "field_1416": "", "field_1434": prov,
        "i_columnid": "2275", "field": "field_1416:1,field_1434:1",
        "currentplace": "", "splitflag": "", "fullpath": "0",
        "currpage": str(page), "download": "查询",
    }).encode()
    req = urllib.request.Request(BASE, data=data, headers={
        **UA, "Referer": "http://www.ncha.gov.cn/col/col2267/index.html",
        "Content-Type": "application/x-www-form-urlencoded"})
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", errors="replace")
    m = re.search(r"checkCurrpage\(1,\s*(\d+)\)", html)
    rows = []
    for mm in ROW_RE.finditer(html):
        cells = [TAG_RE.sub("", c).strip() for c in mm.groups()]
        if len(cells) != 11 or not cells[0].isdigit():
            continue
        rows.append(dict(zip(COLS, cells)))
    return (int(m.group(1)) if m else 1), rows


def main() -> int:
    try:
        result = json.load(open(r"tmp_unesco/ncha_prov_all.json", encoding="utf-8"))
    except FileNotFoundError:
        result = {}
    failed = []

    for prov in PROVINCES:
        if prov in result and result[prov].get("complete"):
            print(f"{prov}: already complete ({len(result[prov]['rows'])} rows)")
            continue
        acc: dict[int, list[dict]] = {}
        page = 1
        total = None
        while page <= (total or 1):
            for attempt in range(3):
                try:
                    total, rows = post_page(prov, page)
                    break
                except Exception as e:
                    print(f"  {prov} p{page} attempt {attempt+1} err: {e}")
                    time.sleep(2)
            else:
                print(f"  {prov} p{page} FAILED")
                failed.append(f"{prov}:p{page}")
                break
            acc[page] = rows
            print(f"  {prov} p{page}/{total} rows={len(rows)}")
            page += 1
            time.sleep(0.5)
        complete = total is not None and page > total
        all_rows = [r for p in sorted(acc) for r in acc[p]]
        result[prov] = {"complete": complete, "pages": total, "rows": all_rows}
        with open(r"tmp_unesco/ncha_prov_all.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

    if failed:
        with open(r"tmp_unesco/ncha_prov_failed.txt", "w", encoding="utf-8") as f:
            f.writelines(x + "\n" for x in failed)

    print("=== SUMMARY ===")
    for prov, d in result.items():
        second = [r for r in d["rows"] if r["grade"] == "二级"]
        print(f"{prov}: complete={d['complete']} total={len(d['rows'])} 二级={len(second)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
