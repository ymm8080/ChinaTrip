# -*- coding: utf-8 -*-
"""import_datasource_03_06_07.py — P2 数据源导入（需城市解析器，backlog P2）.

范围（无 city 列、靠 app.services.poi_city 解析）：
  03_国家考古遗址公园_65.csv    → source='relicpark'   tags=['relicpark']
      province 列验向；city 由 ops 侧 65 行人工映射表（遗址所在县上卷）.
  06_中国历史文化名村_487.csv   → source='histvillage' tags=['histvillage']
      locality 县级 → resolve_city(province, locality).
  07_第八批全国重点文物保护单位_762.csv → source='guobao8' tags=['guobao8']
      address（省前缀 + 县/市）→ resolve_city(None, address).

幂等：seed_upsert 同 (source, source_poi_id) exists 短路；
source_poi_id = "{source}_{行号:04d}"（稳定行伪 id，同 import_datasource_csvs
先例）。骨架导入：不写 hours/price/phone（回源链专属）。identifier:
07 用 code 列（8-0001-1-001 全局唯一）直接当 id；03/06 用行号。

用法（在 `CHINATRIP CODES` 下；.env 仅此目录生效）：
    .venv\\Scripts\\python.exe ops\\import_datasource_03_06_07.py            # dry-run
    .venv\\Scripts\\python.exe ops\\import_datasource_03_06_07.py --apply
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\CHINATRIP\DESIGN\POIS DATASOURCE")

# 03 行 province 只有省级，city 无从机读：65 行人工映射（遗址所在县上卷，
# 口径 = canonical 短名，同 poi_city）。写死在这里便于 review/复跑.
REPLICPARK_CITY: dict[str, str] = {
    "泥河湾国家考古遗址公园": "张家口",
    "赵王城国家考古遗址公园": "邯郸",
    "邺城国家考古遗址公园": "邯郸",
    "辽上京国家考古遗址公园": "赤峰",
    "安吉古城国家考古遗址公园": "湖州",
    "凌家滩国家考古遗址公园": "马鞍山",
    "城村汉城国家考古遗址公园": "南平",
    "汉代海昏侯国国家考古遗址公园": "南昌",
    "仰韶村国家考古遗址公园": "三门峡",
    "二里头国家考古遗址公园": "洛阳",
    "郑州商城国家考古遗址公园": "郑州",
    "屈家岭国家考古遗址公园": "荆门",
    "龙湾国家考古遗址公园": "潜江",
    "炭河里国家考古遗址公园": "长沙",
    "靖江王府及王陵国家考古遗址公园": "桂林",
    "邛窑国家考古遗址公园": "成都",
    "石峁国家考古遗址公园": "榆林",
    "统万城国家考古遗址公园": "榆林",
    "乾陵国家考古遗址公园": "咸阳",
    "元中都国家考古遗址公园": "张家口",
    "大窑龙泉窑国家考古遗址公园": "丽水",
    "上林湖越窑国家考古遗址公园": "宁波",
    "明中都皇故城国家考古遗址公园": "滁州",
    "万寿岩国家考古遗址公园": "三明",
    "城子崖国家考古遗址公园": "济南",
    "吉州窑国家考古遗址公园": "吉安",
    "郑韩故城国家考古遗址公园": "郑州",
    "盘龙城国家考古遗址公园": "武汉",
    "城头山国家考古遗址公园": "常德",
    "汉长安城未央宫国家考古遗址公园": "西安",
    "西夏陵国家考古遗址公园": "银川",
    "牛河梁国家考古遗址公园": "朝阳",
    "渤海中京国家考古遗址公园": "延边",
    "渤海上京国家考古遗址公园": "牡丹江",
    "御窑厂国家考古遗址公园": "景德镇",
    "曲阜鲁国故城国家考古遗址公园": "济宁",
    "大运河南旺枢纽国家考古遗址公园": "济宁",
    "汉魏洛阳故城国家考古遗址公园": "洛阳",
    "熊家冢国家考古遗址公园": "荆州",
    "长沙铜官窑国家考古遗址公园": "长沙",
    "甑皮岩国家考古遗址公园": "桂林",
    "钓鱼城国家考古遗址公园": "重庆",
    "北庭故城国家考古遗址公园": "昌吉",
    "圆明园国家考古遗址公园": "北京",
    "周口店国家考古遗址公园": "北京",
    "集安高句丽国家考古遗址公园": "通化",
    "鸿山国家考古遗址公园": "无锡",
    "良渚国家考古遗址公园": "杭州",
    "殷墟国家考古遗址公园": "安阳",
    "隋唐洛阳城国家考古遗址公园": "洛阳",
    "三星堆国家考古遗址公园": "德阳",
    "金沙国家考古遗址公园": "成都",
    "阳陵国家考古遗址公园": "咸阳",
    "秦始皇陵国家考古遗址公园": "西安",
    "大明宫国家考古遗址公园": "西安",
    "陶寺国家考古遗址公园": "临汾",
    "萨拉乌苏国家考古遗址公园": "鄂尔多斯",
    "和林格尔土城子国家考古遗址公园": "呼和浩特",
    "上山国家考古遗址公园": "金华",
    "双墩国家考古遗址公园": "蚌埠",
    "大汶口国家考古遗址公园": "泰安",
    "大河村国家考古遗址公园": "郑州",
    "铜绿山国家考古遗址公园": "黄石",
    "宝墩国家考古遗址公园": "成都",
    "秦咸阳城咸阳宫国家考古遗址公园": "咸阳",
}

FILES: list[tuple[str, str, list[str]]] = [
    ("03_国家考古遗址公园_65.csv", "relicpark", ["relicpark"]),
    ("06_中国历史文化名村_487.csv", "histvillage", ["histvillage"]),
    ("07_第八批全国重点文物保护单位_762.csv", "guobao8", ["guobao8"]),
]


def read_rows(fname: str) -> list[dict]:
    with (ROOT / fname).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def city_of(source: str, row: dict) -> str | None:
    from app.services.poi_city import canonical_city, resolve_city

    if source == "relicpark":
        city = REPLICPARK_CITY.get(row["name_zh"].strip())
        return canonical_city(city) if city else None
    if source == "histvillage":
        return resolve_city(row["province"], row["locality"])
    return resolve_city(None, row["address"])


def poi_id(source: str, row: dict, i: int) -> str:
    # 07 code 列（8-0001-1-001）全局稳定，比行号抗重排
    code = (row.get("code") or "").strip()
    return f"{source}_{code}" if code else f"{source}_{i:04d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    apply_flag = ap.parse_args().apply

    plan: list[tuple[str, str, list[str], list[dict], dict[int, str | None]]] = []
    for fname, source, tags in FILES:
        rows = read_rows(fname)
        cities: dict[int, str | None] = {}
        for i, row in enumerate(rows, 1):
            cities[i] = city_of(source, row)
        plan.append((fname, source, tags, rows, cities))
        dist = collections.Counter(v for v in cities.values() if v)
        miss = [(i, rows[i - 1]["name_zh"]) for i, v in cities.items() if not v]
        resolved_n = sum(1 for v in cities.values() if v)
        print(
            f"{fname}: rows={len(rows)} resolved={resolved_n}/{len(rows)}"
            f" distinct_cities={len(dist)} miss={len(miss)}"
        )
        for city, n in dist.most_common(12):
            print(f"    {city}: {n}")
        if miss:
            print(f"    miss rows: {miss[:10]}")
    if not apply_flag:
        print("dry-run only — rerun with --apply to write")
        return 0

    from app.db import get_session_factory
    from app.models import Poi
    from app.services.poi_seed import seed_upsert

    fac = get_session_factory()
    for fname, source, tags, rows, cities in plan:
        stats = {"created": 0, "exists": 0, "skipped": 0}
        for i, row in enumerate(rows, 1):
            city = cities[i]
            name = (row.get("name_zh") or "").strip()
            if not name or not city:
                stats["skipped"] += 1
                continue
            aliases = (row.get("alias_zh") or "").split("|")
            alias = [a.strip() for a in aliases if a.strip()]
            outcome = seed_upsert(
                fac,
                Poi,
                source=source,
                source_poi_id=poi_id(source, row, i),
                city=city,
                name_zh=name,
                name_aliases=alias or None,
                tags=tags or None,
                tags_source="datasource_csv",
                origin="cn_sync",
            )
            stats[outcome] = stats.get(outcome, 0) + 1
        print(f"{fname}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
