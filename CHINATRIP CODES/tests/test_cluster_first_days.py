# -*- coding: utf-8 -*-
"""簇优先选日通道（2026-11-08 用户拍板「距离聚类优先/组合排日」+深夜二/三轮）。

选层管线重排为：池定后、逐点认领前——池内可数件按 0<km≤1km
（_FAMILY_ATOMIC_KM，二拍①收紧；1.5-2km 链式弱边不得把原子族撑爆
4/日帽逼减员肢解核心组）连边聚族 → 按（族内最优 tier，-族时长合计
〔二拍③：更难排的先占日〕，-族规模）逐族找最早可行同城日整族原子
认领（4/日帽/边日规则全过；三轮②：腿不是游玩负载，可行性判定与
day_loads 账面一律剔腿；二拍②：全小件族每员≤120min且合计≤180min
可走到达日整族落位通道，返程日不开；三轮①：重要族 best-tier≤2 认领
净日预算 360→450，仅 2 员不可减员时 480 兜底留痕）→ 塞不进只减地理
链端点（二拍④逐项比：非钉>tier数字大>时长长，中间成员永不被减）→
族占日不收异簇可数件（food 豁免、演出钉日不受限）。本文件锚十一路
判据：①最重要成员的族优先占日；②整族原子落日；③减地理端点；
④零散景点进不了族占日；⑤餐厅可以；⑥1-2km 弱边不入原子族（钟/鼓/
城墙核心组不被 1.96km 弱边肢解）；⑦到达日轻量三人组剔腿落 d1；
⑧重要族净日 450min 预算豁免（雁塔 420min 形）。
⑨⑩⑪四轮锚（钟楼案）：认领/捆绑时刻同跑入场闸镜像——预算过闸≠
物理排得下，降序连排末件开场超入场闸即拦在进日前（⑨纯算术；
⑩伞名捆绑 keeper 日物理满则不拉同日；⑪四员 450min 族账面可落
但物理不可排→减地理端点+披露，替代终排无声挤死）。
⑫先保 tier 高弹让锚：王牌族（best tier≤2）全窗容量型被拒时，把
目标日已落地件与入件并一组观察，按「重要度小、重复度高」减员腾位
——弱族整体弹出（伞名票制对联同进退、族形 ≥2 或清零），王牌族
整族原子补进，弹出件回散件通道+双语披露。
"""

from __future__ import annotations

from app.services.agent.plan import (
    PlanningAgent,
    _bundle_umbrella_spec_days,
    _cand_entry_cap,
    _entry_cap_feasible,
)


def _c(
    name: str,
    loc: tuple[float, float],
    *,
    tier: int | None = None,
    dur: int = 60,
    cat: str = "attraction",
    city: str = "成都",
):
    c: dict = {
        "name": name,
        "city": city,
        "category": cat,
        "suggested_duration_min": dur,
        "location": loc,
    }
    if tier == 1:
        c["tags"] = ["unesco"]
        c["source"] = "unesco"
    elif tier == 2:
        c["tags"] = ["5a"]
        c["source"] = "5a"
    return c


# 布点（lat 30.66 下 1° lon ≈ 95.8km、1° lat ≈ 111km）：族内错开
# ~0.5-0.9km（≤1km 原子连边），两族相距 ~40km（互不连边、互为异簇）。
_A0 = (104.060, 30.66)
_A1 = (104.065, 30.66)  # ↔A0 ~0.48km
_A2 = (104.070, 30.66)  # ↔A1 ~0.48km
_B0 = (104.500, 30.66)
_B1 = (104.505, 30.66)
_B2 = (104.510, 30.66)


