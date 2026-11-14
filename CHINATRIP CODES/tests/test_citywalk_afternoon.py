"""CITYWALK 下午场 + 街区型演出块 16:00 后（2026-11-06 二拍）。

用户拍板：「CITYWALK倾向于下午场。像长安十二时辰，倾向于下午四点以后
第二场」。软偏好三路接线（不拦可行性）：

1. 普通街区（category=citywalk，回民街/磁器口类）开场 <13:00 计软罚
   ——CP lit ×100 / 插入 key 10_000 / 评分器 -12。
2. 街区型演出块（名含「街区」的演出/娱乐/街区行，长安十二时辰型沉浸
   街区）开场 <16:00 计软罚，同上量纲。
3. 与同日头拍「无场次演出不默认晚场」正交：头拍废的是硬窗（20:10
   开演域/17:00 地板），本拍是软倾向；pinned 有时刻豁免（铁律 19）。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score
from app.services.itinerary.solver import insertion_schedule_day, solve_day


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


def _citywalk(item_id="cw", dur=90):
    """普通街区（回民街形态：category=citywalk、名无「街区」二字）。"""
    return _visit(item_id, dur=dur, category="citywalk")


def _theme_block(item_id="blk", dur=80):
    """街区型演出块（长安十二时辰形态：名含「街区」+ 演出行、无场次）。"""
    return _visit(
        item_id,
        dur=dur,
        name="长安十二时辰主题街区",
        category="entertainment",
        best_visit_time="show",
    )


def _sight(item_id="sight", dur=60):
    return _visit(item_id, dur=dur, category="attraction")


def _starts(day):
    return {i.item_id: i.start_time for i in day.items if i.start_time is not None}


# ---------- CP 路 ----------


def test_cp_citywalk_pushed_to_afternoon():
    day = DayPlan(day=1, base_city="西安", items=[_citywalk()])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    starts = _starts(solved)
    assert starts["cw"] == time(13, 0)  # 下午场：不为早收工排上午


def test_cp_theme_block_pushed_after_16():
    day = DayPlan(day=1, base_city="西安", items=[_theme_block()])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    starts = _starts(solved)
    assert starts["blk"] == time(16, 0)  # 16:00 后开场
    assert starts["blk"] >= time(16, 0)


def test_cp_plain_sight_still_morning():
    day = DayPlan(day=1, base_city="西安", items=[_sight()])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    assert _starts(solved)["sight"] == time(9, 0)  # 普通观光点不吃街区罚


def test_cp_pinned_citywalk_untouched():
    cw = _citywalk()
    cw.pinned = True
    cw.start_time = time(10, 0)
    cw.end_time = time(11, 30)
    day = DayPlan(day=1, base_city="西安", items=[cw])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    assert _starts(solved)["cw"] == time(10, 0)  # 铁律 19：钉住不迁移


def test_cp_morning_sight_plus_afternoon_citywalk_shape():
    """目标形态：上午观光点 + 13:00 后街区——用户描述的下午场组合。"""
    day = DayPlan(day=1, base_city="西安", items=[_sight(dur=120), _citywalk()])
    solved = solve_day(day, poi_hours=[])
    assert solved is not None
    starts = _starts(solved)
    assert starts["sight"] == time(9, 0)
    assert starts["cw"] >= time(13, 0)


# ---------- 插入路 ----------


def test_insertion_citywalk_afternoon():
    day = DayPlan(day=1, base_city="西安", items=[_sight(dur=120), _citywalk()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    starts = _starts(solved)
    assert starts["sight"] == time(9, 0)  # 大点先插上午
    assert starts["cw"] == time(13, 0)  # 街区让上午、落下午场


def test_insertion_theme_block_after_16():
    day = DayPlan(day=1, base_city="西安", items=[_sight(dur=120), _theme_block()])
    solved = insertion_schedule_day(day, poi_hours=[])
    assert solved is not None
    starts = _starts(solved)
    assert starts["blk"] == time(16, 0)


# ---------- 评分器 ----------


def _scored(item: VisitItem) -> ItineraryPlan:
    item.start_time = item.start_time or time(9, 0)
    day = DayPlan(day=1, base_city="西安", items=[item])
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])


def test_scorer_citywalk_morning_penalty():
    cw = _citywalk()
    cw.start_time = time(10, 0)
    cw.end_time = time(11, 30)
    sc = plan_score(_scored(cw))
    assert sc.soft["citywalk_morning"] == -12
    assert sc.counts["citywalk_morning"] == 1


def test_scorer_citywalk_afternoon_zero():
    cw = _citywalk()
    cw.start_time = time(14, 0)
    cw.end_time = time(15, 30)
    sc = plan_score(_scored(cw))
    assert sc.soft["citywalk_morning"] == 0
    assert sc.counts["citywalk_morning"] == 0


def test_scorer_theme_block_early_penalty():
    blk = _theme_block()
    blk.start_time = time(15, 0)
    blk.end_time = time(16, 20)
    sc = plan_score(_scored(blk))
    assert sc.soft["theme_block_early"] == -12
    assert sc.counts["theme_block_early"] == 1


def test_scorer_theme_block_after_16_zero():
    blk = _theme_block()
    blk.start_time = time(16, 30)
    blk.end_time = time(17, 50)
    sc = plan_score(_scored(blk))
    assert sc.soft["theme_block_early"] == 0


def test_scorer_pinned_theme_block_exempt():
    blk = _theme_block()
    blk.pinned = True
    blk.start_time = time(10, 0)
    blk.end_time = time(11, 20)
    sc = plan_score(_scored(blk))
    assert sc.soft["theme_block_early"] == 0  # 铁律 19：钉住不罚


def test_scorer_sessionless_nonblock_show_stays_neutral():
    """无场次非街区演出（剧场形态）不受二拍影响：三罚全零——11-06 头拍
    「无场次按正常景点排」的中性面不被二拍收窄。"""
    show = _visit("theater", dur=80, category="entertainment", best_visit_time="show")
    show.name = "大唐芙蓉园剧场"
    show.start_time = time(10, 0)
    show.end_time = time(11, 20)
    sc = plan_score(_scored(show))
    assert sc.soft["early_show"] == 0  # 无场次：早场罚场次闸豁免
    assert sc.soft["theme_block_early"] == 0  # 名无「街区」：不进二拍
    assert sc.soft["citywalk_morning"] == 0
