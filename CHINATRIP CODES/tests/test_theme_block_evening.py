"""主题街区整类开晚场 + 晚锚右贴压缩（2026-11-08 拍板）。

用户判词：长安十二时辰是 EVENING EVENT，白天闸把它压成 12:30-16:30；
三连拍定调——「有些主题街区不是夜间，可以白天的啊」→「所有街区都可
以作为夜场，也可以白天」→「但是十二时辰建议晚上」。类级口径：

1. 整类豁免白天入场闸（16:00 开场闸/15:30 大点带都不吃）——街区可夜
   可昼，solver.generic_entry_cap / 选层 _cand_entry_cap / 评分器
   late_entries 三镜像同口径；
2. 「建议晚上」由软偏好表达（规则 33 ≥16:00 倾向 + 夜组贴排夜侧扩面
   + 兜底 16:00 地板），不硬编码站点；
3. 晚场锚前的下午死区整链右贴压缩（长恨歌案：清真寺 90min 后 203min
   空洞 vs 17:00 演出）——链上白天闸件钳 delta，返程日跳过。
"""

from datetime import time

from app.services.agent.plan import (
    _compress_before_evening_anchor,
    _fallback_sequence_times,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import travel_gap_needed
from app.services.itinerary.scoring import plan_score
from app.services.itinerary.solver import (
    _night_combo_pairs,
    _visit_spec,
    generic_entry_cap,
    solve_day,
)


def _visit(item_id, *, dur=60, city="西安", **kw) -> VisitItem:
    fields = dict(
        item_id=item_id,
        name=item_id,
        city=city,
        day=1,
        duration_minutes=dur,
    )
    fields.update(kw)
    return VisitItem(**fields)


def _block(dur=240, item_id="blk"):
    """长安十二时辰·11-08 类目翻转后真实形态：category=citywalk、无
    bvt、名含「街区」——三张旧豁免面（bvt/entertainment/夜馆时段）全
    miss 的那一种。"""
    return _visit(
        item_id,
        dur=dur,
        name="长安十二时辰主题街区",
        category="citywalk",
    )


def _sight(item_id="sight", dur=60, **kw):
    return _visit(item_id, dur=dur, category="attraction", **kw)


# ---------- ① 入场闸豁免（solver 口径） ----------


def test_cap_theme_block_exempt_in_flipped_shape():
    """翻转形态（citywalk/无 bvt/240min）不吃任何白天闸——修复前它被
    _is_big_site 当大点压 15:30。"""
    assert generic_entry_cap(_block(), None) is None
    assert generic_entry_cap(_block(), None) != 15 * 60 + 30  # 大点带不适用


def test_cap_plain_sight_unchanged():
    assert generic_entry_cap(_sight(dur=60), None) == 16 * 60
    assert generic_entry_cap(_sight(dur=120), None) == 15 * 60 + 30


def test_cp_block_runs_into_evening():
    """240min 街块从 16:00 开到 20:00 合法（时长跨 16:00 不再被闸）。"""
    blk = _block()
    hours = [PoiHours(poi_id="blk", opens=time(10, 0), closes=time(22, 0))]
    day = DayPlan(day=1, base_city="西安", items=[blk])
    solved = solve_day(day, poi_hours=hours)
    assert solved is not None
    assert solved.items[0].start_time == time(16, 0)  # 规则 33 软偏好
    assert solved.items[0].end_time == time(20, 0)


# ---------- ② 夜组贴排夜侧扩面 ----------


def test_night_combo_pairs_block_night_side():
    """无 bvt 的街块可作夜侧（大雁塔 13:00-16:00 → 街块 16:00-20:00
    形态的贴排绑定）——修复前 bvt 门把翻转后的块挡在夜组外。"""
    pagoda = _sight("pagoda", dur=180)
    from app.services.itinerary.models import GeoPoint

    pagoda.location = GeoPoint(lon=108.96, lat=34.22)
    blk = _block()
    blk.location = GeoPoint(lon=108.965, lat=34.222)  # ≈0.5km 内
    hours = {}
    specs = [_visit_spec(v, hours) for v in (pagoda, blk)]
    assert specs[0] is not None and specs[1] is not None
    pairs = _night_combo_pairs(specs)
    assert (0, 1) in pairs  # a=大雁塔 贴排在街块开场前收尾


def test_night_combo_pairs_block_never_day_anchor():
    """街块不当白日锚（自己的夜侧候选身份优先）。"""
    from app.services.itinerary.models import GeoPoint

    blk = _block()
    blk.location = GeoPoint(lon=108.96, lat=34.22)
    blk2 = _visit("blk2", dur=120, name="另一主题街区", category="citywalk")
    blk2.location = GeoPoint(lon=108.962, lat=34.221)
    evening = _visit("night", dur=60, best_visit_time="evening")
    evening.location = GeoPoint(lon=108.961, lat=34.2205)
    specs = [_visit_spec(v, {}) for v in (blk, blk2, evening)]
    pairs = _night_combo_pairs(specs)
    # evening 的白日锚不会选街块（blk/blk2 都被排除），无处可绑
    assert (0, 2) not in pairs
    assert (1, 2) not in pairs


# ---------- ③ 兜底 16:00 地板（安全升级） ----------


def _plan_with(*items):
    day = DayPlan(day=1, base_city="西安", items=list(items))
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])