def _by_day(items: list[dict]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for it in items:
        out.setdefault(it["day"], set()).add(it["name"])
    return out


def test_best_member_family_claims_earliest_day_first():
    """①族优先占日按族内最优成员排序：含 unesco（tier1）的族先认领最早
    可行日——若按池序/规模先处理普通族，普通族会抢走 day1。"""
    cands = [
        _c("族甲员一", _A0, tier=1),
        _c("族甲员二", _A1),
        _c("族甲员三", _A2),
        _c("族乙员一", _B0),
        _c("族乙员二", _B1),
        _c("族乙员三", _B2),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = _by_day(items)
    # day1 只装得下一族（4/日帽下两族 6 件装不下）：tier1 族先到先得。
    assert by_day[1] == {"族甲员一", "族甲员二", "族甲员三"}
    assert by_day[2] == {"族乙员一", "族乙员二", "族乙员三"}


def test_family_lands_atomically_on_one_day():
    """②整族原子落同一天：4 员族链式布点（相邻 ≤1km），单日装得下时
    整族同日——不得再被容量梯子逐件拆散。"""
    cands = [
        _c("链员一", _A0),
        _c("链员二", _A1),
        _c("链员三", _A2),
        _c("链员四", (104.075, 30.66)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = _by_day(items)
    assert by_day[1] == {"链员一", "链员二", "链员三", "链员四"}


def test_overflow_family_reduces_geo_endpoint_not_middle():
    """③塞不进只减地理链端点：五员族链（端一 tier2 — 中枢 unesco —
    中二 — 中三 — 端二 tier11，相邻 0.86km）5 件 > 4/日帽全窗装不下
    ——减地理直径端点对（端一↔端二 ~3.4km）中更次要的端二（tier11 >
    端一的 5A）；中间成员（中枢/中二/中三，含族内最重要者）永不被减，
    减员退回零散池：day1 已 4/4 帽满，端二落 day2。"""
    cands = [
        _c("端一", (104.0600, 30.66), tier=2, dur=100),
        _c("中枢", (104.0690, 30.66), tier=1, dur=60),
        _c("中二", (104.0780, 30.66), dur=60),
        _c("中三", (104.0870, 30.66), dur=60),
        _c("端二", (104.0960, 30.66), dur=100),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, notes=notes
    )
    day_of = {it["name"]: it["day"] for it in items}
    # 减员后整族原子落 day1（4/4），中间成员一个不少
    assert day_of["中枢"] == day_of["中二"] == day_of["中三"] == day_of["端一"] == 1
    assert day_of["端二"] == 2  # 地理端点退回零散池，另日安排
    assert any("端二" in n for n in notes)  # 减员双语披露留痕


def test_zero_distance_family_reduces_global_weakest_member():
    """同针族没有地理端点，减员须在全部可减成员中选全局最弱件。"""
    far = (104.500, 30.66)
    cands = [
        _c("远一", far, tier=1),
        _c("远二", far, tier=2),
        _c("远三", far),
        _c("远四", far),
        _c("弱件", far, dur=180),
        *[_c(f"城件{i}", _A0 if i % 2 == 0 else _A1) for i in range(6)],
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, notes=notes
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert {day_of[n] for n in ("远一", "远二", "远三", "远四")} == {1}
    # 减员选择：零距族（全员同针）无地理端点——减的是全局最弱件（弱件
    # 180min 无档），不是地理端点上的任一件（留痕点名）。
    assert any("弱件" in n and "退回零散安排" in n for n in notes), (
        "零距族减员=全局最弱件"
    )
    # 2026-11-13 日间混排闸（6f48bf3）：弱件远郊（>25km）减员回散后，
    # day2/day3 已有城心件（混排禁）、day1 远郊族满员（4/日帽）——
    # 无合规日移出留痕（要加回请说），不再落城心日。
    assert "弱件" not in day_of
    assert any("弱件" in n and "未排入" in n for n in notes)


def test_unmarked_family_softly_prefers_dry_day():
    cands = [
        _c("未标员一", _A0),
        _c("未标员二", _A1),
        _c("未标员三", _A2),
    ]
    items = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"成都": (1, 2)},
        rain_days={"成都": {1}},
    )
    assert _by_day(items)[2] == {"未标员一", "未标员二", "未标员三"}


def test_known_indoor_family_prefers_rainy_day():
    cands = [
        _c("室内员一", _A0),
        _c("室内员二", _A1),
        _c("室内员三", _A2),
    ]
    for cand in cands:
        cand["rain_ok"] = "yes"
    items = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"成都": (1, 2)},
        rain_days={"成都": {2}},
    )
    assert _by_day(items)[2] == {"室内员一", "室内员二", "室内员三"}


def test_less_rain_tolerant_family_claims_dry_day_first():
    """雨日仲裁（用户拍板「选日期要考虑组合里景点是室内还是室外」补口）：
    两族争干日且可行日数相同时，含硬露天员（rain_ok=no，王牌仅小雨放行）
    的族先占位干日；耐雨/中性族殿后 absorb 雨日——王牌小雨放行只是
    「可以落」不是「该落」，不得凭 tier 序让硬露天族殿后接盘雨日。"""
    cands = [
        # 族甲：中性耐雨（王牌+未标注王牌+耐雨员，无 rain_ok=no 员）
        _c("甲王牌", _A0, tier=1),
        _c("甲未标", _A1, tier=2),
        _c("甲耐雨", _A2),
        # 族乙：含硬露天王牌（rain_ok=no 的 5a）——应占干日
        _c("乙露天", _B0, tier=2),
        _c("乙员二", _B1),
        _c("乙员三", _B2),
    ]
    cands[2]["rain_ok"] = "yes"
    cands[3]["rain_ok"] = "no"
    cands[4]["rain_ok"] = "yes"
    cands[5]["rain_ok"] = "yes"
    items = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"成都": (1, 2)},
        rain_days={"成都": {2}},
        light_rain_days={"成都": {2}},
    )
    by_day = _by_day(items)
    assert by_day[1] == {"乙露天", "乙员二", "乙员三"}
    assert by_day[2] == {"甲王牌", "甲未标", "甲耐雨"}


