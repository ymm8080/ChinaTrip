# -*- coding: utf-8 -*-
"""雨天对调逐级兜底（2026-10-30 深夜 day5 武陵山大裂谷事故）。

线上会话 c2e752e3（上海→成都→重庆→上海 7 天，start 10-30）：重庆窗
day4-6，唯一干日 day4 恰是到达日（转场预算 360-180=180min）——
武陵山大裂谷（露天 180min）单点对调必败（150-90+180=240>180），旧
实现对调失败即静默保留、假设区无披露：用户看到「说好有雨自动排室
内，第 5 天还是露天峡谷」。本组锁：
②整组腾挪——干日室内点搬来雨日给露天点让位（两侧预算+个数闸）；
③雨日就地改排未入选室内点（露天点=删景点路径，点名披露）；
④无可替代保留但留痕（不再静默）；大雨/暴雨按雨强分级升级为
「雨日不排」移出行程（2026-10-31 拍板，强雨日绝不排露天）。
（①全对遍历单点对调为顺带加固：两物品预算恒等式下首对成败必与
次对一致，构造不出独立断言场景，不单测。）

测试口径：suggested_duration_min 直通上料（2026-10-31 拆除 180 钳
制闸）、日预算含 _leg_min 步行腿分钟——用共址点（腿=0）+ 小时长
精确控制预算，先手算初始落位再断言兜底动作；软余量周专门不共址，
锁「腿噪声级超额不再卡死对调」；回填周锁「露天补位干日优先」
与「只余雨日时点名披露」。
"""

from app.services.agent.plan import PlanningAgent, _rain_heavy


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
        "武陵山大裂谷" in n and "第4天" in n and "大足石刻博物馆" in n for n in notes
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
    assert any("武陵山大裂谷" in n and "移到第4天" in n for n in notes)
    assert not any("武陵山大裂谷" in n and "本轮不排" in n for n in notes)
    # 雨日6：干日已无室内点 → 四面山/神龙峡保留但留痕
    assert day_of["四面山"] == 6 and day_of["神龙峡"] == 6
    assert any("四面山" in n and "保持原排" in n for n in notes)


