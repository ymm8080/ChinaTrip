"""Tests for the restaurant recommendation tool (§6.2 v1.7, iron rule 20)."""

import asyncio
from datetime import time

from app.services.itinerary.models import DayPlan, GeoPoint, VisitItem
from app.services.restaurants import (
    NO_LOCATION_DETOUR_SCORE,
    RestaurantCandidate,
    build_food_item,
    is_lunch_placeholder,
    meal_times,
    meal_window,
    rank_by_detour,
    recommend_restaurants,
    search_restaurants,
)

# 1 degree of latitude ~ 111.19 km, so lat 0.05 ~ 5.56 km from the origin.
ORIGIN = GeoPoint(lon=0.0, lat=0.0)


class StubAmap:
    """Minimal AmapSearchService stub: canned pois or a raised error."""

    def __init__(self, pois=None, error=None):
        self._pois = pois or []
        self._error = error
        self.calls = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        if self._error is not None:
            raise self._error
        return self._pois


def make_poi(name, lon=0.0, lat=0.0, rating=None, poi_id=None, no_location=False):
    """amap-client-shaped dict; no_location POIs carry no coordinates."""
    return {
        "source": "amap",
        "source_poi_id": poi_id or f"poi-{name}",
        "name": name,
        "city": "杭州",
        "category": "餐饮服务;中餐厅",
        "address": f"{name}地址1号",
        "opening_hours": "周一至周日 10:00-22:00",
        "location": None if no_location else {"lon": lon, "lat": lat},
        **({} if rating is None else {"rating": rating}),
    }


def day_plan(day=1, base_city="杭州", items=None):
    return DayPlan(day=day, base_city=base_city, items=items or [])


def visit(item_id, start=None, end=None, duration=None, location=None):
    return VisitItem(
        item_id=item_id,
        name=f"景点{item_id}",
        city="杭州",
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        location=location,
    )


# --- meal_window -----------------------------------------------------------


def test_meal_window_empty_day_returns_constants():
    # 午餐窗 12:00–13:30（2026-10-31 拍板）
    assert meal_window(day_plan(), "lunch") == (time(12, 0), time(13, 30))
    assert meal_window(day_plan(), "dinner") == (time(17, 30), time(19, 30))


def test_meal_window_untimed_items_do_not_block():
    plan = day_plan(items=[visit("v1")])  # no times at all
    assert meal_window(plan, "lunch") == (time(12, 0), time(13, 30))
    # start_time alone (no end, no duration) defines no interval either
    plan2 = day_plan(items=[visit("v2", start=time(12, 0))])
    assert meal_window(plan2, "lunch") == (time(12, 0), time(13, 30))


def test_meal_window_item_inside_window_compresses_gap():
    # 2026-11-03 拍板：午餐 90 分钟——12:30–13:30 仅剩 60 分钟空档，
    # 装不下 90 分钟午餐 → None（铁律 20：不强插）
    plan = day_plan(items=[visit("v1", start=time(11, 30), end=time(12, 30))])
    assert meal_window(plan, "lunch") is None
    # right-hand compression: item overhanging the window end gets clipped;
    # the 90-minute window then leaves only a 30-min gap -> no meal fits
    plan2 = day_plan(items=[visit("v2", start=time(12, 30), end=time(14, 0))])
    assert meal_window(plan2, "lunch") is None


def test_meal_window_duration_only_item_blocks():
    plan = day_plan(
        items=[visit("v1", start=time(12, 0), duration=60)]  # end_time absent
    )
    # leftover gap 13:00-13:30 is < 60 min
    assert meal_window(plan, "lunch") is None


def test_meal_window_fully_occupied_returns_none():
    plan = day_plan(
        items=[
            visit("v1", start=time(11, 30), end=time(12, 30)),
            visit("v2", start=time(12, 30), end=time(13, 30)),
        ]
    )
    assert meal_window(plan, "lunch") is None


def test_meal_window_items_outside_window_are_ignored():
    plan = day_plan(
        items=[
            visit("v1", start=time(9, 0), end=time(11, 0)),
            visit("v2", start=time(14, 0), end=time(16, 0)),
        ]
    )
    assert meal_window(plan, "lunch") == (time(12, 0), time(13, 30))


