# -*- coding: utf-8 -*-
"""雨天对调逐级兜底（2026-10-30 深夜 day5 武陵山大裂谷事故）。

线上会话 c2e752e3（上海→成都→重庆→上海 7 天，start 10-30）：重庆窗
day4-6，唯一干日 day4 恰是到达日（转场预算 360-180=180min）——
武陵山大裂谷（露天 180min）单点对调必败（150-90+180=240>180），旧
实现对调失败即静默保留、假设区无披露：用户看到「说好有雨自动排室
内，第 5 天还是露天峡谷」。本组锁：
②整组腾挪——干日室内点搬来雨日给露天点让位（两侧预算+个数闸）；
③雨日就地改排未入选室内点（露天点=删景点路径，点名披露）；
④无可替代保留但留痕（不再静默）。
（①全对遍历单点对调为顺带加固：两物品预算恒等式下首对成败必与
次对一致，构造不出独立断言场景，不单测。）

测试口径：suggested_duration_min 被 _clamp_plan_duration 封顶 180、
日预算含 _leg_min 步行腿分钟——用共址点（腿=0）+ ≤180 时长精确
控制预算，先手算初始落位再断言兜底动作；软余量周专门不共址，
锁「腿噪声级超额不再卡死对调」。
"""

from app.services.agent.plan import PlanningAgent


def _cand(name, city, rain_ok, *, lon=104.0, lat=30.6, source="08", dur=60):
    return {
        "name": name,
        "city": city,
        "category": "sight",
        "source": source,
        "rain_ok": rain_ok,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }


def test_multi_exchange_rescues_rainy_day_blocked_by_transfer_budget():
    # 复刻线上：干日=到达日预算 180min；雨日5 的露天 180min 点单点
    # 对调必败 → 腾挪：干日两个室内点（90+60）整组搬来雨日，露天
    # 点移去干日。共址控制腿分钟=0。初始落位（cluster 最远点种子
    # 确定性）：day4=[博物馆90,影院60]=150/180，day5=[大裂谷180]，
    # day6=[四面山120,神龙峡180]=300/360
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("大足石刻数字影院", "重庆", "yes", lat=29.70, dur=60),
        _cand("武陵山大裂谷", "重庆", "no", lat=29.50, dur=180),
        _cand("四面山", "重庆", "no", lat=28.90, dur=120),
        _cand("神龙峡", "重庆", "no", lat=28.90, dur=180),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands,
        6,
        {"重庆": (4, 6)},
        transfer_days={4},
        rain_days={"重庆": {5, 6}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 雨日5：多点腾挪生效——露天点去干日、室内点整组来雨日
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["大足石刻博物馆"] == 5
    assert day_of["大足石刻数字影院"] == 5
    assert any(
        "武陵山大裂谷" in n and "第4天" in n and "大足石刻博物馆" in n
        for n in notes
    )
    # 雨日6：干日已无室内点也无余位 → 四面山/神龙峡保留但留痕
    assert day_of["四面山"] == 6 and day_of["神龙峡"] == 6
    assert any("四面山" in n and "保持原排" in n for n in notes)
    assert any("神龙峡" in n and "保持原排" in n for n in notes)


def test_rainy_day_replaces_outdoor_with_unplaced_indoor_disclosed():
    # 雨日就地改排：干日室内点(90)换出后干日仍装不下露天点(180)时
    # （干日已载 330），未入选室内点 1:1 顶上；露天点点名披露（删
    # 景点路径须可见）。全共址（单簇，day1 贪心装满→溢出 day2）：
    # 初始 day1=[甲山180,乙山180]=360，day2=[丙馆90,丁峰180,戊岭60]
    # =330；己馆(90) 两日都装不下 → 未入选
    cands = [
        _cand("甲山", "成都", "no", dur=180),
        _cand("乙山", "成都", "no", dur=180),
        _cand("丙馆", "成都", "yes", dur=90),
        _cand("丁峰", "成都", "no", dur=180),
        _cand("戊岭", "成都", "no", dur=60),
        _cand("己馆", "成都", "yes", dur=90),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 雨日1：甲山——①丙馆换出后干日 330-90+180=420>360 败、②同败
    # → ③己馆顶上（披露「本轮不排」）；乙山随后无可换 → ④保留留痕
    assert "甲山" not in day_of
    assert day_of["己馆"] == 1
    assert day_of["乙山"] == 1
    assert day_of["丙馆"] == 2
    assert any("甲山" in n and "本轮不排" in n for n in notes)
    assert any("乙山" in n and "保持原排" in n for n in notes)


def test_slack_tolerates_leg_noise_when_transfer_budget_tight():
    # 软余量（用户拍板「差18分钟没有关系」）：线上实例复刻——干日
    # =到达日预算 180，两个室内点隔 0.01°≈1.1km（腿 18min 进日载荷
    # 168），露天点 180min 整组腾挪 168-150+180=198>180：无余量时差
    # 的恰是这 18 分钟腿噪声 → 被迫「点名不排」；有余量后走「移去
    # 干日保留」。初始落位：day4=[博物馆90,影院60]=168/180，
    # day5=[大裂谷180]，day6=[四面山120,神龙峡180]
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("大足石刻数字影院", "重庆", "yes", lat=29.71, dur=60),
        _cand("武陵山大裂谷", "重庆", "no", lat=29.50, dur=180),
        _cand("四面山", "重庆", "no", lat=28.90, dur=120),
        _cand("神龙峡", "重庆", "no", lat=28.91, dur=180),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands,
        6,
        {"重庆": (4, 6)},
        transfer_days={4},
        rain_days={"重庆": {5, 6}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 雨日5：腾挪在 +30min 软余量内放行——露天点去干日、室内整组
    # 来雨日（198 ≤ 180+30）
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["大足石刻博物馆"] == 5
    assert day_of["大足石刻数字影院"] == 5
    assert any(
        "武陵山大裂谷" in n and "移到第4天" in n for n in notes
    )
    assert not any("武陵山大裂谷" in n and "本轮不排" in n for n in notes)
    # 雨日6：干日已无室内点 → 四面山/神龙峡保留但留痕
    assert day_of["四面山"] == 6 and day_of["神龙峡"] == 6
    assert any("四面山" in n and "保持原排" in n for n in notes)