def test_refill_prefers_dry_day_for_outdoor():
    # 回填层雨天感知：露天补位点干日优先——即便雨日更近（腿 0）也去
    # 干日。池 cap=span*4=8：甲乙丙(室内60)聚北→day1(雨)180/3；
    # 丁戊己(露天60)聚南→day2(干)180/3；庚辛(180)两天都装不下→池内
    # 出局；壬峰(露天60)在北锚点旁（day1 腿 0）但属池外第 9 位→回填。
    # 旧序 (腿,负载,日) 会落 day1（雨、腿 0）；新序雨 flag 前置→day2
    cands = [
        _cand("甲馆", "成都", "yes", lat=31.5, dur=60),
        _cand("乙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丁峰", "成都", "no", lat=31.2, dur=60),
        _cand("戊岭", "成都", "no", lat=31.2, dur=60),
        _cand("己山", "成都", "no", lat=31.2, dur=60),
        _cand("庚岭", "成都", "no", lat=30.9, dur=180),
        _cand("辛峰", "成都", "no", lat=30.9, dur=180),
        _cand("壬峰", "成都", "no", lat=31.5, dur=60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 干日装得下（180+60+打车腿104≤360；2026-10-31 打车模型改轨）
    assert day_of["壬峰"] == 2
    assert not any("壬峰" in n for n in notes)


def test_refill_skips_outdoor_when_only_rainy_days_have_room():
    # 只余雨日有位（干日 4 个/日闸满）→ 露天补位**不排**（2026-10-31
    # 用户拍板：整段有雨也不把露天塞进已有安排的雨日，让位室内；5A
    # 级未排由白名单「可选加」披露）。旧版语义为「排入雨日+留痕」，
    # 线上案=start 11-02 会话 day6(11-07 小雨)金佛山-神龙峡补位排入。
    cands = [
        _cand("甲馆", "成都", "yes", lat=31.5, dur=60),
        _cand("乙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丁峰", "成都", "no", lat=30.5, dur=60),
        _cand("戊岭", "成都", "no", lat=30.5, dur=60),
        _cand("己山", "成都", "no", lat=30.5, dur=60),
        _cand("庚岭", "成都", "no", lat=30.5, dur=180),
        _cand("辛峰", "成都", "no", lat=30.9, dur=180),
        _cand("壬峰", "成都", "no", lat=31.5, dur=60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # day2（干）被丁戊己+庚填满 4 个闸 → 壬峰（露天）雨日不补：
    # 不排 + 点名留痕（白名单 max_missing=3 会截断，披露不依赖它）
    assert "壬峰" not in day_of
    assert any("壬峰" in n and "逢雨暂不排入" in n for n in notes)
    # 既有安排不受影响
    assert day_of["甲馆"] == 1 and day_of["庚岭"] == 2


def test_partial_treated_as_outdoor_in_refill():
    # 用户拍板（2026-10-31 选项2）：partial（半露天，如动物园）视同露天
    # 参与雨天避险——回填只余雨日时不排，点名标「半露天」
    cands = [
        _cand("甲馆", "成都", "yes", lat=31.5, dur=60),
        _cand("乙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丙馆", "成都", "yes", lat=31.5, dur=60),
        _cand("丁峰", "成都", "no", lat=30.5, dur=60),
        _cand("戊岭", "成都", "no", lat=30.5, dur=60),
        _cand("己山", "成都", "no", lat=30.5, dur=60),
        _cand("庚岭", "成都", "no", lat=30.5, dur=180),
        _cand("辛峰", "成都", "no", lat=30.9, dur=180),
        _cand("壬峰", "成都", "partial", lat=31.5, dur=60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert "壬峰" not in day_of
    assert any("壬峰" in n and "半露天" in n and "逢雨暂不排入" in n for n in notes)


def test_partial_rescued_by_ladder_with_label():
    # 梯子层同口径：partial 点在雨日被救援，④留痕标「半露天」。
    # 布局同软余量测：day4=转场日(预算180)=[博物馆90,影院60]，
    # day5=[裂谷180]，day6=[四面山120,神龙峡180(partial)]
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("大足石刻数字影院", "重庆", "yes", lat=29.71, dur=60),
        _cand("武陵山大裂谷", "重庆", "no", lat=29.50, dur=180),
        _cand("四面山", "重庆", "no", lat=28.90, dur=120),
        _cand("神龙峡", "重庆", "partial", lat=28.91, dur=180),
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
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["四面山"] == 6 and day_of["神龙峡"] == 6
    # partial 神龙峡进梯子：④留痕且标签=半露天（旧口径下它是中性的、
    # 零留痕）
    assert any("神龙峡" in n and "半露天" in n and "保持原排" in n for n in notes)


def test_heavy_rain_upgrades_no_alternative_to_removal():
    # 雨强分级（2026-10-31 用户拍板）：④无可替代在大雨/暴雨日升级为
    # 「也不排」——移出行程+点名「雨日不排」（5A/UNESCO 由白名单
    # 「可选加」自然披露，回填层还会替它在干日找位）；小雨日救援路径
    # 不受强度影响照常走
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
        heavy_rain_days={"重庆": {6}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # day5 小雨：②整组腾挪照常（强度只改④，不动①②③）
    assert day_of["武陵山大裂谷"] == 4
    # day6 大雨：无可替代 → 移出行程，且回填层也不回排（无干日可去）
    assert "四面山" not in day_of
    assert "神龙峡" not in day_of
    assert set(day_of) == {"大足石刻博物馆", "大足石刻数字影院", "武陵山大裂谷"}
    assert any("四面山" in n and "雨日不排" in n for n in notes)
    assert any("神龙峡" in n and "雨日不排" in n for n in notes)


def test_moderate_rain_keeps_no_alternative_in_place():
    # 分级另一侧：暴雨日(day5)救援成功不受强度影响；中雨日(day6)④
    # 维持「保持原排」——只有强降雨才删点
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
        heavy_rain_days={"重庆": {5}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["四面山"] == 6 and day_of["神龙峡"] == 6
    assert any("四面山" in n and "保持原排" in n for n in notes)
    assert not any("雨日不排" in n for n in notes)


def test_rain_heavy_text_boundary():
    # 强降雨口径：大雨/暴雨（含大暴雨/特大暴雨/转雨）命中；小雨/中雨/
    # 雷阵雨/阵雨/冻雨/非雨不命中
    assert _rain_heavy("大雨")
    assert _rain_heavy("暴雨")
    assert _rain_heavy("大暴雨")
    assert _rain_heavy("特大暴雨")
    assert _rain_heavy("大雨转暴雨")
    assert not _rain_heavy("小雨")
    assert not _rain_heavy("中雨")
    assert not _rain_heavy("雷阵雨")
    assert not _rain_heavy("阵雨")
    assert not _rain_heavy("冻雨")
    assert not _rain_heavy("晴")
    assert not _rain_heavy("")
    assert not _rain_heavy(None)