# --- meal_times（钳制中点：一餐绝不溢出空窗尾） -----------------------------


def test_meal_times_full_windows():
    # 90-minute lunch window: midpoint 12:45 + 60 would overflow -> clamped
    assert meal_times((time(12, 0), time(13, 30))) == (time(12, 30), time(13, 30))
    assert meal_times((time(17, 30), time(19, 30))) == (time(18, 30), time(19, 30))


def test_meal_times_compressed_gap_never_spills():
    # 60-minute gap fits exactly; a midpoint + 60 (13:00-14:00) would spill
    assert meal_times((time(12, 30), time(13, 30))) == (time(12, 30), time(13, 30))
    assert meal_times((time(12, 0), time(13, 0))) == (time(12, 0), time(13, 0))


# --- rank_by_detour --------------------------------------------------------


def test_rank_by_detour_nearest_candidate_ranks_first():
    near = RestaurantCandidate(name="近", location=GeoPoint(lon=0.0, lat=0.002))
    far = RestaurantCandidate(name="远", location=GeoPoint(lon=0.0, lat=0.05))
    ranked = rank_by_detour([far, near], route_points=[ORIGIN])
    assert ranked[0].name == "近"
    assert ranked[0].detour_score < 1.0  # ~0.22 km
    assert ranked[1].detour_score > 5.0  # ~5.6 km
    assert ranked[0].detour_score < ranked[1].detour_score


def test_rank_by_detour_no_location_ranks_last():
    near = RestaurantCandidate(name="近", location=GeoPoint(lon=0.0, lat=0.002))
    noloc = RestaurantCandidate(name="无坐标")
    ranked = rank_by_detour([noloc, near], route_points=[ORIGIN])
    assert ranked[-1].name == "无坐标"
    assert ranked[-1].detour_score == NO_LOCATION_DETOUR_SCORE


def test_rank_by_detour_takes_min_over_all_route_points():
    cand = RestaurantCandidate(name="中途", location=GeoPoint(lon=0.0, lat=0.008))
    ranked = rank_by_detour(
        [cand],
        route_points=[ORIGIN, GeoPoint(lon=0.0, lat=0.05)],
    )
    assert ranked[0].detour_score < 1.0  # nearest point wins (~0.89 km)


def test_rank_by_detour_rating_weight_flips_near_tie():
    plain = RestaurantCandidate(name="近无评分", location=GeoPoint(lon=0.0, lat=0.003))
    rated = RestaurantCandidate(
        name="远高评分", location=GeoPoint(lon=0.0, lat=0.004), rating=4.5
    )
    ranked = rank_by_detour([plain, rated], route_points=[ORIGIN])
    # 0.445 km - 4.5*0.1 = -0.005 beats 0.334 despite being farther away
    assert ranked[0].name == "远高评分"
    assert ranked[1].name == "近无评分"


# --- build_food_item -------------------------------------------------------


def test_build_food_item_fills_fields():
    cand = RestaurantCandidate(
        name="楼外楼",
        poi_id="B0FF0123",
        location=GeoPoint(lon=120.15, lat=30.25),
        rating=4.7,
        biz_type="中餐厅",
    )
    item = build_food_item(
        cand, day=3, city="杭州", window=(time(11, 30), time(13, 30)), item_id="f-1"
    )
    assert isinstance(item, VisitItem)
    assert item.item_id == "f-1"
    assert item.name == "楼外楼"
    assert item.poi_id == "B0FF0123"
    assert item.category == "food"
    assert item.city == "杭州"
    assert item.location == GeoPoint(lon=120.15, lat=30.25)
    assert item.day == 3
    assert item.start_time == time(12, 30)  # window midpoint
    assert item.end_time == time(13, 30)
    assert item.duration_minutes == 60
    assert item.pinned is False


def test_build_food_item_uses_compressed_window_midpoint():
    # clamp: the meal never spills past the gap end (old behavior 13:00-14:00)
    cand = RestaurantCandidate(name="知味观")
    item = build_food_item(
        cand, day=1, city="杭州", window=(time(12, 30), time(13, 30)), item_id="f-2"
    )
    assert item.start_time == time(12, 30)
    assert item.end_time == time(13, 30)


