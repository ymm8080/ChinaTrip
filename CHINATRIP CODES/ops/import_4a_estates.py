# -*- coding: utf-8 -*-
"""4A 名单庄园/酒庄类 12 行补灌（2026-11-03，4A 质检 v2 收口）。

官方 13_4A 汇编 4,674 行中 12 行庄园/酒庄类在库内无任何形态（其余缺失行
均为清洗/出池拍板删除）。本脚本按既有 4a 行形状补灌：
source='4a'、source_poi_id='4a_<续号 4675+>'、tags=['4a']、
tags_source='datasource_csv'、origin='cn_sync'，category/时长地板走
poi_classify（与 seed 路径同语义）。名称幂等：已存在同名行跳过。
"""

from __future__ import annotations

import csv
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.db import get_session_factory
from app.services.poi_classify import classify

SRC = r"D:/CHINATRIP/DESIGN/POIS DATASOURCE/13_4A级旅游景区_官方汇编4674.csv"
TARGETS = (
    "神农庄园",
    "振国壹号庄园",
    "榆树钱酒文化庄园",
    "张裕葡萄酒城（张裕卡斯特庄园）",
    "榆次区常家庄园",
    "河源市巴伐利亚庄园",
    "商水县叶氏庄园",
    "康百万庄园",
    "中国薰衣草庄园",
    "盘锦中尧七彩庄园",
    "伏尔加庄园",
    "普罗旺斯薰衣草庄园",
)


def main() -> int:
    with io.open(SRC, encoding="utf-8-sig", newline="") as f:
        rows = {r["name_zh"].strip(): r for r in csv.DictReader(f)}
    factory = get_session_factory()
    with factory.begin() as s:
        existing = {
            n
            for (n,) in s.execute(
                text("select name_zh from pois where name_zh is not null")
            )
        }
        max_seq = s.execute(
            text(
                "select coalesce(max(cast(substring(source_poi_id from '4a_([0-9]+)') "
                "as int)), 0) from pois where source='4a'"
            )
        ).scalar()
        seq = int(max_seq)
        inserted = 0
        for name in TARGETS:
            if name in existing:
                print(f"skip existing: {name}")
                continue
            row = rows.get(name)
            if row is None:
                print(f"skip not-in-csv: {name}")
                continue
            seq += 1
            city = (row.get("city") or row.get("province") or "").strip()
            city = city.removesuffix("市")
            cat, indoor, rain_ok, floor = classify(name, None)
            s.execute(
                text(
                    """insert into pois
                    (id, source, source_poi_id, city, name_zh, category, status,
                     tags, tags_source, origin, indoor, rain_ok,
                     suggested_duration_min, duration_source)
                    values (:id, '4a', :pid, :city, :name, :cat, 'active',
                            '["4a"]'::jsonb, 'datasource_csv', 'cn_sync',
                            :indoor, :rain_ok, :floor, 'heuristic')"""
                ),
                {
                    "id": str(uuid.uuid4()),
                    "pid": f"4a_{seq}",
                    "city": city,
                    "name": name,
                    "cat": cat,
                    "indoor": "yes" if indoor else ("no" if indoor is False else None),
                    "rain_ok": "yes"
                    if rain_ok
                    else ("no" if rain_ok is False else None),
                    "floor": floor,
                },
            )
            inserted += 1
    print(f"inserted={inserted} next_seq={seq}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
