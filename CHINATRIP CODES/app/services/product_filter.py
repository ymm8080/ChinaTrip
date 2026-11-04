"""§4 产品过滤共享闸（POIS_DATASOURCE §4：革命/红色 + 政治人物 + 战争军事）。

2026-10-25 用户拍板：红色旅游、政治人物/现代人物纪念、战争/军事纪念
**不进候选**。2026-11-03 红色出池两轮（389 行）后，本模块成为 §4 词表
的唯一正典源（此前散落在一次性 ops 脚本与会话内转换器）。

消费者：名单类导入作业在 load_rows 之后调 :func:`apply_product_filter`，
剔除行**必须**落 ``*_excluded.csv``（含 exclusion_reason，§4 纪律：
可回灌恢复）。已接：import_museum_grades（guobao/4A 未来同路径）、
import_shows（红色题材演艺，2026-11-03 拍板 红秀/西安事变 影画出池）。

刻意**不设** seed_upsert 全局闸：延安路/二七小路 这类路名字眼会误伤
hotel（延安饭店等五行为 2026-11-03 用户确认保留），类别相关判定留给
各导入作业的领域语义。
"""

from __future__ import annotations

import csv
import io

#: §4 革命/红色历史关键词（2026-10-25 拍板正典词表，原样照抄）
RED_TOKENS: tuple[str, ...] = (
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

#: §4 政治与现代人物纪念显式人名表（原样照抄；在世创始人命名馆不删，
#: 如 谢子龙/李自健/李昌钰——均不在表内）
POLITICAL_NAMES: tuple[str, ...] = (
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

#: §4 保留类抽样（古代人物/事件类，写测试锁定不误伤）
_KEEP_SAMPLES: tuple[str, ...] = (
    "杜甫草堂",
    "武侯祠",
    "三苏祠",
    "八大山人纪念馆",
    "蒲松龄故居",
    "李白纪念馆",
    "王安石纪念馆",
    "林则徐纪念馆",
    "大足石刻",
    "良渚博物院",
    "汶川特大地震纪念馆",
    "上海犹太难民纪念馆",
)


def red_exclusion_reason(name: str | None) -> str | None:
    """名称命中 §4 词表 → 剔除理由（人名表优先于关键词）；未命中 None。"""
    n = name or ""
    for t in POLITICAL_NAMES:
        if t in n:
            return f"§4人名:{t}"
    for t in RED_TOKENS:
        if t in n:
            return f"§4关键词:{t}"
    return None


def apply_product_filter(
    rows: list[dict], *, name_key: str = "name_zh"
) -> tuple[list[dict], list[dict]]:
    """种子行二分：(保留, 剔除)。剔除行附 exclusion_reason 字段。"""
    kept: list[dict] = []
    excluded: list[dict] = []
    for r in rows:
        reason = red_exclusion_reason(r.get(name_key) or "")
        if reason:
            excluded.append({**r, "exclusion_reason": reason})
        else:
            kept.append(r)
    return kept, excluded


def write_excluded_csv(
    path: str,
    excluded: list[dict],
    fields: tuple[str, ...] = ("source", "city", "name_zh", "exclusion_reason"),
) -> None:
    """剔除行落 excluded CSV（§4 纪律：可回灌恢复；整档覆盖=本次口径）。"""
    if not excluded:
        return
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(fields))
        for r in excluded:
            w.writerow([r.get(k, "") for k in fields])
