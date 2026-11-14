# -*- coding: utf-8 -*-
"""到达日补真实内容（2026-11-13 六拍 / 11-14 两拍 / 11-14 三拍）。

口径（用户原话）：
- 「到达日不能整天没有安排：附近的 CITYWALK / 演出 / 餐厅都行」
- 「餐卡补卡规则把转场日整天豁免 为什么？不应该豁免」「至少晚餐不应该豁免」
- 「这些城市漫步需要找到景点。餐卡和按摩卡先找附近 5 公里内评价高的点，
   找不到就找 8 公里内」

落地：
① 餐卡：转场日不再整日豁免——按 fixed 窗（落地 +150 / 发车 −90）找空隙，
   晚窗被占走迟场 20:30–21:30（45/30 分钟）；餐窗整段在途才不补。
② 空到达日不再造假「城市漫步（自由安排）」占位：`PlanningAgent.
   _fill_arrival_day_nearby` 用 `_nearby_poi_rows` 按 PostGIS 圈选同城
   POI，`_pick_arrival_nearby` 按 景点→演出→按摩→餐厅 逐级挑，每级先
   5 公里圈按评价挑、空则 8 公里圈。
③ 到达日只收「轻量真实景点」：`_arrival_sight_visit`（tier>3 且
   ≤120 分钟）既是合法端点内容、也不进重磅闸；5A/4A（tier≤3）仍出端点日。
④ 读路径 `heal_arrival_light` 只补餐卡（没有 DB 句柄，不硬造景点）。
"""

from datetime import time

from app.services.agent.plan import (
    _arrival_heavy_visit,
    _arrival_sight_visit,
    _endpoint_content_visit,
    _endpoint_day_light_sweep,
    _pick_arrival_nearby,
    _retime_meal_placeholders,
    heal_arrival_light,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

_C0 = GeoPoint(lon=108.9400, lat=34.2600)


def _transfer(day: int = 1, *, start=time(9, 0), end=time(12, 0)) -> TransferItem:
    return TransferItem(
        item_id=f"t-{day}",
        day=day,
        seq=1,
        mode="flight",
        from_city="上海",
        to_city="西安",
        start_time=start,
        end_time=end,
    )


def _hotel(day: int = 1, *, start=time(13, 30), end=time(14, 30)) -> VisitItem:
    return VisitItem(
        item_id=f"h-{day}",
        name="🏨 酒店入住（放行李·休整）",
        city="西安",
        day=day,
        duration_minutes=60,
        category="hotel",
        start_time=start,
        end_time=end,
    )


def _visit(name: str, dur: int, loc: GeoPoint, day: int, **kw) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}-{day}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
        **kw,
    )


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-arrival-fill", cities=["西安"], days=list(days)
    )


def _day(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="西安", items=list(items))


def _cand(
    name: str,
    *,
    lat: float,
    category: str = "attraction",
    dur: int = 90,
    rating: float | None = None,
    count: int | None = None,
    lon: float = 0.0,
    tier: int | None = None,
) -> dict:
    return {
        "name": name,
        "city": "西安",
        "category": category,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
        "rating": rating,
        "rating_count": count,
        "tags": [],
        "best_visit_time": "any",
        "_tier": tier,
    }


# ------------------------------------------------ 餐卡（转场日不豁免）


def test_transfer_day_gets_dinner_card_when_window_allows():
    """转场日不再整日豁免餐卡：落地 12:00 的到达日应补上晚餐卡。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    foods = [i for i in d1.items if getattr(i, "category", "") == "food"]
    assert foods, "到达日应补一张晚餐卡（旧口径转场日整日豁免）"
    dinner = [i for i in foods if "晚饭" in str(i.name)]
    assert dinner, "应是晚餐卡而不是硬塞午餐（落地 12:00 + 150 分钟缓冲）"
    assert dinner[0].start_time is not None
    assert dinner[0].start_time >= time(16, 30)


def test_transfer_day_in_air_all_day_gets_no_meal_card():
    """整天在飞机上（09:00-21:00）→ 餐窗全被占，不硬塞餐卡。"""
    d1 = _day(1, _transfer(start=time(9, 0), end=time(21, 0)))
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    assert not [i for i in d1.items if getattr(i, "category", "") == "food"]


def test_late_dinner_card_when_evening_blocked_until_2015():
    """「至少晚餐不应该豁免」：晚窗被占到 20:15 也要走迟场补 30/45 分钟晚卡。"""
    busy = VisitItem(
        item_id="v-busy",
        name="晚间长块",
        city="西安",
        day=1,
        duration_minutes=215,
        category="citywalk",
        start_time=time(16, 40),
        end_time=time(20, 15),
        location=_C0,
    )
    d1 = _day(1, busy)
    plan = _plan(d1)
    _retime_meal_placeholders(plan, ensure_cards=True)

    dinner = [i for i in d1.items if "晚饭" in str(i.name)]
    assert dinner, "晚窗被占也要补迟场晚卡"
    assert dinner[0].start_time >= time(20, 30)
    assert dinner[0].duration_minutes >= 30


# ------------------------------------------------ 空到达日：不造假占位


def test_empty_arrival_day_gets_no_fake_citywalk():
    """空到达日不再插「城市漫步（自由安排）」假卡——真实景点由规划期补。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1, _day(2, _visit("城件一", 60, _C0, 2, tier=9)))
    _endpoint_day_light_sweep(plan, frozenset())

    assert not any(
        str(getattr(i, "item_id", "")).startswith("citywalk-ph-d") for i in d1.items
    ), "不得造假漫步占位"
    assert any("到达日" in str(a) for a in plan.assumptions), "空日要留披露"


