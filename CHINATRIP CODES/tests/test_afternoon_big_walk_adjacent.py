# -*- coding: utf-8 -*-
"""下午单大点贴邻豁免（2026-11-07 钟楼/鼓楼/回民街同街拆天案）。

2026-11-04 拍板「同日下午已有大点，第二个留空交挪日」在兜底排序里是
硬跳过——鼓楼（90min 大点）与下午已排的回民街（90min 大点）直线
1.3km 在近距同日圈（_NEAR_SAMEDAY_KM，用户拍板 5km 口径）内，被当
「第二个下午大点」踢出当日交挪日链，同街三件拆成两天。圈内=同片区
连游，豁免跳过；圈外远距大点照旧跳过。
"""

from datetime import time

from app.services.agent.plan import _fallback_sequence_times
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

_HMJ = GeoPoint(lon=108.9326, lat=34.2680)  # 回民街
_GL = GeoPoint(lon=108.9435, lat=34.2602)  # 鼓楼（钟楼旁，~1.3km）
_FAR = GeoPoint(lon=108.9639, lat=34.3150)  # 大明宫北（~6km，近距同日圈外）


def _plan(far_second: bool) -> ItineraryPlan:
    second_loc = _FAR if far_second else _GL
    second_name = "大明宫旅游景区" if far_second else "西安鼓楼"
    return ItineraryPlan(
        itinerary_id="p",
        cities=["西安"],
        days=[
            DayPlan(
                day=4,
                base_city="西安",
                items=[
                    # 上午已排大点（堵死上午空档）+ 下午已排大点（回民街）
                    # ——无时段大点被逼进下午，才走到「第二个下午大点」
                    # 跳过分支。
                    VisitItem(
                        item_id="v-cq",
                        name="西安城墙",
                        city="西安",
                        day=4,
                        duration_minutes=180,
                        location=GeoPoint(lon=108.9405, lat=34.2504),
                        start_time=time(9, 0),
                        end_time=time(12, 0),
                    ),
                    VisitItem(
                        item_id="v-hmj",
                        name="回民街",
                        city="西安",
                        day=4,
                        duration_minutes=90,
                        location=_HMJ,
                        start_time=time(13, 0),
                        end_time=time(14, 30),
                    ),
                    VisitItem(
                        item_id="v-gl",
                        name=second_name,
                        city="西安",
                        day=4,
                        duration_minutes=90,
                        location=second_loc,
                    ),
                ],
            )
        ],
    )


def test_walk_adjacent_second_big_stays_same_day():
    plan = _plan(far_second=False)
    _fallback_sequence_times(plan)
    drum = next(
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.name == "西安鼓楼"
    )
    # 贴邻大点不再被「第二个下午大点」跳过：当日排出时刻
    # （上午有空排上午，游标被占则顺延——同日在册即达标）
    assert drum.start_time is not None
    assert drum.start_time <= time(16, 30)  # 白天入场闸内


def test_far_second_big_still_skipped():
    plan = _plan(far_second=True)
    _fallback_sequence_times(plan)
    far = next(
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.name == "大明宫旅游景区"
    )
    # 步行圈外的第二个下午大点维持 11-04 拍板：留空交挪日/披露
    assert far.start_time is None