def test_fallback_theme_block_floor_16():
    """兜底游标把街块塞上午时升档 16:00（「建议晚上」的降级路镜像）；
    升档失败（此处不会）保留游标位——永不因地板丢安置。"""
    m = _sight("m", dur=90)
    m.start_time, m.end_time = time(9, 0), time(10, 30)
    blk = _block()
    plan = _plan_with(m, blk)
    _fallback_sequence_times(plan)
    assert blk.start_time == time(16, 0)
    assert blk.end_time == time(20, 0)


def test_fallback_plain_sight_no_floor():
    """普通观光点不吃地板（白天闸照卡）。"""
    m = _sight("m", dur=90)
    m.start_time, m.end_time = time(9, 0), time(10, 30)
    c = _sight("c", dur=90)
    plan = _plan_with(m, c)
    _fallback_sequence_times(plan)
    assert c.start_time == time(11, 0)  # 游标顺排，不升档


# ---------- ④ 晚锚右贴压缩 ----------


def _timed(v, sh, sm, eh, em):
    v.start_time, v.end_time = time(sh, sm), time(eh, em)
    return v


def test_compress_chain_against_evening_anchor():
    """长恨歌案形态：下午观光件与晚场锚间 203min+ 死区 → 右贴收紧；
    白天闸钳 delta（普通件最迟 16:00 开场——>80min 大点件另钳 15:30）。"""
    m = _timed(_sight("m", dur=90), 9, 0, 10, 30)
    c = _timed(_sight("c", dur=80), 12, 10, 13, 30)
    a = _visit("show", dur=80, best_visit_time="evening")
    _timed(a, 19, 0, 20, 20)
    plan = _plan_with(m, c, a)
    _compress_before_evening_anchor(plan)
    assert c.start_time == time(16, 0)  # delta 被闸钳到 16:00 开场
    assert c.end_time == time(17, 20)
    assert m.start_time == time(9, 0)  # 晨件不动


def test_compress_theme_block_is_anchor():
    """街块自己是晚锚（17:00-21:00 场形态）。"""
    c = _timed(_sight("c", dur=90), 13, 40, 15, 10)
    blk = _timed(_block(dur=240), 17, 0, 21, 0)
    plan = _plan_with(c, blk)
    _compress_before_evening_anchor(plan)
    assert c.start_time == time(15, 0)  # 贴锚留 30min 通勤
    assert c.end_time == time(16, 30)
    assert blk.start_time == time(17, 0)  # 锚不动


def test_compress_uses_canonical_gap_beyond_short_leg_floor():
    c = _timed(_sight("c", dur=60), 12, 0, 13, 0)
    c.location = GeoPoint(lon=108.9, lat=34.2)
    a = _visit("show", dur=80, best_visit_time="evening")
    a.location = GeoPoint(lon=108.965, lat=34.2)
    _timed(a, 17, 0, 18, 20)
    plan = _plan_with(c, a)
    need = travel_gap_needed(c, a)
    assert need is not None and need > 30
    _compress_before_evening_anchor(plan)
    actual_gap = (
        a.start_time.hour * 60
        + a.start_time.minute
        - c.end_time.hour * 60
        - c.end_time.minute
    )
    assert actual_gap == need


def test_compress_chain_breaks_at_food():
    """餐/酒店断链：只右贴餐后的尾段，餐不动。"""
    lunch = _timed(_visit("lunch", dur=90, category="food"), 12, 0, 13, 30)
    c = _timed(_sight("c", dur=80), 13, 40, 15, 0)
    a = _timed(_visit("show", dur=80, best_visit_time="evening"), 19, 0, 20, 20)
    plan = _plan_with(lunch, c, a)
    _compress_before_evening_anchor(plan)
    assert c.start_time == time(16, 0)
    assert lunch.start_time == time(12, 0)  # 餐不动


def test_compress_skips_departure_afternoon():
    """规则 21：午后城际腿当天=车站缓冲，不压缩。"""
    c = _timed(_sight("c", dur=90), 12, 10, 13, 40)
    a = _timed(_visit("show", dur=80, best_visit_time="evening"), 19, 0, 20, 20)
    tr = TransferItem(
        item_id="tr",
        day=1,
        seq=1,
        from_city="西安",
        to_city="上海",
        start_time=time(20, 30),
        end_time=time(23, 0),
    )
    plan = _plan_with(c, a, tr)
    _compress_before_evening_anchor(plan)
    assert c.start_time == time(12, 10)  # 零改动


def test_compress_zero_effect_on_small_gap():
    """死区 <60min 不值得动——零副作用。"""
    c = _timed(_sight("c", dur=90), 16, 30, 18, 0)
    a = _timed(_visit("show", dur=80, best_visit_time="evening"), 19, 0, 20, 20)
    plan = _plan_with(c, a)
    _compress_before_evening_anchor(plan)
    assert c.start_time == time(16, 30)


# ---------- ⑤ 评分器镜像 ----------


def test_scorer_late_entry_exempt_theme_block():
    blk = _timed(_block(), 17, 0, 21, 0)
    sc = plan_score(_plan_with(blk))
    assert sc.counts["late_entries"] == 0


def test_scorer_late_entry_plain_sight_still_counted():
    c = _timed(_sight("c", dur=90), 17, 0, 18, 30)
    sc = plan_score(_plan_with(c))
    assert sc.counts["late_entries"] == 1
