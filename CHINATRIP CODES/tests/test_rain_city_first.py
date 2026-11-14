# -*- coding: utf-8 -*-
"""2026-11-11 三拍引擎侧回归锚（类级规则，无真实站点名）。

①簇减员雨日补口（拍板「一族太大放不下是可以减景点的，与室外一族绑簇
不是不入选的理由」）：自动聚合簇全窗被雨闸弹回时，先裁雨日不合适成员
（硬露天/未标注非体验件）再重试——2 员族同样裁到 1 员；钉/心愿不裁；
耐雨/体验型成员保留落位，披露进 notes，不再整簇弃排。
②体验型保底同类替补+弃排披露（拍板「多样化走同类替补，需要实行」）：
每行程 ≥2 体验型（_EXPERIENCE_CATEGORIES）主选排不进时，从候选池
同类目其他候选替补重试；替补也排不进必须显式披露（notes），不许只留
服务端日志。
③雨日市内优先（拍板「雨天不倾向去远郊风景区，应安排市内活动如看戏
喝茶」）：全雨窗里距城市核心（medoid）超市区圈的风景区族整族降权，
市内体验型族先赢档期（软偏好非硬禁，王牌不豁免）。
"""

from __future__ import annotations

from app.services.agent.plan import PlanningAgent


def _c(
    name: str,
    loc: tuple[float, float],
    *,
    cat: str = "attraction",
    dur: int = 60,
    rain_ok: str = "",
    tier: int | None = None,
    city: str = "成都",
):
    c: dict = {
        "name": name,
        "city": city,
        "category": cat,
        "suggested_duration_min": dur,
        "location": loc,
        "address": f"{city}测试路1号",
        "rating": 4.5,
    }
    if rain_ok:
        c["rain_ok"] = rain_ok
    if tier == 1:
        c["tags"] = ["unesco"]
        c["source"] = "unesco"
    elif tier == 2:
        c["tags"] = ["5a"]
        c["source"] = "5a"
    return c


def _spec(name: str, day: int, *, cat: str = "museum", dur: int = 90):
    return {
        "name": name,
        "city": "成都",
        "category": cat,
        "day": day,
        "duration_minutes": dur,
        "location": {"lon": 104.06, "lat": 30.66},
    }


# 布点（lat 30.66 下 1° lon ≈ 95.8km）：城内件 ~104.06 一片，远郊件
# ~104.50 一片（相距 ~42km，互不成族、远超市区圈 15km）。
# 命名避坑：同对成员名不得共用站名核心（池级同站孪生并卡会并掉一张），
# 远郊对也不得入风景区行程桶（_itin_cap_bucket=scenic 上限 1/行程会把
# 第二张裁出池）——故远郊对用「观景台/天梯/索道/步道」类非桶名。
_T0 = (104.060, 30.66)
_T1 = (104.065, 30.66)  # ↔_T0 ~0.48km（≤1km 原子连边）
_G0 = (104.062, 30.70)  # 城内第三点（撑 medoid 主导簇，~4.5km 不入族）
_F0 = (104.500, 30.66)
_F1 = (104.505, 30.66)  # ↔_F0 ~0.48km


def test_rain_cluster_reduces_unfit_members_and_keeps_rain_fit():
    """①混合耐雨属性的自动簇在雨日减员落耐雨成员（而非整簇弃排）：
    茶馆（体验型，未标注）+ 两个硬露天伴成族，全雨窗整族被雨闸弹回
    ——裁掉露天伴后茶馆落位，披露进 notes。"""
    cands = [
        _c("茶馆甲", _T0, cat="tea_experience", dur=120),
        _c("江滩露台", _T1, cat="attraction", dur=60, rain_ok="no"),
        _c("山脊步道", (104.070, 30.66), cat="nature", dur=60, rain_ok="no"),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1, 2}}, notes=notes
    )
    names = {s["name"] for s in picked}
    assert "茶馆甲" in names  # 耐雨成员减员后落位
    assert "江滩露台" not in names and "山脊步道" not in names
    assert any("雨天不适合" in n for n in notes)  # 减员披露


