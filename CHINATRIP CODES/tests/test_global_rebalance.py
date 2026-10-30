# -*- coding: utf-8 -*-
"""全局跨天优化回归（2026-10-30 用户拍板「做全局跨天优化」）。

覆盖：
- _city_day_ranges 无 city_days 修复：闭合行程尾城只留返程日、真实目的
  地均分活动天（2026-11-04 空天事故根因之一：上海→成都→重庆→上海 7 天
  被旧版分成 成都1天/重庆1天/归程上海5天，day3-6 全空）。
- _rebalance_days：空/欠载天回填（tier 序、地理腿、雨天露天闸、孪生
  有效记账含 >2km 地理闸、每日 4 点闸、预算含腿）+ 超载天分流（必去
  不动）。
"""

from app.services.agent.plan import PlanningAgent, _city_day_ranges


def _cand(
    name,
    city,
    *,
    loc,
    minutes=90,
    rain=None,
    tags=None,
    source=None,
    category="sight",
):
    return {
        "name": name,
        "city": city,
        "category": category,
        "suggested_duration_min": minutes,
        "location": {"lon": loc[0], "lat": loc[1]},
        "rain_ok": rain,
        "tags": tags or [],
        "source": source,
    }


def _spec(name, city, day, *, loc=None, minutes=90, must=False, category="sight"):
    spec = {
        "name": name,
        "city": city,
        "category": category,
        "day": day,
        "duration_minutes": minutes,
    }
    if loc is not None:
        spec["location"] = {"lon": loc[0], "lat": loc[1]}
    if must:
        spec["must"] = True
    return spec


# --- _city_day_ranges：无 city_days 的均分与闭合行程 ------------------------


def test_ranges_closed_trip_even_split():
    # 上海→成都→重庆→上海 7 天：归程上海只留返程日，蓉渝均分 6 天
    assert _city_day_ranges(["上海", "成都", "重庆", "上海"], 7) == {
        "成都": (1, 3),
        "重庆": (4, 6),
        "上海": (7, 7),
    }


def test_ranges_closed_trip_uneven_split():
    # 8 天：7 个活动天 4+3 分给两个真实目的地
    assert _city_day_ranges(["上海", "杭州", "苏州", "上海"], 8) == {
        "杭州": (1, 4),
        "苏州": (5, 7),
        "上海": (8, 8),
    }


def test_ranges_open_trip_even_split():
    # 非闭合：4 天对半分（旧版杭州只给 1 天）
    assert _city_day_ranges(["上海", "杭州", "苏州"], 4) == {
        "杭州": (1, 2),
        "苏州": (3, 4),
    }


def test_ranges_city_days_unchanged():
    # 用户显式给定天数：行为不变（既有语义锚）
    assert _city_day_ranges(["上海", "杭州", "苏州"], 5, {"杭州": 2}) == {
        "杭州": (1, 2),
        "苏州": (3, 5),
    }
    assert _city_day_ranges(["北京"], 3) == {"北京": (1, 3)}
    assert _city_day_ranges(
        ["上海", "成都", "重庆", "上海"], 7, {"成都": 2, "重庆": 4}
    ) == {
        "成都": (1, 2),
        "重庆": (3, 6),
        "上海": (7, 7),
    }


# --- _rebalance_days ①：空/欠载天回填 --------------------------------------


def test_rebalance_fills_empty_day_from_full_pool():
    # day2 空：从候选（含池外 tier 序）补 5A 级点
    picked = [_spec("甲", "成都", 1, loc=(104.0, 30.6), minutes=180)]
    candidates = [
        _cand("甲", "成都", loc=(104.0, 30.6), minutes=180),
        _cand("乙5A", "成都", loc=(104.0, 30.61), tags=["5a"], minutes=90),
    ]
    out, notes = PlanningAgent._rebalance_days(picked, candidates, 3, {"成都": (1, 3)})
    assert any(s["name"] == "乙5A" and s["day"] == 2 for s in out)
    assert any("回填" in zh for zh, _en in notes)


def test_rebalance_twin_phantom_does_not_count():
    # 孪生 spec（同名同址）双占预算：均衡只数胜者——孪生败者不再压住
    # 预算；空天优先获补（建川博物馆进 day2）；败者留在 picked（组装层
    # 去重负责丢弃+留痕）
    picked = [
        _spec("安仁古镇景区", "成都", 1, loc=(103.6, 30.5), minutes=180),
        _spec("安仁古镇", "成都", 1, loc=(103.6, 30.5), minutes=180),
    ]
    candidates = [
        _cand("安仁古镇景区", "成都", loc=(103.6, 30.5), minutes=180),
        _cand("建川博物馆", "成都", loc=(103.6, 30.51), minutes=90),
    ]
    out, _ = PlanningAgent._rebalance_days(picked, candidates, 2, {"成都": (1, 2)})
    assert any(s["name"] == "建川博物馆" and s["day"] == 2 for s in out)
    assert sum(1 for s in out if s["name"].startswith("安仁古镇")) == 2


