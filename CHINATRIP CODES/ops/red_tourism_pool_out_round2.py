# -*- coding: utf-8 -*-
"""红色出池第二轮（2026-11-03，用户拍板：flag 82 行全出仅留毛主席纪念堂、
其他类别 §4 命中行全出——含 show/historic/theme_park 的红色题材行；
hotel 5 行路名误报（延安路/二七小路）保留）。

A 批：red_tourism_flag_review_2026-11-03.md 全部 82 行 - 毛主席纪念堂。
B 批：status='active' AND category<>'hotel' AND name 命中 §4 词表
      （首轮 NULL 池已删的 56 行不重复）。
处置同首轮：status='inactive' 软删；落
ops/red_tourism_excluded_round2_2026-11-03.csv（含 exclusion_reason 与批次）。
"""

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

SRC = Path(__file__).parent / "red_tourism_flag_review_2026-11-03.md"
OUT_CSV = Path(__file__).parent / "red_tourism_excluded_round2_2026-11-03.csv"

RED_TOKENS = (
    "革命",
    "苏区",
    "红军",
    "红色",
    "起义",
    "战役",
    "大战",
    "战斗",
    "突围",
    "抗战",
    "抗日",
    "抗美援朝",
    "惨案",
    "屠杀",
    "烈士",
    "八路军",
    "新四军",
    "野战军",
    "纵队",
    "游击",
    "边区",
    "军史",
    "军工",
    "军事",
    "炮台",
    "要塞",
    "集中营",
    "事变",
    "二七",
    "延安",
    "共产党员",
    "中共",
    "勤工俭学",
    "三线",
    "西路军",
    "围剿",
    "党史",
    "庐山会议",
    "战争",
    "转兵",
    "方面军",
    "监狱",
)
POLITICAL_NAMES = (
    "毛泽东",
    "周恩来",
    "朱德",
    "邓小平",
    "刘少奇",
    "宋庆龄",
    "孙中山",
    "胡耀邦",
    "彭德怀",
    "贺龙",
    "任弼时",
    "刘伯承",
    "叶剑英",
    "陈毅",
    "粟裕",
    "陈独秀",
    "彭真",
    "雷锋",
    "焦裕禄",
    "孔繁森",
    "张謇",
    "鲁迅",
    "丁玲",
    "张学良",
    "贺子珍",
    "隆平",
    "王进喜",
    "李大钊",
    "赵一曼",
    "杨靖宇",
    "瞿秋白",
    "周尧",
    "王学仲",
    "三杰",
    "韬奋",
    "赵尚志",
)
TOKENS = RED_TOKENS + POLITICAL_NAMES
KEEP_EXCEPTION = "毛主席纪念堂"  # 用户点名保留


def reason_of(name: str) -> str:
    for t in TOKENS:
        if t in name:
            return f"§4关键词:{t}"
    return "§4 flag人工确认"


def main() -> int:
    # A 批：flag 清单解析（跳过保留例外）
    a_rows = []
    for ln in io.open(SRC, encoding="utf-8").read().splitlines():
        m = re.match(r"- (.*?)｜(.+?)｜", ln)
        if m and m.group(2).strip() != KEEP_EXCEPTION:
            a_rows.append((m.group(1).strip(), m.group(2).strip()))

    eng = create_engine(
        "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
        connect_args={"connect_timeout": 3},
    )
    with eng.connect() as c:
        b_rows = c.execute(
            text(
                "select city, name_zh, category, source from pois "
                "where status='active' and category <> 'hotel' "
                "and category is not null and name_zh is not null"
            )
        ).fetchall()
    b_hits = [r for r in b_rows if any(t in r.name_zh for t in TOKENS)]

    stats = {"a_deleted": 0, "b_deleted": 0, "miss": []}
    with eng.begin() as c:
        for city, name in a_rows:
            r = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW() "
                    "where status='active' and city=:c and name_zh=:n"
                ),
                {"c": city, "n": name},
            )
            if r.rowcount:
                stats["a_deleted"] += r.rowcount
            else:
                stats["miss"].append(("A", city, name))
        for r in b_hits:
            u = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW() "
                    "where status='active' and city=:c and name_zh=:n"
                ),
                {"c": r.city, "n": r.name_zh},
            )
            if u.rowcount:
                stats["b_deleted"] += u.rowcount
            else:
                stats["miss"].append(("B", r.city, r.name_zh))

    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "poi_id_like",
                "city",
                "name_zh",
                "batch",
                "exclusion_reason",
                "excluded_at",
            ]
        )
        now = datetime.now().isoformat(timespec="seconds")
        for city, name in a_rows:
            w.writerow(["", city, name, "A_flag", "§4 flag人工确认", now])
        for r in b_hits:
            w.writerow(
                ["", r.city, r.name_zh, "B_other_cat", reason_of(r.name_zh), now]
            )
    kept = None
    with eng.connect() as c:
        kept = c.execute(
            text("select status, category from pois where name_zh = :n"),
            {"n": KEEP_EXCEPTION},
        ).fetchall()
    print(stats)
    print(
        f"A批 {len(a_rows)} 组 / B批 {len(b_hits)} 组；"
        f"保留例外 {KEEP_EXCEPTION}: {kept}"
    )
    print("csv:", OUT_CSV)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