def test_locked_low_priority_card_cannot_evict_higher_priority_member():
    cands = [
        _c("高档长件", _A0, tier=1, dur=180),
        _c("族短一", _A1, dur=30),
        _c("族短二", _A2, dur=40),
        _c("族短三", (104.075, 30.66), dur=50),
    ]
    incoming = _c("低档雨锁", (104.240, 30.66), dur=60)
    cands.append(incoming)
    for cand in cands:
        cand["rain_ok"] = "no"
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"成都": (1, 2)},
        rain_days={"成都": {2}},
        notes=notes,
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["高档长件"] == 1
    assert "低档雨锁" not in day_of
    assert any("低档雨锁" in n and "无干日可排" in n for n in notes)


def test_full_day_shed_preserves_two_members_in_each_family():
    cands = [
        _c("甲族一", _A0, dur=30),
        _c("甲族二", _A1, dur=40),
        _c("乙族长件", _B0, dur=180),
        _c("乙族二", _B1, dur=50),
    ]
    incoming = _c("雨锁入件", (104.700, 30.66), tier=2, dur=60)
    cands.append(incoming)
    for cand in cands:
        cand["rain_ok"] = "no"
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands,
        3,
        {"成都": (1, 3)},
        rain_days={"成都": {2, 3}},
        notes=notes,
    )
    by_day = _by_day(items)
    # 2026-11-13 日间混排闸（6f48bf3）：乙族夹具距城心 42km（>25km 混排
    # 带）不落城心件（甲族 10km）已占的干日 day1；day2/3 雨日全拦——
    # 乙族长件无合规日出局留痕、乙族二露天交雨闸弃排披露（现行拍板口
    # 径）；甲族照旧整族同日。
    assert {"甲族一", "甲族二"} <= by_day[1]
    assert not any(n in by_day[1] for n in ("乙族长件", "乙族二"))
    assert "雨锁入件" not in {it["name"] for it in items}
    assert any("乙族长件" in n and "离城心太远" in n for n in notes)
    assert any("乙族二" in n and "无干日可排" in n for n in notes)