def test_rain_cluster_two_member_still_reduces_on_rain_rejection():
    """①补：2 员族同样裁——体验型 + 单个硬露天伴绑簇不是不入选的理由。"""
    cands = [
        _c("茶馆乙", _T0, cat="tea_experience", dur=120),
        _c("湖滨草坪", _T1, cat="attraction", dur=60, rain_ok="no"),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1, 2}}, notes=notes
    )
    names = {s["name"] for s in picked}
    assert "茶馆乙" in names
    assert "湖滨草坪" not in names
    assert any("雨天不适合" in n for n in notes)


def test_experience_guarantee_same_type_substitute_placed():
    """②保底体验型主选排不进 → 池内同类目候选替补落上（回填重要度门槛
    不够格的无评分长尾，保底替补通道照收——保底是拍板不是凑数）。"""
    tea = _c("茶馆丙", _T0, cat="tea_experience", dur=60)
    tea.pop("rating")  # 无评分长尾：回填①门槛不够格，主环不选
    picked = [_spec("博物馆甲", 1)]
    picked, notes = PlanningAgent._rebalance_days(picked, [tea], 2, {"成都": (1, 2)})
    subs = [s for s in picked if s["name"] == "茶馆丙"]
    assert len(subs) == 1 and subs[0]["day"] in (1, 2)


def test_experience_guarantee_dropped_is_disclosed():
    """②补：替补也排不进（4/日帽全满）最终弃排时必须显式披露进 notes，
    不许只留服务端日志。"""
    tea = _c("茶馆丁", _T0, cat="tea_experience", dur=60)
    picked = [_spec(f"博物馆{d}{i}", d) for d in (1, 2) for i in range(4)]
    picked, notes = PlanningAgent._rebalance_days(picked, [tea], 2, {"成都": (1, 2)})
    assert all(s["name"] != "茶馆丁" for s in picked)
    assert any("体验型活动保底" in zh for zh, _ in notes)


def test_rainy_window_far_scenic_family_yields_to_in_city_experience():
    """③全雨窗里市内体验型族先赢档期：远郊风景区族（5A 王牌，雨日远征
    不优先、王牌不豁免）整族降权殿后——市内茶馆族占 day1，远郊族落
    day2（无本键时按 tier 梯远郊王牌先占 day1）。远郊族标 rain_ok=yes
    隔离变量：雨闸放行，档期输赢只由远郊降权键决定。"""
    cands = [
        _c("茶馆戊", _T0, cat="tea_experience", dur=120, rain_ok="yes"),
        _c("茶馆己", _T1, cat="tea_experience", dur=120, rain_ok="yes"),
        _c("城内馆甲", _G0, cat="museum", dur=60),
        _c("苍岩观景台", _F0, cat="attraction", dur=180, tier=2, rain_ok="yes"),
        _c("翠壁天梯", _F1, cat="attraction", dur=180, tier=2, rain_ok="yes"),
    ]
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1, 2}}
    )
    by_day: dict[int, set[str]] = {}
    for s in picked:
        by_day.setdefault(s["day"], set()).add(s["name"])
    assert by_day[1] >= {"茶馆戊", "茶馆己"}  # 市内体验型族先赢 day1
    assert "苍岩观景台" in by_day[2] and "翠壁天梯" in by_day[2]


def test_far_scenic_demotion_inactive_without_rain():
    """③补：无雨窗口远郊降权恒不生效——晴天 tier 原梯不动（远郊王牌
    族照占 day1）。"""
    cands = [
        _c("茶馆庚", _T0, cat="tea_experience", dur=120, rain_ok="yes"),
        _c("茶馆辛", _T1, cat="tea_experience", dur=120, rain_ok="yes"),
        _c("城内馆乙", _G0, cat="museum", dur=60),
        _c("苍岩索道", _F0, cat="attraction", dur=180, tier=2),
        _c("云顶步道", _F1, cat="attraction", dur=180, tier=2),
    ]
    picked = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day: dict[int, set[str]] = {}
    for s in picked:
        by_day.setdefault(s["day"], set()).add(s["name"])
    assert "苍岩索道" in by_day[1] and "云顶步道" in by_day[1]