def test_lunch_placeholder_prefix_detection():
    ph = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="杭州",
        day=1,
    )
    assert is_lunch_placeholder(ph)
    assert not is_lunch_placeholder(visit("v1"))


# --- search_restaurants ----------------------------------------------------


def test_search_restaurants_maps_pois_and_tolerates_missing_rating():
    stub = StubAmap(
        pois=[
            make_poi("近餐厅", lat=0.002, rating=4.5),
            make_poi("无评分餐厅", lat=0.05),  # rating key absent
            make_poi("无坐标餐厅", no_location=True),
            make_poi("字符串评分", lat=0.003, rating="4.6"),
        ]
    )
    out = asyncio.run(search_restaurants(stub, "杭州", anchor=ORIGIN))
    assert stub.calls == [("餐厅", "杭州")]
    assert [c.name for c in out] == ["近餐厅", "无评分餐厅", "无坐标餐厅", "字符串评分"]
    assert out[0].poi_id == "poi-近餐厅"
    assert out[0].address == "近餐厅地址1号"
    assert out[0].opening_hours == "周一至周日 10:00-22:00"
    assert out[0].biz_type == "餐饮服务;中餐厅"
    assert out[0].rating == 4.5
    assert out[1].rating is None
    assert out[2].location is None and out[2].walk_minutes is None
    assert out[3].rating == 4.6  # numeric strings are coerced
    assert out[0].walk_minutes == 3  # ~222 m at 80 m/min


def test_search_restaurants_limit_caps_results():
    stub = StubAmap(pois=[make_poi(f"r{i}") for i in range(5)])
    out = asyncio.run(search_restaurants(stub, "杭州", limit=2))
    assert [c.name for c in out] == ["r0", "r1"]


def test_search_restaurants_degrades_to_empty():
    assert asyncio.run(search_restaurants(None, "杭州")) == []
    broken = StubAmap(error=RuntimeError("amap down"))
    assert asyncio.run(search_restaurants(broken, "杭州")) == []


# --- recommend_restaurants -------------------------------------------------


def test_recommend_restaurants_builds_food_items_inside_window():
    stub = StubAmap(
        pois=[
            make_poi("远处餐厅", lat=0.05),
            make_poi("顺路餐厅", lat=0.002),
            make_poi("无坐标餐厅", no_location=True),
        ]
    )
    plan = day_plan(
        day=2,
        items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)],
    )
    items = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert stub.calls == [("餐厅", "杭州")]
    assert len(items) == 3
    # ranking order: detour puts the on-the-way candidate first
    assert [i.name for i in items] == ["顺路餐厅", "远处餐厅", "无坐标餐厅"]
    for item in items:
        assert isinstance(item, VisitItem)
        assert item.category == "food"
        assert item.day == 2
        assert item.city == "杭州"
        # 2026-11-03 拍板：午餐默认 1.5h（90 分钟）
        assert item.duration_minutes == 90
        assert item.pinned is False
        assert item.start_time == time(12, 0)  # pulled back so 90 min fits the gap
        assert item.end_time == time(13, 30)
    assert len({i.item_id for i in items}) == 3
    assert items[2].location is None  # location-less candidate stays addable
    assert items[0].address == "顺路餐厅地址1号"  # address rides along to the item
    assert items[0].opening_hours == "周一至周日 10:00-22:00"


def test_recommend_restaurants_city_override_beats_base_city():
    stub = StubAmap(pois=[make_poi("本帮菜")])
    plan = day_plan(day=1, base_city="杭州")
    items = asyncio.run(recommend_restaurants(stub, plan, "dinner", city="上海"))
    assert stub.calls == [("餐厅", "上海")]
    assert items and items[0].city == "上海"


def test_recommend_restaurants_no_free_window_returns_empty():
    stub = StubAmap(pois=[make_poi("随便吃")])
    plan = day_plan(
        items=[
            visit("v1", start=time(11, 30), end=time(12, 30)),
            visit("v2", start=time(12, 30), end=time(13, 30)),
        ]
    )
    assert asyncio.run(recommend_restaurants(stub, plan, "lunch")) == []
    assert stub.calls == []  # iron rule 20: never even search without a gap


