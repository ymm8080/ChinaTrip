"""风景区时长一次性重算（ops，2026-10-31 用户拍板）。

背景：POIS 库里名称含景区标记（风景名胜区/旅游景区/旅游区/风景区/景区）
的行，heuristic 时长大多是旧规则留下的 90 分钟（5A 头部景区也 90，明显
偏短）。2026-10-31 poi_classify 已加「景区名→240 地板」，但 enrich 是只
填空作业，旧 heuristic 值不会被重算——本脚本做一次性重算：

- 「两行城市」名单（2026-10-31 用户在 90 分钟清单的两行城市小节上拍板，
  30 城）：180 分钟；
- 其余景区行（含无城市行）：240 分钟；
- 名称含 酒店/民宿/宾馆/公寓 的住宿噪声行不动（attraction 分类误挂，
  时长语义不适用，另行处理）；
- 真值行（ctrip/llm_web/qunar 等）本就不在选取范围内，天然不碰；
- 重算后 duration_source 维持 'heuristic'，真值源仍可按
  duration_upgradable 升级覆盖（与 poi_classify 语义一致）。

用法：python ops/recalc_scenic_duration.py            # dry-run 打印对照
      python ops/recalc_scenic_duration.py --apply   # 落库
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DSN = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"

SCENIC_NAME_RE = r"风景名胜区|旅游景区|旅游区|风景区|景区"
# 用户拍板 180 的两行城市名单（2026-10-31，90 分钟清单两行城市小节原文）
TWO_ROW_CITIES = {
    "丽江", "伊犁", "保亭", "六安", "厦门", "喀什", "嘉兴", "天津",
    "威海", "宁波", "安阳", "安顺", "宝鸡", "巴音郭楞", "常州", "忻州",
    "恩施", "惠州", "承德", "拉萨", "昆明", "晋中", "本溪", "林芝",
    "桂林", "毕节", "甘孜", "长沙", "青岛", "黄山",
}
# 住宿噪声（attraction 分类误挂，名称可辨）
STAY_NOISE_RE = re.compile(r"酒店|民宿|宾馆|公寓|度假村")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落库（默认 dry-run）")
    args = ap.parse_args()

    with psycopg.connect(DSN, connect_timeout=5) as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, name_zh, city
            FROM pois
            WHERE status='active'
              AND duration_source='heuristic'
              AND suggested_duration_min=90
              AND name_zh ~ %s
            ORDER BY city NULLS LAST, name_zh
            """,
            (SCENIC_NAME_RE,),
        )
        rows = cur.fetchall()

        stay_noise, plan = [], {}
        city_hits: dict[str, int] = {}
        for pid, name, city in rows:
            if STAY_NOISE_RE.search(name or ""):
                stay_noise.append((city, name))
                continue
            if city in TWO_ROW_CITIES:
                plan[pid] = (name, city, 180)
                city_hits[city] = city_hits.get(city, 0) + 1
            else:
                plan[pid] = (name, city, 240)

        n180 = sum(1 for _, _, v in plan.values() if v == 180)
        n240 = sum(1 for _, _, v in plan.values() if v == 240)
        odd = {c: n for c, n in city_hits.items() if n != 2}
        print(f"选取 {len(rows)} 行：180 ← {n180}，240 ← {n240}，"
              f"住宿噪声不动 ← {len(stay_noise)}")
        if odd:
            print(f"!! 两行城市名单中行数≠2 的城市（清单漂移，请复核）: {odd}")
        for city, name in stay_noise:
            print(f"   [噪声不动] {city or '?'} {name}")

        if not args.apply:
            print("\n(dry-run，加 --apply 落库)")
            return 0
        for pid, (_name, _city, minutes) in plan.items():
            cur.execute(
                "UPDATE pois SET suggested_duration_min=%s WHERE id=%s",
                (minutes, pid),
            )
        con.commit()
        print(f"已落库：{len(plan)} 行更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
