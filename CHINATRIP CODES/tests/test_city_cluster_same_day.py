# -*- coding: utf-8 -*-
"""城心簇同日连排（2026-11-08 西安案：钟楼/城墙/永宁门/碑林拆两天）。

用户拍板「距离聚合都是近距离聚合优先」：0.5-2km 强簇斗得过 4.6-5km
压线弱边。四路收口锚——
① 下午单大点贴邻豁免全引擎同步（solver CP/插入/打磨 + scoring；
   此前仅 plan 兜底有豁免——城墙180+碑林博90 贴邻同日被四路计罚 →
   untimed → 挪日 → 让位链删件，session bf4c8340 实录）；
② 让位弹座紧簇保护（碑林博为钟楼让位后无处可排被删实录）；
③ 挪日宿主簇领地排序（碑林博被 4.97km 压线弱边天抢先收走）；
④ 认领紧簇 kin（10km 粗簇让大雁塔↔钟楼 6.1km 同簇是拆城心簇的
   通道，回归见 test_priority_early）。
"""

from datetime import time

from app.services.agent.plan import _host_day_for_visit, _tight_cluster_mate_on
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    VisitItem,
)
from app.services.itinerary.scoring import plan_score
from app.services.itinerary.solver import (
    _adjacent_big_ids,
    _haversine_km,
    solve_day,
)

# 西安锚点（按 bf4c8340 实测距离矩阵布点：城心簇两两 <2km；大雁塔压线
# 弱边 ~5km；大明宫圈外 ~7km）
_ZL = GeoPoint(lon=108.9398, lat=34.2610)  # 西安钟楼（城心簇）
_BL = GeoPoint(lon=108.9397, lat=34.2565)  # 西安碑林博物馆（↔钟楼 ~0.5km）
_CQ = GeoPoint(lon=108.9405, lat=34.2540)  # 西安城墙永宁门段（↔碑林 ~0.3km）
_DYT = GeoPoint(lon=108.9674, lat=34.2153)  # 大雁塔（↔永宁门段 ~5.0km 压线）
_DMG = GeoPoint(lon=108.9639, lat=34.3150)  # 大明宫（↔城心簇 ~7km 圈外）
_ALL_DAY = PoiHours(poi_id="p_all", opens=time(9, 0), closes=time(21, 0))


def _big(name: str, dur: int, loc: GeoPoint | None) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="西安",
        day=1,
        duration_minutes=dur,
        location=loc,
    )


def test_anchor_geometry_matches_incident():
    """布点自检：城心簇两两紧簇（<2km），大雁塔压线弱边（≤5km 进同日
    圈），钟楼↔大雁塔出圈（>5km）——与 bf4c8340 实测矩阵同构。"""
    assert _haversine_km(_ZL, _BL) < 2.0
    assert _haversine_km(_CQ, _BL) < 2.0
    assert _haversine_km(_CQ, _DYT) <= 5.0
    assert _haversine_km(_ZL, _DYT) > 5.0
    assert _haversine_km(_CQ, _DMG) > 5.0


def test_adjacent_big_ids_pairwise_circle():
    wall = _big("西安城墙", 180, _CQ)
    beilin = _big("西安碑林博物馆", 90, _BL)
    damingong = _big("大明宫旅游景区", 120, _DMG)
    noloc = _big("无坐标大点", 90, None)
    # 贴邻对（圈内）双双豁免——同片区连游不计「第二个下午大点」
    assert _adjacent_big_ids([wall, beilin]) == {id(wall), id(beilin)}
    # 圈外大点不豁免；缺坐标保守不豁免
    assert _adjacent_big_ids([wall, damingong]) == set()
    assert _adjacent_big_ids([wall, beilin, noloc]) == {id(wall), id(beilin)}