def test_rebalance_far_same_name_not_phantom():
    # 同名但相距 >2km 的不同场馆（青城山 vs 青城山skydive）不是孪生：
    # 双双计入负载，满载天不再回填
    picked = [
        _spec("青城山", "成都", 1, loc=(103.59, 30.90), minutes=180),
        _spec("青城山skydive", "成都", 1, loc=(103.62, 30.85), minutes=180),
    ]
    candidates = [
        _cand("青城山", "成都", loc=(103.59, 30.90), minutes=180),
        _cand("青城山skydive", "成都", loc=(103.62, 30.85), minutes=180),
        _cand("补充点", "成都", loc=(103.60, 30.88), minutes=90),
    ]
    out, _ = PlanningAgent._rebalance_days(picked, candidates, 1, {"成都": (1, 1)})
    # day1 有效负载 360 已满：不再补
    assert not any(s["name"] == "补充点" for s in out)


def test_rebalance_outdoor_skips_rainy_day():
    # 露天点不进雨天；室内点可进
    picked = [_spec("锚点", "重庆", 1, loc=(106.5, 29.5), minutes=90)]
    candidates = [
        _cand("锚点", "重庆", loc=(106.5, 29.5), minutes=90),
        _cand("露天峡", "重庆", loc=(106.5, 29.51), minutes=90, rain="no"),
        _cand("室内馆", "重庆", loc=(106.5, 29.51), minutes=90, rain="yes"),
    ]
    out, _ = PlanningAgent._rebalance_days(
        picked,
        candidates,
        2,
        {"重庆": (1, 2)},
        rain_days={"重庆": {2}},
    )
    days_of = {(s["name"], s["day"]) for s in out}
    assert ("露天峡", 2) not in days_of
    assert ("室内馆", 2) in days_of


def test_rebalance_respects_budget_and_cap():
    # 预算含打车腿：远点腿爆炸不补；每日 4 点闸不破
    picked = [_spec("锚点", "成都", 1, loc=(104.0, 30.6), minutes=90)]
    far = (105.5, 31.5)  # ~150km → 打车腿封顶 180
    candidates = [
        _cand("锚点", "成都", loc=(104.0, 30.6), minutes=90),
        _cand("远点", "成都", loc=far, minutes=180),
        _cand("近点", "成都", loc=(104.0, 30.61), minutes=90),
    ]
    out, _ = PlanningAgent._rebalance_days(picked, candidates, 1, {"成都": (1, 1)})
    names = [s["name"] for s in out]
    assert "远点" not in names
    assert sum(1 for s in out if s["day"] == 1) <= 4


# --- _rebalance_days ②：超载天分流 -----------------------------------------


def test_rebalance_spills_overloaded_day_but_never_must():
    # day1 超载：非必去搬走、必去钉死
    picked = [
        _spec("必去点", "成都", 1, loc=(104.0, 30.6), minutes=180, must=True),
        _spec("可搬点", "成都", 1, loc=(104.4, 30.4), minutes=180),
        _spec("可搬2", "成都", 1, loc=(104.4, 30.41), minutes=120),
    ]
    candidates = [_cand("必去点", "成都", loc=(104.0, 30.6), minutes=180)]
    out, notes = PlanningAgent._rebalance_days(picked, candidates, 2, {"成都": (1, 2)})
    must_days = {s["day"] for s in out if s.get("must")}
    assert must_days == {1}
    day1 = sum(s["duration_minutes"] for s in out if s["day"] == 1)
    day2 = [s["name"] for s in out if s["day"] == 2]
    assert day1 <= 360
    assert day2  # 分流到 day2
    assert any("分流" in zh for zh, _en in notes)


def test_rebalance_keeps_food_and_show_untouched():
    # 餐饮/演出不参与搬移
    picked = [
        _spec("正餐", "成都", 1, loc=(104.0, 30.6), minutes=60, category="food"),
        _spec(
            "演出",
            "成都",
            1,
            loc=(104.0, 30.6),
            minutes=80,
            category="entertainment",
        ),
        _spec("大点", "成都", 1, loc=(104.0, 30.6), minutes=180),
        _spec("大点2", "成都", 1, loc=(104.0, 30.61), minutes=180),
    ]
    out, _ = PlanningAgent._rebalance_days(picked, [], 2, {"成都": (1, 2)})
    for name in ("正餐", "演出"):
        assert any(s["name"] == name and s["day"] == 1 for s in out)
