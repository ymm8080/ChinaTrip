# -*- coding: utf-8 -*-
"""雨天语义测试（2026-11-02 拍板链后整体更新）。

拍板链：2026-10-30「有雨自动排室内」→ 2026-10-31 雨强分级/回填
雨闸 → 2026-11-02「时间约束是软闸；被闸时同档选时间短的」+
**「雨日是硬闸」**——露天/半露天点绝不落雨日：主环目标天逢雨→
必投有计数空位的干日（预算软闸照放），无干日空位=出局（回填层
重试+「逢雨暂不排入」点名）；救援梯④无可替代=任何强度移出
（大雨/中雨仅措辞分级）；雨夜换不动同移出。防优于治后①对调/
②腾挪经普通选点不可达，由 must 合并/编辑重排路径承接（待补）。

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


def test_outdoor_redirects_to_sole_dry_day_soft_overflow():
    # 2026-11-02 预占位链后形态：物理受限先认领（乙山案）——仅干日
    # 可投的三个露天点先占唯一干日 day4（4 闸占 3，软闸超额照放）；
    # 宽窗室内馆失去干日档后落雨日5（室内不受雨闸），神龙峡保住
    # 干日位——露天绝不落雨日、无出局无披露。
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("重庆科技馆", "重庆", "yes", lat=29.70, dur=60),
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
    # 露天点全部硬闸避让到唯一干日（软闸超额）
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["四面山"] == 4
    assert day_of["神龙峡"] == 4
    # 宽窗室内馆退雨日5（室内不受雨闸，无出局无披露）
    assert day_of["大足石刻博物馆"] == 5 and day_of["重庆科技馆"] == 5
    assert not any(("逢雨" in n or "不排" in n) for n in notes)


def test_outdoor_moves_to_dry_day_no_removal_needed():
    # 2026-11-02 软闸+雨日硬闸后形态：雨日1 的露天山点全部避让到
    # 干日2（软闸超额，4 闸内），室内馆留在雨日——无删点、无披露，
    # 露天不进雨日即无需救援。
    # 坐标彼此按 lon 错开 >1.5km（同点互认并卡会把室内馆并进露天锚卡，
    # 验不出「室内不受雨闸独立留雨日」；族卡已废 10bd56b，贴邻同日圈
    # 11-07 晚扩 5km——0.02°≈1.9km 在圈内，同日软偏好与雨闸同向）。
    cands = [
        _cand("甲山", "成都", "no", lon=104.0, dur=180),
        _cand("乙山", "成都", "no", lon=104.02, dur=180),
        _cand("丙馆", "成都", "yes", lon=104.04, dur=90),
        _cand("丁峰", "成都", "no", lon=104.06, dur=180),
        _cand("戊岭", "成都", "no", lon=104.08, dur=60),
        _cand("己馆", "成都", "yes", lon=104.1, dur=90),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["甲山"] == 2 and day_of["乙山"] == 2
    assert day_of["丁峰"] == 2 and day_of["戊岭"] == 2
    assert day_of["丙馆"] == 1 and day_of["己馆"] == 1
    # 露天已避让成功：不再有逢雨/移出类披露
    assert not any(("逢雨" in n or "不排" in n) for n in notes)


def test_leg_noise_does_not_change_hard_gate_shape():
    # 软闸拍板后预算精度不再决定出局（软余量概念随硬闸退役）；
    # 本测保留 0.01° 腿噪声形态回归——腿分钟进载荷不改变雨日硬闸
    # 的落位形态（与 test_outdoor_redirects_to_sole_dry_day 同构）。
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("重庆科技馆", "重庆", "yes", lat=29.71, dur=60),
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
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["四面山"] == 4
    assert day_of["神龙峡"] == 4
    # 宽窗室内馆退雨日5（腿噪声不改硬闸落位形态，与上测同构）
    assert day_of["大足石刻博物馆"] == 5 and day_of["重庆科技馆"] == 5
    assert not any(("逢雨" in n or "不排" in n) for n in notes)


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


def test_tail_outdoor_redirects_and_full_dry_drops():
    # 2026-11-02 语义：壬峰（露天短点，「同档短者优先」使其入主环）
    # 硬闸避让到干日2（软闸超额照放）；庚岭轮到它时干日已 4 闸满、
    # 雨日预算也装不下 → 出局（计数裁减同语义，5A/UNESCO 才有白名
    # 单披露）；池外尾巴辛峰不享软闸不排。
    # 组内坐标按 lon 错开 >1.5km（同点互认并卡会让露天族整族搭车进
    # 干日、庚岭不再 4 闸满出局；本测意图依赖 4/日闸封顶。族卡已废，
    # 贴邻同日圈 5km——1.9km 在圈内，同日软偏好与 4/日闸同向）。
    # 北族纬度 30.68（城心 ~12km 中性带，2026-11-13 日间混排闸口径）：
    # 旧夹具 31.5=城心 103km 远郊件——混排闸把露天壬峰锁死在北族日，
    # 雨日避让语义被分区闸遮蔽（2026-11-14 夹具修正，同
    # test_rain_unmarked_sites 口径）。
    cands = [
        _cand("甲馆", "成都", "yes", lon=104.0, lat=30.68, dur=60),
        _cand("乙馆", "成都", "yes", lon=104.02, lat=30.68, dur=60),
        _cand("丙馆", "成都", "yes", lon=104.04, lat=30.68, dur=60),
        _cand("丁峰", "成都", "no", lon=104.0, lat=30.5, dur=60),
        _cand("戊岭", "成都", "no", lon=104.02, lat=30.5, dur=60),
        _cand("己山", "成都", "no", lon=104.04, lat=30.5, dur=60),
        _cand("庚岭", "成都", "no", lon=104.06, lat=30.5, dur=180),
        _cand("辛峰", "成都", "no", lat=30.9, dur=180),
        _cand("壬峰", "成都", "no", lon=104.06, lat=30.68, dur=60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["壬峰"] == 2  # 露天避让到干日（软闸超额）
    assert "庚岭" not in day_of  # 干日 4 闸满 → 出局不落雨日
    assert "辛峰" not in day_of  # 池外尾巴不享软闸
    assert day_of["甲馆"] == 1


def test_partial_light_rain_only_with_hint():
    # 半露天（partial）雨天口径（2026-11-02 拍板「小雨可以排。没说
    # 中雨」）：中雨日（无 light 图）=拦、避让干日；小雨日（light
    # 图）=照排+「建议备伞」提示；全露天庚岭无论哪种雨都不进雨日。
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
    # 中雨：拦 → 避让干日2，无提示
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["壬峰"] == 2
    assert not any("壬峰" in n for n in notes)
    # 小雨：照排 + 提示
    notes2: list[str] = []
    picked2 = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"成都": (1, 2)},
        rain_days={"成都": {1}},
        light_rain_days={"成都": {1}},
        notes=notes2,
    )
    day_of2 = {p["name"]: p["day"] for p in picked2}
    assert day_of2["壬峰"] == 1
    assert any("壬峰" in n and "小雨照排" in n and "建议备伞" in n for n in notes2)


def test_partial_light_rain_day_stays_with_hint():
    # 复合形态：影院让位博物馆（同站闸）；全露天（四面山/裂谷）硬闸
    # 避让到唯一干日 day4（软闸超额）；宽窗博物馆先占小雨日5（室内
    # 不受雨闸），神龙峡(partial)落另一小雨日6 照排+「建议备伞」
    # 提示（2026-11-02 拍板）——半露天可落雨日的唯一形态（池外
    # 切片修复前此处曾出假披露，2026-11-02 已修）。
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
        light_rain_days={"重庆": {5, 6}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["武陵山大裂谷"] == 4
    assert day_of["四面山"] == 4
    assert day_of["大足石刻博物馆"] == 5
    # 神龙峡(partial)：另一小雨日(6)照排+提示
    assert day_of["神龙峡"] == 6
    assert any("神龙峡" in n and "小雨照排" in n and "建议备伞" in n for n in notes)
    assert any("大足石刻数字影院" in n and "大足石刻博物馆" in n for n in notes)
    assert "大足石刻数字影院" not in day_of
    assert not any(("逢雨" in n or "雨日不排" in n) for n in notes)


def test_whole_window_rain_hard_gates_all_outdoor():
    # 雨日硬闸（2026-11-02 拍板）全窗形态：无干日可避让 → 露天点
    # 全部出局+「逢雨暂不排入」点名（大雨日同理，强度不再分级——
    # 防优于治）；室内点照排雨日（室内不受硬闸限制）。
    cands = [
        _cand("大足石刻博物馆", "重庆", "yes", lat=29.70, dur=90),
        _cand("重庆科技馆", "重庆", "yes", lat=29.70, dur=60),
        _cand("武陵山大裂谷", "重庆", "no", lat=29.50, dur=180),
        _cand("四面山", "重庆", "no", lat=28.90, dur=120),
        _cand("神龙峡", "重庆", "no", lat=28.90, dur=180),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands,
        6,
        {"重庆": (4, 6)},
        rain_days={"重庆": {4, 5, 6}},
        heavy_rain_days={"重庆": {6}},
        notes=notes,
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert set(day_of) == {"大足石刻博物馆", "重庆科技馆"}
    assert day_of["大足石刻博物馆"] == 4 and day_of["重庆科技馆"] == 4
    # 露天点全部出局+点名（回填层也无干日可补）
    assert any("武陵山大裂谷" in n and "逢雨暂不排入" in n for n in notes)
    assert any("预报全段有雨" in n for n in notes)


def test_partial_window_heavy_day_redirects_when_dry_room():
    # 部分窗有雨+大雨日(day5)：唯一干日 day4 有计数空位 → 大雨日簇
    # 的露天点物理受限先认领占干日（软闸超额）；宽窗室内馆落雨日5，
    # 无一露天落雨日、无删点披露——防优于治，强度分级只在无可替
    # 代移出时影响措辞。
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
    assert day_of["四面山"] == 4 and day_of["神龙峡"] == 4
    assert day_of["大足石刻博物馆"] == 5
    assert "大足石刻数字影院" not in day_of
    assert not any(("逢雨" in n or "雨日不排" in n) for n in notes)


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


def test_rain_light_text_boundary():
    # 小雨口径（2026-11-02 拍板「半露天（partial）小雨可以排。没说
    # 中雨」）：仅含「小雨」且不含更强/其他雨种才命中——半露天只在
    # 小雨日放行（+提示），中雨及以上一律拦。
    from app.services.agent.plan import _rain_light

    assert _rain_light("小雨")
    assert _rain_light("阴转小雨")
    assert not _rain_light("小到中雨")
    assert not _rain_light("中雨")
    assert not _rain_light("阵雨")
    assert not _rain_light("雷阵雨")
    assert not _rain_light("冻雨")
    assert not _rain_light("大雨")
    assert not _rain_light("暴雨")
    assert not _rain_light("晴")
    assert not _rain_light("")
    assert not _rain_light(None)
