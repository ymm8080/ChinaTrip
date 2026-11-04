# -*- coding: utf-8 -*-
"""七省二级博物馆补缺 CSV 构建（ncha 全国博物馆名录 → museum2 补缺审阅包+导入档）。

输入 tmp_unesco/ncha_prov_all.json（scrape_ncha_by_province.py 产物）。
输出：
  DESIGN/POIS DATASOURCE/15_国家二级博物馆_七省补缺.csv  （审阅包，全列）
  CHINATRIP CODES/data/museum2_sevenprov.csv             （导入档，importer schema）
规范：name_zh 保留（曾用名）括号（对齐在库 344 行 baike 口径）；括号内容同时
入 alias_zh；city=省短名（PROVINCE_LEVEL 既有约定）；grade=国家二级博物馆。
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil

SRC_URL = "http://www.ncha.gov.cn/col/col2267/index.html"
PROV_SHORT = {
    "天津市": "天津", "吉林省": "吉林", "贵州省": "贵州", "西藏自治区": "西藏",
    "青海省": "青海", "宁夏回族自治区": "宁夏", "新疆维吾尔自治区": "新疆",
}
PAREN_RE = re.compile(r"^(.*?)\s*[（(]([^（）()]+)[)）]\s*$")


def main() -> int:
    data = json.load(open(r"tmp_unesco/ncha_prov_all.json", encoding="utf-8"))
    rows = []
    for prov_full, d in sorted(data.items()):
        short = PROV_SHORT[prov_full]
        for r in d["rows"]:
            if r["grade"] != "二级":
                continue
            name = re.sub(r"\s+", "", r["name"])
            alias = ""
            m = PAREN_RE.match(name)
            if m and m.group(1) and m.group(2) not in ("博物馆", "展览馆", "陈列馆"):
                alias = m.group(2)  # 泛称括号（文博院（博物馆）类）不入别名
            rows.append({
                "province": prov_full, "city": short, "name_zh": name,
                "nature": r["nature"], "free": r["free"], "alias_zh": alias,
                "source_url": SRC_URL,
            })

    out_review = r"DESIGN/POIS DATASOURCE/15_国家二级博物馆_七省补缺.csv"
    with io.open(out_review, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    out_import = r"CHINATRIP CODES/data/museum2_sevenprov.csv"
    with io.open(out_import, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name_zh", "province", "city", "grade", "batch", "alias_zh", "source_url"])
        for r in rows:
            w.writerow([r["name_zh"], r["province"], r["city"], "国家二级博物馆", "", r["alias_zh"], r["source_url"]])

    print(f"review pack: {out_review} ({len(rows)} rows)")
    print(f"import csv : {out_import}")
    from collections import Counter
    print(Counter(r["province"] for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
