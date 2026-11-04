# -*- coding: utf-8 -*-
"""5A 名单刷新对齐收口（§3.2 #3，2026-11-03；提案见 ops/5a_align_proposal_2026-11-03.md）。

显式裁决表（dry-run 已人工核对，禁用模糊自动选 keeper）：
  MERGES  13 站：跨源 keeper 行 tags 追加 '5a'（直接 UPDATE，幂等）
  RENAMES 15 行：库内 5a 变体名 → 包内官方名（旧名进 name_aliases，幂等按新名判）
  INSERTS  4 行：全源确无 → 插 5a 骨架（续号 5a_350..；坐标/EN 留空走回源链）
C 类（六盘山红军长征）§4 出池不导入；其余变体对（万盛黑山谷标点/乐满地等）留后续。

用法：
    .venv\\Scripts\\python.exe ops\\import_5a_gap_2026-11-03.py            # dry-run
    .venv\\Scripts\\python.exe ops\\import_5a_gap_2026-11-03.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.services.poi_seed import seed_upsert  # noqa: E402
from app.models import Poi  # noqa: E402

#: (包内站点名, keeper source, keeper source_poi_id 或名称精确)
MERGES = [
    ("颐和园", "unesco", "颐和园"),
    ("秦皇岛市山海关景区", "baidu", "山海关景区"),
    ("齐齐哈尔市扎龙生态旅游区", "4a", "扎龙生态旅游区"),
    ("上海科技馆", "museum1", "上海科技馆"),
    ("金华市双龙风景旅游区", "scenic", "双龙风景名胜区"),
    ("龙岩市冠豸山景区", "scenic", "冠豸山风景名胜区"),
    ("上饶市篁岭景区", "histvillage", "篁岭村"),
    ("崇左市花山岩画景区", "unesco", "花山岩画"),
    ("大足石刻景区", "unesco", "大足石刻"),
    ("新乡市宝泉旅游区", "4a", "新乡市宝泉旅游度假区"),
    ("咸阳市乾陵景区", "4a", "乾陵博物馆"),
    ("甘南州冶力关旅游区", "4a", "临潭县冶力关景区"),
    ("西安市华清宫景区", "intl", "华清宫"),
    ("沈阳市 沈阳植物园", "baidu", "沈阳植物园"),
    ("呼和浩特市老牛湾黄河大峡谷旅游区", "4a", "老牛湾黄河大峡谷旅游区"),
]

#: (5a source_poi_id, 官方名, 旧名入别名)
RENAMES = [
    ("5a_049", "伪满皇宫博物院", "伪满皇宫博物馆"),
    ("5a_069", "钟山风景名胜区－中山陵园风景区", "钟山中山陵风景名胜区"),
    ("5a_078", "金鸡湖旅游区", "金鸡湖国家商务旅游示范区"),
    ("5a_167", "嵩山少林景区", "嵩山少林寺景区"),
    ("5a_296", "秦始皇帝陵博物院", "秦始皇兵马俑博物馆"),
    ("5a_077", "溱湖旅游景区", "溱湖国家湿地公园"),
    ("5a_131", "白水洋·鸳鸯溪旅游景区", "屏南县旅游景区"),
    ("5a_176", "西峡恐龙遗迹园－伏牛山－老界岭旅游区", "伏牛山老界岭中国恐龙遗址园旅游区"),
    ("5a_214", "雁南飞茶田景区", "梅县区雁南飞茶田景区"),
    ("5a_330", "金湖杨景区", "喀什地区泽普县金胡杨景区"),
    ("5a_079", "金山·焦山·北固山风景区", "三山风景名胜区"),
    ("5a_093", "杭州西湖风景区", "西湖区西湖风景区"),
    ("5a_213", "白云山景区", "白云区白云山风景区"),
    ("5a_075", "瘦西湖风景区", "邗江区瘦西湖风景区"),
    ("5a_104", "南浔古镇景区", "南浔区南浔古镇景区"),
    ("5a_285", "中国科学院西双版纳热带植物园", "中科院西双版纳热带植物园"),
    ("5a_301", "法门文化景区", "扶风县法门寺佛文化景区"),
    ("5a_187", "神农溪纤夫文化旅游区", "神龙溪纤夫文化旅游区"),
]

#: (官方名, city) —— 全源确无
INSERTS = [
    ("衡水湖旅游景区", "衡水"),
    ("鲁迅故里·沈园景区", "绍兴"),
    ("周村古商城景区", "淄博"),
    ("万绿湖风景区", "河源"),
    ("晋祠天龙山景区", "太原"),
    ("喀什古城景区", "喀什"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    factory = get_session_factory()

    with factory() as session:
        print("=== MERGES（tags 追加 5a）===")
        for pack_name, src, keeper_name in MERGES:
            row = session.execute(text(
                "select id, name_zh, status, tags::text from pois "
                "where source=:s and name_zh=:n"), {"s": src, "n": keeper_name}).fetchone()
            if row is None:
                print(f"  !! MISS {src}/{keeper_name}")
                continue
            has5a = '"5a"' in (row[3] or "[]")
            print(f"  {'SKIP' if has5a else 'MERGE':<5} {pack_name} -> [{src}] {row[1]} ({row[2]})")

    with factory() as session:
        print("=== RENAMES（5a 变体→官方名）===")
        for sid, new, old in RENAMES:
            row = session.execute(text(
                "select name_zh, status from pois where source='5a' and source_poi_id=:sid"),
                {"sid": sid}).fetchone()
            if row is None:
                print(f"  !! MISS {sid}")
                continue
            print(f"  RENAME {sid}: {row[0]} -> {new}  (alias+={old})")

    with factory() as session:
        print("=== INSERTS（5a 骨架）===")
        for official, city in INSERTS:
            print(f"  INSERT 5a_??? {official} ({city})")

    if not args.apply:
        print("dry-run only (use --apply)")
        return 0

    with factory() as session:
        for pack_name, src, keeper_name in MERGES:
            res = session.execute(text(
                "update pois set tags = (coalesce(tags,'[]'::jsonb) || '[\"5a\"]'::jsonb), "
                "updated_at = now() "
                "where source=:s and name_zh=:n and status='active' "
                "and not coalesce(tags,'[]'::jsonb) @> '[\"5a\"]'::jsonb"),
                {"s": src, "n": keeper_name})
            print(f"  merged {src}/{keeper_name}: {res.rowcount}")
        for sid, new, old in RENAMES:
            res = session.execute(text(
                "update pois set name_zh=:new, "
                "name_aliases = (coalesce(name_aliases,'[]'::jsonb) || to_jsonb(cast(:old as text))), "
                "updated_at=now() "
                "where source='5a' and source_poi_id=:sid and name_zh <> :new"),
                {"new": new, "old": old, "sid": sid})
            print(f"  renamed {sid}: {res.rowcount}")
        session.commit()
        maxrow = session.execute(text(
            "select coalesce(max(substring(source_poi_id from '[0-9]+$')::int),0) "
            "from pois where source='5a'")).scalar()
    seq = int(maxrow)
    for official, city in INSERTS:
        seq += 1
        sid = f"5a_{seq:03d}"
        out = seed_upsert(
            factory, Poi, source="5a", source_poi_id=sid,
            city=city, name_zh=official, category="attraction",
            origin="cn_sync", tags=["5a"], tags_source="mct")
        print(f"  inserted {sid} {official} ({city}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