def test_recommend_restaurants_amap_failure_returns_empty():
    plan = day_plan()
    broken = StubAmap(error=RuntimeError("amap down"))
    assert asyncio.run(recommend_restaurants(broken, plan, "lunch")) == []
    assert asyncio.run(recommend_restaurants(None, plan, "lunch")) == []


def test_recommend_restaurants_returns_fewer_when_few_hits():
    stub = StubAmap(pois=[make_poi("独一家", lat=0.001)])
    plan = day_plan()
    items = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert len(items) == 1
    assert items[0].name == "独一家"


def test_recommend_restaurants_drops_far_located_candidates_when_route_known():
    # 跨城错排闸（2026-10-31 沪→西安案）：有当日动线坐标时，已知坐标
    # 候选距动线 ≥50km 不推荐；无坐标候选无法判定，维持垫底保留。
    stub = StubAmap(
        pois=[
            make_poi("千里之外餐厅", lat=0.5),  # ~55.6km，跨城错排信号
            make_poi("顺路餐厅", lat=0.002),
            make_poi("无坐标餐厅", no_location=True),
        ]
    )
    plan = day_plan(
        day=1,
        items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)],
    )
    items = asyncio.run(recommend_restaurants(stub, plan, "dinner"))
    assert [i.name for i in items] == ["顺路餐厅", "无坐标餐厅"]


def test_recommend_restaurants_keeps_far_candidates_without_route_points():
    # 无动线坐标（纯过境日）：顺路语义无从判定，50km 闸不启用
    stub = StubAmap(pois=[make_poi("远处餐厅", lat=0.5)])
    items = asyncio.run(recommend_restaurants(stub, day_plan(), "dinner"))
    assert [i.name for i in items] == ["远处餐厅"]


# --- DB 荐点餐厅并池 + 晚餐优先 + 时段要求闸（2026-11-07 用户指令） --------


def _db_rec_poi(name, *, rec=True, hours=None, hint=None, lon=None, lat=None):
    """recommendation_food_in_city 形状的 DB hit（荐点餐厅）。"""
    return {
        "source_poi_id": f"curated:成都:{name}",
        "name": name,
        "city": "杭州",
        "category": "food",
        "address": None,
        "opening_hours": hours,
        "best_visit_time": None,
        "rating": None,
        "location": None if lon is None else (lon, lat),
        "suggested_duration_min": hint,
        "rec_tagged": rec,
    }


def test_recommend_restaurants_merges_db_rec_food_without_amap_hit():
    """任务1：带荐点标的 DB 餐厅不经 amap 关键词搜索直接进槽（红鼎宴/
    失重餐厅类点名店 live 搜索覆盖不到）；无坐标骨架行照回（垫底带）。"""
    stub = StubAmap(pois=[make_poi("顺路餐厅", lat=0.002)])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    items = asyncio.run(
        recommend_restaurants(stub, plan, "dinner", extra_pois=[_db_rec_poi("红鼎宴")])
    )
    names = [i.name for i in items]
    assert "红鼎宴" in names and "顺路餐厅" in names
    hong = next(i for i in items if i.name == "红鼎宴")
    assert hong.category == "food" and hong.location is None


def test_dinner_rec_bonus_prefers_tagged_over_closer_untagged():
    """任务3：dinner 槽位荐点标候选享 REC_DINNER_BONUS_KM 优先——约
    1.1km 外的荐点店赢 0.2km 顺路无标店；lunch 同场景不享受优先。"""
    close_plain = make_poi("顺路餐厅", lat=0.002)
    stub = StubAmap(pois=[close_plain])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    extra = [_db_rec_poi("红鼎宴", lon=0.0, lat=0.01)]
    dinner = asyncio.run(recommend_restaurants(stub, plan, "dinner", extra_pois=extra))
    assert dinner[0].name == "红鼎宴"
    lunch = asyncio.run(recommend_restaurants(stub, plan, "lunch", extra_pois=extra))
    assert lunch[0].name == "顺路餐厅"


