# -*- coding: utf-8 -*-
"""A/B 基准：插入主路 vs CP 主路（CHINATRIP_SCHEDULER）。

用法：python ops/bench_scheduler.py
指标：untimed 数 / 全程走行分钟 / 墙钟毫秒（每模式逐日求解）。
"""

import os
import sys
import time as _time
from datetime import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import solve_plan


def _v(item_id, dur, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="西安",
        day=1,
        duration_minutes=dur,
        **kw,
    )


def bench_day(label, day: DayPlan, hours, matrix=None):
    print(f"--- {label} ---")
    for mode in ("insertion", "cp"):
        os.environ["CHINATRIP_SCHEDULER"] = mode
        plan = ItineraryPlan(
            itinerary_id="bench", cities=["西安"], days=[day.model_copy(deep=True)]
        )
        t0 = _time.perf_counter()
        solved = solve_plan(plan, poi_hours=hours, travel_minutes=matrix)
        ms = (_time.perf_counter() - t0) * 1000
        if solved is None:
            print(f"  {mode:10s} None  {ms:.1f}ms")
            continue
        untimed = sum(
            1
            for d in solved.days
            for i in d.items
            if isinstance(i, VisitItem) and i.start_time is None
        )
        seq = [
            i
            for d in solved.days
            for i in d.items
            if isinstance(i, VisitItem) and i.start_time is not None
        ]
        seq.sort(key=lambda i: (i.start_time.hour, i.start_time.minute))
        travel = 0
        if matrix:
            for a, b in zip(seq, seq[1:]):
                travel += matrix.get((a.item_id, b.item_id), 30)
        lay = " | ".join(
            f"{i.item_id}@{i.start_time.hour:02d}:{i.start_time.minute:02d}"
            for i in seq
        )
        print(f"  {mode:10s} untimed={untimed} travel={travel} {ms:6.1f}ms  {lay}")
    os.environ.pop("CHINATRIP_SCHEDULER", None)


def main():
    # ① 参考案：5 天西安 day4 形状（钟楼+三场演出+午餐，真场次）
    lunch = VisitItem(
        item_id="lunch",
        name="午饭",
        category="food",
        city="西安",
        day=1,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    shows = [
        _v(
            "sf",
            80,
            best_visit_time="show",
            category="entertainment",
            opening_hours="多场（白天约11:10/12:00/13:40/16:20/17:10，平日约3场）",
        ),
        _v(
            "sq",
            80,
            best_visit_time="show",
            category="entertainment",
            opening_hours="多场（约14:00/16:30，旺季11:00起加场）",
        ),
        _v(
            "sr",
            80,
            best_visit_time="show",
            category="entertainment",
            opening_hours="多场（约11:00/14:00/17:00，以当日公告为准）",
        ),
    ]
    zhonglou = _v("zhonglou", 60)
    bench_day(
        "day4 三演出+钟楼+软午餐（真场次）",
        DayPlan(day=1, base_city="西安", items=[lunch, zhonglou, *shows]),
        [],
    )

    # ② 240 大点+软午餐（±30 规则案）
    bench_day(
        "240 大点+软午餐 meal_flex",
        DayPlan(
            day=1,
            base_city="西安",
            items=[
                lunch,
                _v("big240", 240),
            ],
        ),
        [],
    )

    # ③ 返程日晚场演出+航班（按日降级案）
    flight = TransferItem(
        day=1,
        seq=1,
        mode="flight",
        item_id="t1",
        from_city="西安",
        to_city="上海",
        start_time=time(17, 0),
        end_time=time(20, 0),
        duration_minutes=180,
    )
    show_eve = _v(
        "seve",
        80,
        best_visit_time="show",
        category="entertainment",
        opening_hours="傍晚/晚间场（约17:30/19:30两场）",
    )
    big180 = _v("big180", 180)
    bench_day(
        "返程日晚场×航班+180 大点",
        DayPlan(day=1, base_city="西安", items=[lunch, flight, show_eve, big180]),
        [],
    )

    # ④ 走行矩阵模式（4 点同城）
    matrix = {}
    ids = ["m1", "m2", "m3", "m4"]
    for a in ids:
        for b in ids:
            if a != b:
                matrix[(a, b)] = (
                    40
                    if (a, b)
                    in {
                        ("m1", "m2"),
                        ("m2", "m1"),
                        ("m2", "m3"),
                        ("m3", "m2"),
                        ("m3", "m4"),
                        ("m4", "m3"),
                    }
                    else 70
                )
    bench_day(
        "4 点走行矩阵（m1-m4 链便宜）",
        DayPlan(
            day=1,
            base_city="西安",
            items=[_v(i, 90) for i in ids],
        ),
        [],
        matrix=matrix,
    )


if __name__ == "__main__":
    main()