def test_tight_cluster_capacity_uses_original_insertion_charge():
    cands = [
        _c("首占远件", (104.000, 30.66), tier=1, dur=120),
        _c("近件一", (104.100, 30.66), tier=2, dur=80),
        _c("近件二", (104.112, 30.66), tier=2, dur=80),
        _c("近件三", (104.124, 30.66), tier=2, dur=80),
        _c("待合近件", (104.136, 30.66), dur=60),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, arrival_days={2, 3}
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["首占远件"] == 1
    assert {day_of[f"近件{x}"] for x in "一二三"} == {1}
    assert day_of["待合近件"] == 2


def test_transfer_empty_day_moves_selected_loose_card_not_cluster_tail():
    near = (104.505, 30.66)

    def _show(name, loc, *, tier=None, dur=60):
        cand = _c(name, loc, tier=tier, dur=dur, cat="entertainment")
        cand.update(best_visit_time="show", opening_hours="多场 10:00/14:00/19:30")
        return cand

    cands = [
        _c("近簇件一", near, dur=150),
        _show("近簇演出", near, dur=150),
        _c("近簇件二", near, dur=150),
        _c("待挪散件", (104.200, 30.66), tier=1, dur=150),
        _c("近簇尾件", near, dur=40, cat="museum"),
        _show("定场演出", (104.060, 30.66), tier=1, dur=40),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={3}
    )
    by_day = _by_day(items)
    assert by_day[3] == {"待挪散件"}
    assert "近簇尾件" in by_day[2]


def test_stranger_sight_cannot_claim_family_day():
    """④零散景点不得认领族占日：族甲整族占 day1（3/4 有余位），无族
    身份的远点（异簇）即使最早有容量也不得插进 day1——改投开放日
    day2（旧容量梯子会把它塞进 day1 第 4 席）。"""
    cands = [
        _c("族员一", _A0, tier=1),
        _c("族员二", _A1),
        _c("族员三", _A2),
        _c("零散远点", (104.90, 30.66), dur=90),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = _by_day(items)
    assert by_day[1] == {"族员一", "族员二", "族员三"}
    assert by_day[2] == {"零散远点"}


def test_food_can_share_family_day():
    """⑤近距离餐厅可以（food 豁免）：族甲整族占 day1，food 候选不受
    族占日闸——照常落 day1（餐饮锚点摊开语义不因族日受限）。"""
    cands = [
        _c("族员一", _A0, tier=1),
        _c("族员二", _A1),
        _c("族员三", _A2),
        _c("近邻餐厅", (104.062, 30.66), cat="food", dur=60),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = _by_day(items)
    assert by_day[1] == {"族员一", "族员二", "族员三", "近邻餐厅"}


def test_weak_edge_beyond_1km_not_in_atomic_family():
    """⑥二拍①锚（钟/鼓/城墙案）：1-2km 链式弱边不入原子族。钟楼/
    鼓楼/城墙碑林互 ≤0.5km 成原子族；小雁塔（↔城墙碑林 ~1.96km 压线
    弱边）、碑林博物馆（↔城墙碑林 ~1.16km）不入族——旧 2km 口径下
    五员族超 4/日帽触发结构性减员，核心三人组被肢解；新口径三人组
    原子完整落 day1，弱边两件留零散（2km 内仍受 tight_kin 软偏好，
    落哪天不锚）。"""
    cands = [
        _c("钟楼", (104.0600, 30.66), dur=40, city="西安"),
        _c("鼓楼", (104.0610, 30.66), dur=40, city="西安"),
        _c("城墙碑林", (104.0640, 30.66), tier=2, dur=90, city="西安"),
        _c("小雁塔", (104.0640, 30.6423), dur=60, city="西安"),  # ↔城墙碑林 ~1.96km
        _c("碑林博物馆", (104.0760, 30.6585), dur=60, city="西安"),  # ↔城墙碑林 ~1.16km
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, notes=notes
    )
    day_of = {it["name"]: it["day"] for it in items}
    trio = ("钟楼", "鼓楼", "城墙碑林")
    # 核心三人组原子完整同日（不被弱边撑爆减员肢解）
    assert len({day_of[n] for n in trio}) == 1
    assert day_of["钟楼"] == 1  # 最早可行日整族认领
    # 三人组无任何减员/退零散披露（旧口径会减钟楼/鼓楼/城墙碑林）
    assert not any(n for n in notes if any(t in str(n) for t in trio))


def test_all_small_family_claims_arrival_day():
    """⑦三轮②锚（账面剔腿）：腿不是游玩负载——可行性判定与
    day_loads 账面一律剔腿。三人组 40+40+90=170min 落到达日 d1：
    旧账面含腿 170+腿≈198>180 把整族挤去 d2（探针 r2 实录），剔腿后
    按 170 判 ≤180 直落 d1。2026-11-13 端点日内容闸后，到达日整族
    通道只收端点合法内容（简单街区/茶/演出），夹具改用带街/巷语素的
    轻量三人组，仍验 170≤180 的剔腿判据。"""
    cands = [
        _c("钟楼街", (104.0600, 30.66), dur=40, city="西安"),
        _c("鼓楼街", (104.0690, 30.66), dur=40, city="西安"),
        _c("城墙根巷", (104.0780, 30.66), dur=90, city="西安"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands,
        3,
        {"西安": (1, 3)},
        transfer_days={1},
        arrival_days={1},
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert {day_of["钟楼街"], day_of["鼓楼街"], day_of["城墙根巷"]} == {1}


def test_important_family_gets_450_clean_day_waiver():
    """⑧三轮①锚（净日预算豁免）：重要族（best-tier≤2）整族认领净日时
    预算 360→450（真实全日窗 09:00-17:30≈450；「拿组合族的时间加和
    算时间按排序选日子」，预算是选层启发式不是物理极限）。雁塔形 2 员
    族 240+180=420min>360——无豁免会「no feasible day, members stay
    loose」散装混日（探针 r2 实录：大雁塔混 30km 异簇 d3）；有豁免
    整族原子落净日 d1。"""
    cands = [
        _c("大雁塔", (104.0600, 30.66), tier=2, dur=240, city="西安"),
        _c("十二时辰", (104.0680, 30.66), dur=180, city="西安"),  # ↔大雁塔 ~0.77km
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"西安": (1, 2)})
    day_of = {it["name"]: it["day"] for it in items}
    assert {day_of["大雁塔"], day_of["十二时辰"]} == {1}


def test_entry_cap_feasible_arithmetic():
    """⑨四轮锚（纯算术）：入场闸镜像——09:00(540) 起、已有负载按单块
    前置、相邻 30 分钟隔、降序连排，任一件开场超其入场闸即不可排。
    大点帽 15:30(930)、普帽 16:00(960)（solver.generic_entry_cap 常量
    镜像）。"""
    # 空日 180+120+90：540→750→900，末件 90 开场 15:00 ≤16:00 可排
    assert _entry_cap_feasible(540, 0, 0, [(180, 930), (120, 930), (90, 960)])
    # +60 末件：90 后 t=1020(17:00) > 16:00 —— 钟楼案形，账面 450 预算
    # 过闸但物理排不下
    assert not _entry_cap_feasible(
        540, 0, 0, [(180, 930), (120, 930), (90, 960), (60, 960)]
    )
    # 已有族块 330min/3 卡前置：t=540+330+90=960(16:00)，大点 120 开场
    # 16:00 > 15:30 帽 —— 捆绑通道同判
    assert not _entry_cap_feasible(540, 330, 3, [(120, 930)])
    # 同块小点（帽 16:00）压线可排
    assert _entry_cap_feasible(540, 330, 3, [(60, 960)])
    # 帽口径：>80min 普通景点=大点帽 930，≤80min=普帽 960
    assert _cand_entry_cap(_c("大块景点", _A0, dur=120)) == 15 * 60 + 30
    assert _cand_entry_cap(_c("小块景点", _A0, dur=60)) == 16 * 60


def test_umbrella_bundle_respects_entry_cap_on_keeper_day():
    """⑩四轮锚（捆绑闸）：伞名近邻跨日捆绑把低 rank 件拉回高 rank 件
    同日前，先跑入场闸镜像——keeper 日已有物理负载塞不下就不拉
    （捆绑是机会性优化，跨日合法），不再硬塞进族占日让终排无声挤死
    某件（钟楼案：碑林博物馆 120min 被拉进 330min 族日，末件 17:00
    开场被 16:00 闸吞）。"""
    cands = {
        "城墙古城景区": _c("城墙古城景区", _A0, tier=2, dur=150),
        "古城伴一": _c("古城伴一", _A1, dur=90),
        "古城伴二": _c("古城伴二", _A2, dur=90),
        "成都古城博物馆": _c("成都古城博物馆", (104.082, 30.66), cat="museum", dur=120),
    }
    # 装配层规格形态：无坐标（走同城+词素降级判据，碑林产线同路），
    # duration_minutes 为物理时长，category 供大点帽判型
    heavy = [
        {
            "name": "城墙古城景区",
            "day": 1,
            "duration_minutes": 150,
            "category": "attraction",
            "city": "成都",
        },
        {
            "name": "古城伴一",
            "day": 1,
            "duration_minutes": 90,
            "category": "attraction",
            "city": "成都",
        },
        {
            "name": "古城伴二",
            "day": 1,
            "duration_minutes": 90,
            "category": "attraction",
            "city": "成都",
        },
        {
            "name": "成都古城博物馆",
            "day": 2,
            "duration_minutes": 120,
            "category": "museum",
            "city": "成都",
        },
    ]
    notes = _bundle_umbrella_spec_days(heavy, cands)
    # keeper 日族块 330min/3 卡 + 120 大点 = 末件开场 16:00 > 15:30 帽：
    # 不拉同日，博物馆留 day2，无捆绑披露
    assert next(s for s in heavy if s["name"] == "成都古城博物馆")["day"] == 2
    assert not any("古城博物馆" in n for n in notes)
    # 对照：keeper 日轻载（仅 90min 景区）时 t=660，120 大点 11:00 开场
    # 压线下可排 → 捆绑照常
    light = [
        {
            "name": "城墙古城景区",
            "day": 1,
            "duration_minutes": 90,
            "category": "attraction",
            "city": "成都",
        },
        {
            "name": "成都古城博物馆",
            "day": 2,
            "duration_minutes": 120,
            "category": "museum",
            "city": "成都",
        },
    ]
    notes_light = _bundle_umbrella_spec_days(light, cands)
    assert next(s for s in light if s["name"] == "成都古城博物馆")["day"] == 1
    assert any("古城博物馆" in n for n in notes_light)


def test_cap_infeasible_family_sheds_endpoint_with_disclosure():
    """⑪四轮锚（钟楼案选层形）：四员族 180+120+90+60=450min——tier2
    成员在场净日 450 预算豁免账面可落（三轮①），但降序连排末件 60
    开场 17:00 > 16:00 帽物理排不下（终排只会无声挤死它）。四轮起认
    领时刻即拦：整族不可行→减地理直径端点对中更次要的轻端（tier11
    > 重员一 tier2），余三员原子落 day1，轻端另日安排+披露留痕——
    挤死不可能发生。"""
    cands = [
        _c("重员一", (104.0600, 30.66), tier=2, dur=180),
        _c("重员二", (104.0680, 30.66), dur=120),
        _c("中员", (104.0750, 30.66), dur=90),
        _c("轻端", (104.0820, 30.66), dur=60),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, notes=notes
    )
    day_of = {it["name"]: it["day"] for it in items}
    # 余三员原子落 day1（390min，450 豁免账面过+入场闸物理过）
    assert day_of["重员一"] == day_of["重员二"] == day_of["中员"] == 1
    # 轻端被减员另日安排，不再占着 day1 席位等终排无声挤死
    assert day_of["轻端"] == 2
    assert any("轻端" in n for n in notes)  # 减员双语披露留痕


def test_ace_family_displaces_weaker_family_with_disclosure():
    """⑫先保 tier 高（2026-11-10 拍板「先保 TIER 高的。如果装不下可
    以看当天已经落地景点和要落地景点一起观察，组内按重要度小和重复
    度高的原则减少项目」）：王牌族（best tier≤2）全窗被拒且拒因纯容
    量型（cap4/budget/entry_cap——雨/远/边日闸弹人没用）时，把目标日
    已落地件与入件并一组观察，按「重要度小、重复度高」逐件减员腾位。

    布形：弱族四员 180+120+90+60=450 形（一员 5a 挂联伞名博物馆对），
    入场闸物理不可排→预可行 0 最先处理→减地理端点（60min 弱端）后
    三员 390 占 day1；王牌族 2 员 240+180=420（一员 unesco 一员 5a、
    硬露天 rain_ok=no 锁死雨日 day2）→ day1 cap4 拒、day2 雨拒→
    弹让：最弱散件先弹（族形 2 保持、账面仍不合），伞名对联整组弹出
    （族形清零合法、孤员悬日不许）→420≤450 入账，王牌族原子落 day1，
    弱族三员回散件通道另日+披露留痕。"""
    cands = [
        _c("城墙古城景区", (104.0500, 30.66), tier=2, dur=180),
        _c("江畔乙", (104.0580, 30.66), dur=120),
        _c("成都古城博物馆", (104.0660, 30.66), cat="museum", dur=90),
        _c("汀丁", (104.0740, 30.66), dur=60),
        _c("王牌A", (103.9000, 30.66), tier=1, dur=240),
        _c("副A", (103.9050, 30.66), tier=2, dur=180),
    ]
    cands[4]["rain_ok"] = "no"
    cands[5]["rain_ok"] = "no"
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, notes=notes, rain_days={"成都": {2}}
    )
    day_of = {it["name"]: it["day"] for it in items}
    # 王牌族整族原子落 day1（弹让入账，不被拆散）
    assert day_of["王牌A"] == 1
    assert day_of["副A"] == 1
    # 弱族三员全部弹出 day1（伞名对联整组同进退），回散件通道另日
    assert day_of["城墙古城景区"] != 1
    assert day_of["江畔乙"] != 1
    assert day_of["成都古城博物馆"] != 1
    # 弹让双语披露留痕（要加回请说）
    assert any("让位" in n and "王牌A" in n for n in notes)