def test_heal_adds_meals_but_no_fake_sight():
    """读路径自愈只补餐卡（无 DB 句柄，不硬造景点）。"""
    d1 = _day(1, _transfer(), _hotel())
    plan = _plan(d1, _day(2, _visit("城件一", 60, _C0, 2, tier=9)))
    heal_arrival_light(plan)

    assert not any(
        str(getattr(i, "item_id", "")).startswith("citywalk-ph-d") for i in d1.items
    )
    assert [i for i in d1.items if getattr(i, "category", "") == "food"], "晚卡要补"


# ------------------------------------------------ 挑选器：5 公里评价高 → 8 公里


def test_pick_prefers_high_rating_within_5km():
    """5 公里圈内按评价挑：评分高的优先于距离近的。"""
    near_low = _cand("近处低分馆", lat=0.02, rating=3.6)  # ~2.2km
    far_high = _cand("近圈高分馆", lat=0.035, rating=4.6)  # ~3.9km
    hit = _pick_arrival_nearby([near_low, far_high], (0.0, 0.0), exclude=set())
    assert hit is not None and hit["name"] == "近圈高分馆"


def test_pick_falls_back_to_8km_when_5km_empty():
    """5 公里内没有候选 → 退 8 公里圈，仍按评价挑。"""
    only_far = _cand("八公里内馆", lat=0.06, rating=4.1)  # ~6.7km
    hit = _pick_arrival_nearby([only_far], (0.0, 0.0), exclude=set())
    assert hit is not None and hit["name"] == "八公里内馆"


def test_pick_tier_order_sight_before_food_and_spa():
    """分级顺序：景点 → 演出 → 按摩 → 餐厅。景点在圈内就不选餐厅。"""
    food = _cand("高分餐厅", lat=0.01, category="food", rating=4.9)
    spa = _cand("汤泉会馆", lat=0.01, category="other", rating=4.8)
    sight = _cand("城墙", lat=0.03, category="attraction", rating=3.8)
    hit = _pick_arrival_nearby([food, spa, sight], (0.0, 0.0), exclude=set())
    assert hit is not None and hit["name"] == "城墙"


def test_pick_spa_tier_used_when_no_sight_or_show():
    """无景点/演出时，按摩/汤泉（5 公里内）可以补位。"""
    spa = _cand("水裹汤泉", lat=0.02, category="entertainment", rating=4.4)
    hit = _pick_arrival_nearby([spa], (0.0, 0.0), exclude=set())
    assert hit is not None and hit["name"] == "水裹汤泉"


def test_pick_skips_long_and_excluded_and_no_anchor():
    """＞120 分钟、已在行程里、以及缺锚（不可核）都不挑。"""
    long_one = _cand("大汤泉", lat=0.01, dur=180, rating=4.9)
    excluded = _cand("已排馆", lat=0.01, rating=4.9)
    assert _pick_arrival_nearby([long_one], (0.0, 0.0), exclude=set()) is None
    assert _pick_arrival_nearby([excluded], (0.0, 0.0), exclude={"已排馆"}) is None
    assert _pick_arrival_nearby([excluded], None, exclude=set()) is None


def test_pick_keeps_center_4a_sights():
    """市中心 4A（tier≤3、≤120 分钟）不再被一票否决，按评价可入选。"""
    premium = _cand("西安鼓楼", lat=0.01, category="attraction", tier=3, rating=4.9)
    museum = _cand(
        "陕西唐三彩艺术博物馆",
        lat=0.03,
        category="museum",
        tier=10,
        rating=4.6,
        dur=120,
    )
    hit = _pick_arrival_nearby([premium, museum], (0.0, 0.0), exclude=set())
    assert hit is not None and hit["name"] == "西安鼓楼"


# ------------------------------------------------ 到达日轻量景点口径


def test_light_sight_is_legal_arrival_content():
    """tier>3 且 ≤120 分钟的真实景点：合法端点内容，且不算重磅。"""
    v = _visit("陕西唐三彩艺术博物馆", 120, _C0, 1, category="museum", tier=10)
    assert _arrival_sight_visit(v) is True
    assert _endpoint_content_visit(v) is True
    assert _arrival_heavy_visit(v) is False


def test_center_short_sight_stays_but_long_sight_leaves():
    """市中心短时 4A 留在端点日；>120 分钟大块头与 5A 王牌仍出端点日。"""
    center = _visit("西安钟楼", 90, _C0, 1, category="attraction", tier=3)
    long_one = _visit("大型博物馆", 180, _C0, 1, category="museum", tier=10)
    ace = _visit("秦始皇帝陵博物院", 120, _C0, 1, category="attraction", tier=1)
    assert _arrival_heavy_visit(center) is False
    assert _endpoint_content_visit(center) is True
    assert _arrival_heavy_visit(long_one) is True
    assert _endpoint_content_visit(long_one) is False
    assert _arrival_heavy_visit(ace) is True