def test_evening_only_rec_food_excluded_at_lunch_kept_at_dinner():
    """任务3 时段要求闸：营业时间推仅晚市（17:00-23:00 餐秀类）→
    午餐槽剔除、晚餐槽保留——「check if there is timing requirement」。"""
    stub = StubAmap(pois=[make_poi("顺路餐厅", lat=0.002)])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    extra = [_db_rec_poi("红鼎宴", hours="周一至周日 17:00-23:00")]
    lunch = asyncio.run(recommend_restaurants(stub, plan, "lunch", extra_pois=extra))
    assert [i.name for i in lunch] == ["顺路餐厅"]
    dinner = asyncio.run(recommend_restaurants(stub, plan, "dinner", extra_pois=extra))
    assert "红鼎宴" in [i.name for i in dinner]


def test_dinner_show_duration_hint_extends_and_clamps():
    """任务3 时长 hint：DB suggested_duration_min=120 的餐秀入卡 120
    分钟占满晚餐窗（17:30-19:30）；窗被压缩到 90 分钟时钳回 90，绝不
    溢出铁律 20 空窗。"""
    stub = StubAmap(pois=[])
    plan = day_plan(day=1)
    items = asyncio.run(
        recommend_restaurants(
            stub, plan, "dinner", extra_pois=[_db_rec_poi("红鼎宴", hint=120)]
        )
    )
    assert items[0].duration_minutes == 120
    assert items[0].start_time == time(17, 30) and items[0].end_time == time(19, 30)
    # 压缩窗：19:00 后被占 → gap 17:30-19:00=90 → 钳 90
    plan2 = day_plan(
        day=1,
        items=[visit("v1", start=time(19, 0), end=time(21, 0))],
    )
    items2 = asyncio.run(
        recommend_restaurants(
            stub, plan2, "dinner", extra_pois=[_db_rec_poi("红鼎宴", hint=120)]
        )
    )
    assert items2[0].duration_minutes == 90
    assert items2[0].end_time == time(19, 0)


def test_db_rec_food_dedup_against_amap_twin_keeps_vendor_fields():
    """同名双源去重：图商实时字段（坐标/poi_id）赢，不产生双卡。"""
    stub = StubAmap(pois=[make_poi("红鼎宴", lat=0.002, poi_id="amap-uid-1")])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    items = asyncio.run(
        recommend_restaurants(stub, plan, "dinner", extra_pois=[_db_rec_poi("红鼎宴")])
    )
    twins = [i for i in items if i.name == "红鼎宴"]
    assert len(twins) == 1
    assert twins[0].poi_id == "amap-uid-1"
    assert twins[0].location is not None


def test_lunch_slot_fitness_gates_evening_only_amap_candidate_too():
    """时段闸对图商候选同款生效：amap 回包带仅晚市营业时间的餐厅
    不进午餐槽（顺手收口——并池前 live 候选无槽位适性判定）。"""
    stub = StubAmap(pois=[make_poi("夜市烧烤", lat=0.002, rating=4.9)])
    for poi in stub._pois:
        poi["opening_hours"] = "周一至周日 17:00-23:00"
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    lunch = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert lunch == []
    dinner = asyncio.run(recommend_restaurants(stub, plan, "dinner"))
    assert [i.name for i in dinner] == ["夜市烧烤"]


def test_far_rec_food_skipped_at_lunch_saved_for_dinner():
    """午餐顺路闸（2026-11-07 用户指令「餐厅也要考虑距离，如果距离近
    可以放中午」）：点名店距午间动线 ≥REC_LUNCH_NEAR_KM 不硬灌午餐
    （防唯一候选被强吃），留给晚餐；近距离（<3km）照常可进午餐。"""
    close_plain = make_poi("顺路餐厅", lat=0.002)
    stub = StubAmap(pois=[close_plain])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    far = _db_rec_poi("远点名店", lon=0.0, lat=0.09)  # ~10km
    lunch = asyncio.run(recommend_restaurants(stub, plan, "lunch", extra_pois=[far]))
    assert [i.name for i in lunch] == ["顺路餐厅"]
    dinner = asyncio.run(recommend_restaurants(stub, plan, "dinner", extra_pois=[far]))
    assert "远点名店" in [i.name for i in dinner]
    # 近点名店：午餐照进（顺路可午饭）
    near = _db_rec_poi("近点名店", lon=0.0, lat=0.01)  # ~1.1km
    lunch2 = asyncio.run(recommend_restaurants(stub, plan, "lunch", extra_pois=[near]))
    assert "近点名店" in [i.name for i in lunch2]


