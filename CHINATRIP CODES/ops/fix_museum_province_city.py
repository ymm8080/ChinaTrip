"""museum1/2/3 省级回退 city 修复（2026-11-03 数据债收口）.

import_museum_grades 对区县馆行把 city 落成省名回退（黑龙江/山东/…），
这些行永远过不了规划池门槛（poi_city canonical 城市表），坐标链也喂不进
——backfill_locations 的 city 闸把它们整批挡住。

本作业按「馆藏名头解析」归一：名单里绝大多数馆名带「X市/A盟/X州」头
（张家口市博物馆 / 兴安盟博物馆 / 伊犁哈萨克自治州博物馆 …），用
poi_city.resolve_city(None, name_zh) + city_from_name 从名字解析出地级
短名后直接写 city。同名双关省名（吉林=吉林省 & 吉林市、海南=海南省 &
海南州）行不动，排除误伤。

幂等可重跑：再跑一遍无 hits 即 done。

用法：
    python -m ops.fix_museum_province_city            # dry-run 只打印
    python -m ops.fix_museum_province_city --apply    # 写库
"""

from __future__ import annotations

import argparse
import collections

# 25 个不含同名地级市的省级回退值（吉林/海南双关、四直辖市不在集内）
PROV_TARGET = frozenset(
    {
        "河北",
        "山西",
        "辽宁",
        "黑龙江",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "四川",
        "贵州",
        "云南",
        "陕西",
        "甘肃",
        "青海",
        "内蒙古",
        "广西",
        "西藏",
        "宁夏",
        "新疆",
    }
)

# 省名头 → 省会（「省名+馆」体例的名单行，物理位置即省会）
PROV_CAPITAL = {
    "河北": "石家庄",
    "山西": "太原",
    "辽宁": "沈阳",
    "黑龙江": "哈尔滨",
    "江苏": "南京",
    "浙江": "杭州",
    "安徽": "合肥",
    "福建": "福州",
    "江西": "南昌",
    "山东": "济南",
    "河南": "郑州",
    "湖北": "武汉",
    "湖南": "长沙",
    "广东": "广州",
    "四川": "成都",
    "贵州": "贵阳",
    "云南": "昆明",
    "陕西": "西安",
    "甘肃": "兰州",
    "青海": "西宁",
    "内蒙古": "呼和浩特",
    "广西": "南宁",
    "西藏": "拉萨",
    "宁夏": "银川",
    "新疆": "乌鲁木齐",
}

# 名字级例外（解析不到 / 会馆名不在省会）：知名馆藏地人工拍定
NAME_OVERRIDES: dict[str, str] = {
    "乾陵博物馆": "咸阳",  # 咸阳乾县
    "中国文字博物馆": "安阳",  # 河南安阳
    "澄江化石地世界自然遗产博物馆": "玉溪",  # 玉溪澄江
}


def resolve_museum_city(name_zh: str) -> str | None:
    from app.services.poi_city import canonical_city, city_from_name, resolve_city

    for key, city in NAME_OVERRIDES.items():
        if key in (name_zh or ""):
            return city
    hit = resolve_city(None, name_zh) or city_from_name(name_zh)
    if hit and hit not in PROV_TARGET:  # 解析出省名视同未命中，保守不动
        return hit
    # 「省名+馆」体例：物理位置即省会（山东博物馆/新疆维吾尔自治区博物馆…）
    head = (name_zh or "").strip()
    for prov in sorted(PROV_TARGET, key=len, reverse=True):
        if head.startswith(prov):
            return canonical_city(PROV_CAPITAL[prov])
    return None


def select_prov_rows() -> list:
    from app.db import get_session_factory
    from app.models import Poi

    fac = get_session_factory()
    with fac() as session:
        rows = session.query(Poi).filter(Poi.status == "active").all()
    return [r for r in rows if (r.city or "") in PROV_TARGET]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    apply_flag = ap.parse_args().apply

    rows = select_prov_rows()
    plan: list[tuple[int, str, str, str]] = []  # (id, old, new, name)
    for r in rows:
        canon = resolve_museum_city(r.name_zh or "")
        if canon and canon != r.city:
            plan.append((r.id, r.city, canon, r.name_zh or ""))

    dist = collections.Counter(new for _, _, new, _ in plan)
    print(
        f"扫描省级回退行={len(rows)}  可解析={len(plan)}  "
        f"未解析={len(rows) - len(plan)}"
    )
    for city, n in dist.most_common(15):
        print(f"    {city}: {n}")
    for _id, old, new, name in plan[:12]:
        print(f"    {old} -> {new} | {name[:24]}")
    unresolved = [
        (r.city, r.name_zh or "?")
        for r in rows
        if resolve_museum_city(r.name_zh or "") in (None, r.city)
    ]
    print("    未解析样例（名头无城市信号，留人工）:")
    for prov, name in unresolved[:15]:
        print(f"    [{prov}] {name[:32]}")
    if not plan:
        print("no hits (empty plan)")
        return 0
    if not apply_flag:
        print("dry-run only — rerun with --apply to write")
        return 0

    from app.db import get_session_factory
    from app.models import Poi

    fac = get_session_factory()
    plan_ids = [p[0] for p in plan]
    new_by_id = {p[0]: p[2] for p in plan}
    with fac() as session:
        for row in session.query(Poi).filter(Poi.id.in_(plan_ids)):
            row.city = new_by_id.get(row.id, row.city)
        session.commit()
    print(f"applied: {len(plan)} rows updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
