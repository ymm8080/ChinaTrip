# -*- coding: utf-8 -*-
"""返程日 CityWalk 保底回归（2026-11-05 重庆案：day7 只有 17:00 返程航班）。

事故形态：沪-蓉-渝-沪 7 天（city_days={成都:2,重庆:4,上海:1}），重庆窗
day3-7 同时含到达日 day3 与返程日 day7。13 张远郊王牌（unesco/5A，
100-330km）占满池首；市区名点（磁器口街区 tier8 / 十八梯）曾因 rating
缺失被切池外。离城日上午闸（solver `_leaving_morning_cap`：条目 end ≤
min(12:00, 发车−90)）使远郊大块头物理排不进 day7 → 空天保底盲挪池尾
远点 → 全被清算移除 → day7 只剩航班（用户：飞机五点的，为什么不安排）。

回归锚：
1. 返程日必须落得进市区轻点（CityWalk，≤180min、非远郊）；
2. 远郊大块头不得被选进返程日（上午闸窗口内排不下）。
数据口径取 2026-11-05 DB 实测（01aa3d2 评分回填后）。
"""

from __future__ import annotations

from app.services.agent.plan import PlanningAgent

_CQ = (106.578, 29.560)  # 渝中解放碑（市区簇）
_CQ_N = (106.454, 29.577)  # 沙坪坝磁器口（市区簇）

# 远郊王牌真实坐标（公里级离城）：大足/武隆/金佛山/四面山/白帝城…
_FAR = [
    (105.720, 29.700),  # 大足石刻 ~100km
    (107.760, 29.350),  # 武隆 ~120km
    (107.190, 29.010),  # 金佛山（南川）~110km
    (106.350, 28.890),  # 四面山（江津）~140km
    (109.570, 31.040),  # 白帝城（奉节）~330km
    (108.690, 30.770),  # 小三峡（巫山）~400km
    (108.530, 30.430),  # 龙缸（云阳）~300km
    (107.220, 30.120),  # 濯水/阿依河方向 ~250km
    (106.650, 29.230),  # 黑山谷（万盛）~110km
    (107.090, 29.180),  # 桃花源（酉阳）~280km
    (106.240, 29.820),  # 大裂谷（涪陵）~90km
    (108.120, 29.530),  # 神龙峡/彭水 ~180km
]

_FAR_NAMES = [f"远郊五A{i}" for i in range(len(_FAR))]


def _cand(
    name,
    city,
    *,
    cat="attraction",
    minutes=None,
    tags=None,
    loc=None,
    rating=None,
    count=None,
    source=None,
):
    c = {"name": name, "city": city, "category": cat, "location": loc}
    if minutes is not None:
        c["suggested_duration_min"] = minutes
    if tags is not None:
        c["tags"] = tags
    if rating is not None:
        c["rating"] = rating
    if count is not None:
        c["rating_count"] = count
    if source is not None:
        c["source"] = source
    return c


def _chongqing_shape():
    """沪-蓉-渝-沪 7 天的重庆候选形态（11-05 DB 实测口径）。"""
    cands = [
        _cand(
            "大足石刻",
            "重庆",
            cat="sight",
            minutes=300,
            tags=["unesco"],
            loc=_FAR[0],
            rating=4.7,
            count=80000,
        ),
    ]
    for name, (lon, lat) in zip(_FAR_NAMES, _FAR[1:]):
        cands.append(
            _cand(
                name,
                "重庆",
                minutes=240,
                tags=["5a"],
                loc=(lon, lat),
                rating=4.7,
                count=50000,
            )
        )
    # 市区名点（01aa3d2 评分回填后的真实字段）
    cands += [
        _cand(
            "洪崖洞",
            "重庆",
            cat="ancient_town",
            minutes=180,
            tags=["ta", "lp", "intl"],
            loc=_CQ,
            rating=4.7,
            count=100000,
        ),
        _cand(
            "磁器口街区",
            "重庆",
            cat="historic",
            minutes=90,
            tags=["国家级旅游休闲街区"],
            loc=_CQ_N,
            rating=4.4,
            count=90000,
        ),
        _cand("十八梯", "重庆", cat="", minutes=120, tags=[], loc=_CQ, rating=4.5),
        _cand(
            "李子坝轻轨站",
            "重庆",
            cat="transport",
            minutes=60,
            tags=["curated", "intl"],
            loc=_CQ,
            rating=4.5,
            count=393,
        ),
    ]
    # 成都窗 day1-2（非本测重点，给足背景）
    cands += [
        _cand(
            "熊猫基地",
            "成都",
            cat="zoo",
            minutes=180,
            loc=(104.144, 30.733),
            rating=4.6,
            count=90000,
        ),
        _cand(
            "宽窄巷子",
            "成都",
            minutes=90,
            tags=["街区"],
            loc=(104.053, 30.667),
            rating=4.5,
            count=60000,
        ),
    ]
    return cands


def test_return_day_gets_citywalk_not_far_poi():
    picked = PlanningAgent._deterministic_selection(
        _chongqing_shape(),
        7,
        {"成都": (1, 2), "重庆": (3, 7), "上海": (7, 7)},
        transfer_days={1, 3, 7},
        arrival_days={1, 3},
    )
    by_day: dict[int, list[dict]] = {}
    for it in picked:
        by_day.setdefault(it["day"], []).append(it)

    # 返程日必须有参访（不能只剩返程腿）
    assert by_day.get(7), "返程日(day7)零参访——重庆案回归"

    # 返程日条目必须是市区轻点：上午闸窗口（end ≤ 12:00）内排得下
    far = {n for n in _FAR_NAMES} | {"大足石刻"}
    for it in by_day[7]:
        assert it["name"] not in far, (
            f"远郊大块头「{it['name']}」被选进返程日——上午闸窗口内物理排不下"
        )
    assert any(
        it["name"] in {"磁器口街区", "十八梯", "洪崖洞", "李子坝轻轨站"}
        for it in by_day[7]
    ), f"返程日没落任何市区 CityWalk 点：{[it['name'] for it in by_day[7]]}"