def test_evening_only_show_dinner_beats_closer_plain_restaurant():
    """仅晚市餐秀强拉力（2026-11-07 用户指令「restaurant 演出只有晚上
    应该优先晚餐」）：5km 外的时段锁死晚餐的荐点餐秀赢 0.2km 顺路普通
    店（REC_SHOW_DINNER_BONUS_KM=10 > 4.8km 距离差）；普通荐点同场景
    仍按 3km 档不越界。"""
    close_plain = make_poi("顺路餐厅", lat=0.002, rating=4.9)
    stub = StubAmap(pois=[close_plain])
    plan = day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )
    show = _db_rec_poi("红鼎宴", lon=0.0, lat=0.045, hours="周一至周日 17:00-23:00")
    dinner = asyncio.run(recommend_restaurants(stub, plan, "dinner", extra_pois=[show]))
    assert dinner[0].name == "红鼎宴"
    # 普通荐点（非仅晚市）3km 档：5km 外赢不了 0.2km 顺路店
    plain_tagged = _db_rec_poi("远点名店", lon=0.0, lat=0.045)
    dinner2 = asyncio.run(
        recommend_restaurants(stub, plan, "dinner", extra_pois=[plain_tagged])
    )
    assert dinner2[0].name == "顺路餐厅"


# --- 近簇硬闸 + 簇锚检索 + 多类型/评分差排序（2026-11-13 用户拍板） --------
# 场景：当天景点成簇在远郊（距市区几十公里），午餐不得落到市区——普通
# 候选距当天动线最近点 >8km 一律剔除（网红店放宽 15km），无回落宁缺。


# 1 度纬度 ~111.19km：0.071≈7.9km / 0.081≈9.0km / 0.108≈12.0km /
# 0.144≈16.0km / 0.369≈41.0km
def _routed_plan():
    return day_plan(
        day=1, items=[visit("v1", start=time(9, 0), end=time(11, 0), location=ORIGIN)]
    )


def test_meal_gate_drops_plain_beyond_8km_keeps_within():
    """普通候选 9km 剔除 / 7.9km 保留（8km 硬闸边界，无回落兜底）。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005),  # ~0.6km
            make_poi("闸内店", lat=0.071),  # ~7.9km
            make_poi("闸外店", lat=0.081),  # ~9.0km
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    names = [i.name for i in items]
    assert "闸外店" not in names
    assert names[:2] == ["簇近店", "闸内店"]


def test_meal_gate_drops_city_restaurant_40km_from_cluster():
    """远郊成簇日回归：景点簇旁有候选时，41km 外市区店不得中选。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005),
            make_poi("远市区店", lat=0.369),  # ~41km，50km 旧闸内但 8km 闸外
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert [i.name for i in items] == ["簇近店"]


def test_meal_gate_empty_after_gate_returns_empty():
    # 宁缺：闸内无候选 → 返回 []，调用方走既有占位/不插路径
    stub = StubAmap(pois=[make_poi("远市区店", lat=0.369)])
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert items == []


def test_viral_within_15km_wins_with_rating_edge():
    """网红店距离闸放宽到 15km：12km 网红店评分比近选中选者高 0.4
    （≥0.3 评分差）→ 越前中选。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005, rating=4.0),
            make_poi("网红食堂", lat=0.108, rating=4.4),  # ~12.0km
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert items[0].name == "网红食堂"


def test_viral_beyond_15km_dropped():
    """网红店 16km 外仍剔除（15km 是网红档最后一道闸）。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005, rating=4.0),
            make_poi("网红食堂", lat=0.144, rating=4.9),  # ~16.0km
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert [i.name for i in items] == ["簇近店"]