def test_solver_times_adjacent_big_pair_same_day():
    """城墙180+碑林博90+钟楼45 同日全排上时刻（solver CP 贴邻豁免冒烟：
    贴邻大点对不再吃 1e6 罚被逼出当日）。"""
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            VisitItem(
                item_id="v-cq",
                name="西安城墙",
                city="西安",
                day=1,
                duration_minutes=180,
                location=_CQ,
                poi_id="p_all",
            ),
            VisitItem(
                item_id="v-bl",
                name="西安碑林博物馆",
                city="西安",
                day=1,
                duration_minutes=90,
                location=_BL,
                poi_id="p_all",
            ),
            VisitItem(
                item_id="v-zl",
                name="西安钟楼",
                city="西安",
                day=1,
                duration_minutes=45,
                location=_ZL,
                poi_id="p_all",
            ),
        ],
    )
    solved = solve_day(day, poi_hours=[_ALL_DAY])
    assert solved is not None
    assert all(i.start_time is not None for i in solved.items)


def test_scoring_no_afternoon_crowd_for_adjacent_bigs():
    """评分器镜像（LNS 评估地基）：贴邻大点对同日下午不计超点——修复
    前 afternoon_crowd=1，LNS 会把碑林博从城墙日挪走=城心簇拆天。"""

    def _plan(second_loc: GeoPoint, second_name: str) -> ItineraryPlan:
        return ItineraryPlan(
            itinerary_id="p",
            cities=["西安"],
            days=[
                DayPlan(
                    day=1,
                    base_city="西安",
                    items=[
                        VisitItem(
                            item_id="v-cq",
                            name="西安城墙",
                            city="西安",
                            day=1,
                            duration_minutes=90,
                            location=_CQ,
                            start_time=time(13, 0),
                            end_time=time(14, 30),
                        ),
                        VisitItem(
                            item_id="v-2nd",
                            name=second_name,
                            city="西安",
                            day=1,
                            duration_minutes=90,
                            location=second_loc,
                            start_time=time(14, 30),
                            end_time=time(16, 0),
                        ),
                    ],
                )
            ],
        )

    near = plan_score(_plan(_BL, "西安碑林博物馆"))
    assert near.counts["afternoon_crowd"] == 0
    far = plan_score(_plan(_DMG, "大明宫旅游景区"))
    assert far.counts["afternoon_crowd"] == 1


def test_tight_cluster_mate_protection():
    """弹座紧簇保护：候选与同日任一其他参访在 2km 紧簇内=强簇员不让
    弹座；压线弱边（4.97km）不是紧簇员照常可弹。"""
    zhonglou = _big("西安钟楼", 45, _ZL)
    beilin = _big("西安碑林博物馆", 90, _BL)
    dayan = _big("大雁塔", 120, _DYT)
    day = DayPlan(day=1, base_city="西安", items=[zhonglou, beilin, dayan])
    assert _tight_cluster_mate_on(day, beilin)  # ↔钟楼 0.5km 强簇员
    assert not _tight_cluster_mate_on(day, dayan)  # ↔最近 4.97km 弱边


def test_host_day_prefers_cluster_territory_over_day_order():
    """挪日宿主簇领地排序：碑林博找宿主天时，城心簇天（钟楼在册，
    0.5km）先于更早日序的压线弱边天（大雁塔在册，4.97km）——修复前
    按天序 first-fit 把碑林博送进大雁塔日，城心簇因此拆散。"""
    dayan_day = DayPlan(
        day=1,
        base_city="西安",
        items=[_big("大雁塔", 120, _DYT)],
    )
    center_day = DayPlan(
        day=2,
        base_city="西安",
        items=[_big("西安钟楼", 45, _ZL)],
    )
    host = _host_day_for_visit(
        [dayan_day, center_day],
        "西安",
        90,
        incoming=_BL,
        visit=_big("西安碑林博物馆", 90, _BL),
    )
    assert host is center_day
    # 无圈内天时维持原日序（first-fit 不变形）
    other_city_day = DayPlan(
        day=1,
        base_city="西安",
        items=[_big("大明宫旅游景区", 120, _DMG)],
    )
    other_center = DayPlan(
        day=2,
        base_city="西安",
        items=[_big("大明宫遗址公园", 120, _DMG)],
    )
    host2 = _host_day_for_visit(
        [other_city_day, other_center],
        "西安",
        90,
        incoming=_BL,
        visit=_big("西安碑林博物馆", 90, _BL),
    )
    assert host2 is other_city_day
