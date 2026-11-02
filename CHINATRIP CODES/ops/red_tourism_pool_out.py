# -*- coding: utf-8 -*-
"""红色/政治/军事纪念行出池（2026-11-03，POIS_DATASOURCE §4 产品过滤）。

范围（宁缺勿错）：仅 status='active' AND category IS NULL 的骨架行（即
NULL 分类池——2026-10-31 会话核查确认其中约 842 行为红色旅游旧址类）。
其他 category 的行（museum/attraction 等）即使命中词表也**只进 flag
报告不动库**——§4 说不确定者宁缺勿错，全面清洗属独立拍板项。

规则：§4 正典词表（革命/红色 + 政治人物显式表 + 战争军事），不使用
区县级大表（漏网逐个 flag 机制，见 §4）。
处置：status='inactive' 软删（可回灌）；剔除行落
ops/red_tourism_excluded_2026-11-03.csv（poi_id/city/name/reason，
§4 纪律：全部剔除行必须落 excluded.csv 含 exclusion_reason）。
未命中但名称含 旧址/纪念/陵园 的 NULL 行列 flag 清单供人复核。
"""

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

OUT_CSV = Path(__file__).parent / "red_tourism_excluded_2026-11-03.csv"
FLAG_MD = Path(__file__).parent / "red_tourism_flag_review_2026-11-03.md"

#: §4 革命/红色历史关键词（2026-10-25 拍板正典词表，原样照抄）
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
#: §4 政治与现代人物纪念显式人名表（原样照抄）
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
FLAG_HINT = re.compile(r"旧址|遗址|纪念|陵园|故居|殉难|死难|遇难|罹难")

eng = create_engine(
    "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
    connect_args={"connect_timeout": 3},
)


def reason_of(name: str) -> str:
    for t in TOKENS:
        if t in name:
            return f"§4关键词:{t}"
    return ""


def main() -> int:
    with eng.connect() as c:
        null_rows = c.execute(
            text(
                "select id, city, name_zh, source from pois "
                "where status='active' and category is null and name_zh is not null"
            )
        ).fetchall()
    hits = [(r, reason_of(r.name_zh)) for r in null_rows if reason_of(r.name_zh)]
    flags = [
        r for r in null_rows if not reason_of(r.name_zh) and FLAG_HINT.search(r.name_zh)
    ]
    others = []
    if hits:
        with eng.begin() as c:
            for r, reason in hits:
                c.execute(
                    text(
                        "update pois set status='inactive', updated_at=NOW() "
                        "where id=:i and status='active'"
                    ),
                    {"i": r.id},
                )
            others = c.execute(
                text(
                    "select count(*) from pois where status='active' "
                    "and category is not null and name_zh ~ :pat"
                ),
                {"pat": "|".join(RED_TOKENS)},
            ).scalar()
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["poi_id", "city", "name_zh", "source", "exclusion_reason", "excluded_at"]
        )
        for r, reason in hits:
            w.writerow(
                [
                    r.id,
                    r.city,
                    r.name_zh,
                    r.source,
                    reason,
                    datetime.now().isoformat(timespec="seconds"),
                ]
            )
    with io.open(FLAG_MD, "w", encoding="utf-8") as f:
        f.write("# 红色/纪念类 flag 复核清单（2026-11-03，未动库）\n\n")
        f.write(
            f"> NULL 池 {len(null_rows)} 行中命中 §4 词表 {len(hits)} 行已软删"
            "（见 red_tourism_excluded_2026-11-03.csv）；"
            f"未命中但名称含 旧址/纪念/陵园/故居 类词的 {len(flags)} 行列此清单"
            "宁缺勿错，请人工过目。\n\n"
        )
        for r in flags:
            f.write(f"- {r.city or '—'}｜{r.name_zh}｜{r.source}\n")
        f.write(
            f"\n## 其他 category 命中 §4 词表的 active 行（{others} 行，本轮未动）\n\n"
            "> 全面清洗需独立拍板：museum/attraction 里含 革命/烈士/中共 等词的行"
            "（如各类纪念馆）是否同样出池，见 POIS_DATASOURCE §4。\n"
        )
    print(
        f"NULL pool={len(null_rows)} excluded={len(hits)} flagged={len(flags)} "
        f"other-category matches (untouched)={others}"
    )
    print("csv:", OUT_CSV)
    print("flag list:", FLAG_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