def test_viral_with_small_rating_edge_loses_to_near():
    """评分差 0.1 < 0.3：网红店（5.6km，闸内）败给 8km 内近店。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005, rating=4.0),
            make_poi("网红食堂", lat=0.05, rating=4.1),  # ~5.6km
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert items[0].name == "簇近店"


def test_typed_candidate_beats_untyped_at_same_distance_band():
    """多类型优先：同距离档内带 cuisine_group 类型标签的候选优先于
    无类型候选（映射复用 cuisine_taxonomy 现成词表）。"""
    untyped = make_poi("无类型店", lat=0.004)  # ~0.44km 更近
    untyped["category"] = None
    typed = make_poi("火锅小店", lat=0.005)  # ~0.56km 稍远但带类型
    typed["category"] = "餐饮服务;中餐厅;火锅店"
    stub = StubAmap(pois=[untyped, typed])
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert items[0].name == "火锅小店"


def test_only_viral_left_is_directly_selectable():
    """无普通候选可中时（闸内只剩网红店）网红店直接可选，无需比较。"""
    stub = StubAmap(pois=[make_poi("网红食堂", lat=0.03, rating=4.2)])
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert [i.name for i in items] == ["网红食堂"]


def test_meal_gate_ignores_viral_tags_honor_mark():
    """网红信号复用现成 tags 荣誉标：普通名但 tags 带 michelin 标 +
    高评分差 → 享受 15km 网红档与越前规则。"""
    honored = make_poi("巷里小馆", lat=0.108, rating=4.5)  # ~12.0km
    honored["tags"] = ["michelin_1star"]
    stub = StubAmap(pois=[make_poi("簇近店", lat=0.005, rating=4.0), honored])
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert items[0].name == "巷里小馆"


class StubAmapAround(StubAmap):
    """带 /place/around 能力的 stub：记录簇锚检索入参。"""

    def __init__(self, pois=None, error=None, around_error=None):
        super().__init__(pois=pois, error=error)
        self.around_calls = []
        self._around_error = around_error

    async def search_poi_around(
        self, keywords, *, location, radius=30000, page=1, offset=25
    ):
        self.around_calls.append((keywords, location, radius))
        if self._around_error is not None:
            raise self._around_error
        return self._pois


def test_recommend_uses_cluster_anchor_for_around_search():
    """簇锚传检索：当天景点簇质心作为 around 检索位置，半径覆盖网红档
    （15km）；支持 around 的客户端不再走无偏置 text 检索。"""
    stub = StubAmapAround(pois=[make_poi("簇近店", lat=0.005)])
    plan = day_plan(
        day=1,
        items=[
            visit("v1", start=time(9, 0), end=time(10, 0), location=ORIGIN),
            visit(
                "v2",
                start=time(10, 0),
                end=time(11, 0),
                location=GeoPoint(lon=0.0, lat=0.01),
            ),
        ],
    )
    items = asyncio.run(recommend_restaurants(stub, plan, "lunch"))
    assert items and items[0].name == "簇近店"
    assert len(stub.around_calls) == 1
    keywords, location, radius = stub.around_calls[0]
    assert keywords == "餐厅"
    assert location == "0.000000,0.005000"  # 两景点质心
    assert radius == 15000
    assert stub.calls == []  # around 命中即不走 text


def test_around_failure_falls_back_to_text_search():
    """around 失败自动回退 text 原路径（独立配额池，行为不退化）。"""
    stub = StubAmapAround(
        pois=[make_poi("簇近店", lat=0.005)], around_error=RuntimeError("around down")
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "lunch"))
    assert [i.name for i in items] == ["簇近店"]
    assert len(stub.around_calls) == 1
    assert stub.calls == [("餐厅", "杭州")]


def test_meal_gate_and_viral_edge_apply_to_dinner_too():
    """午/晚餐同一套规则（2026-11-13 拍板收口）：晚餐槽同吃 8km 普通
    硬闸 + 网红 15km 放宽 + 评分差 ≥0.3 越前。"""
    stub = StubAmap(
        pois=[
            make_poi("簇近店", lat=0.005, rating=4.0),
            make_poi("闸外店", lat=0.081),  # ~9.0km 普通 → 剔除
            make_poi("网红食堂", lat=0.108, rating=4.4),  # ~12.0km 网红 → 越前
        ]
    )
    items = asyncio.run(recommend_restaurants(stub, _routed_plan(), "dinner"))
    names = [i.name for i in items]
    assert "闸外店" not in names
    assert names[0] == "网红食堂"
