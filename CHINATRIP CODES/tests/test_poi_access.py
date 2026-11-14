"""POI 到达方式摘要（app.services.poi_access）单测。

口径来源：2026-11-15 用户拍板「远郊景点要有交通方式（景交/地铁/火车）」，
慕田峪实测（百度 transit，城心 前门 → 景区）：单段「慕田峪长城景区直达车
前门线」，首班 07:00、末班 12:00、2 小时 8 分、下车步行 8 分钟。
"""

from __future__ import annotations

from app.services.poi_access import build_note, classify_ride, summarize


def _ride(name, kind="bus", **over):
    ride = {
        "kind": kind,
        "name": name,
        "departure_stop": None,
        "arrival_stop": None,
        "duration_s": None,
        "departure_time": None,
        "last_time": None,
        "time_table": [],
    }
    ride.update(over)
    return ride


def _plan(duration_s, *segments):
    return {"duration_s": duration_s, "segments": list(segments)}


def _ride_seg(ride):
    return {"walking": None, "rides": [ride]}


def _walk_seg(distance_m, duration_s):
    return {
        "walking": {"distance_m": distance_m, "duration_s": duration_s, "steps": []},
        "rides": [],
    }


# --- 方式判定 ------------------------------------------------------------------


def test_classify_ride_by_line_name():
    assert classify_ride(_ride("地铁8号线")) == "metro"
    assert classify_ride(_ride("慕田峪长城景区直达车前门线")) == "shuttle"
    assert classify_ride(_ride("市郊铁路怀密线")) == "train"
    assert classify_ride(_ride("120路")) == "bus"
    assert classify_ride(_ride("鼓浪屿轮渡")) == "ferry"


def test_classify_ride_falls_back_to_kind():
    assert classify_ride(_ride("", kind="railway")) == "train"
    assert classify_ride(_ride("", kind="bus")) == "bus"


# --- 摘要 ----------------------------------------------------------------------


def test_summarize_single_shuttle_keeps_first_last_and_walk():
    plans = [
        _plan(
            0,
            _walk_seg(369, 316),
            _ride_seg(
                _ride(
                    "慕田峪长城景区直达车前门线",
                    kind="bus",
                    departure_stop="前门站",
                    arrival_stop="慕田峪长城站",
                    duration_s=5546,
                    departure_time="07:00",
                    last_time="12:00",
                )
            ),
            _walk_seg(1964, 480),
        )
    ]
    plans[0]["duration_s"] = 7647
    out = summarize(plans)
    assert out is not None
    assert out["access_mode"] == "shuttle"
    assert out["access_minutes"] == 127
    assert out["access_gateway"] == "慕田峪长城站"
    # 下车点 2km 外：不再当「步行 8 分钟」报，改口接驳/打车（见下一条短步行）
    assert out["access_gateway_minutes"] is None
    assert "前门站 → 慕田峪长城站" in out["access_note"]
    assert "首班 07:00" in out["access_note"]
    assert "末班 12:00" in out["access_note"]
    assert "2.0 km" in out["access_note"]
    assert "打车/接驳" in out["access_note"]
    assert out["access_note_en"].startswith("Take 慕田峪长城景区直达车前门线")


def test_summarize_short_walk_keeps_walk_minutes():
    plans = [
        _plan(
            4200,
            _ride_seg(
                _ride(
                    "怀密线",
                    kind="railway",
                    departure_stop="黄土店站",
                    arrival_stop="雁栖湖站",
                    duration_s=3600,
                )
            ),
            _walk_seg(800, 360),
        )
    ]
    out = summarize(plans)
    assert out["access_gateway_minutes"] == 6
    assert "下车步行 6 分钟" in out["access_note"]


def test_summarize_prefers_the_ride_that_covers_the_distance():
    """地铁 40 分钟 + 长途公交 2 小时 → 报公交（远郊件问的是那趟长途车）。"""
    plans = [
        _plan(
            9600,
            _ride_seg(
                _ride("地铁2号线外环", kind="railway", duration_s=2400,
                      departure_stop="前门站", arrival_stop="东直门站")
            ),
            _walk_seg(200, 180),
            _ride_seg(
                _ride("980路快车", duration_s=7200,
                      departure_stop="东直门站", arrival_stop="密云站")
            ),
        )
    ]
    out = summarize(plans)
    assert out is not None
    assert out["access_mode"] == "bus"
    assert "地铁2号线外环" in out["access_note"]
    assert "980路快车" in out["access_note"]
    assert "1 次换乘" in out["access_note"]


def test_summarize_marks_once_a_day_departure():
    plans = [
        _plan(
            3600,
            _ride_seg(
                _ride("密51路区间", duration_s=3300,
                      departure_stop="密云站", arrival_stop="沙岭七队站",
                      departure_time="11:00", last_time="11:00")
            ),
        )
    ]
    out = summarize(plans)
    assert "仅 11:00 一班" in out["access_note"]
    assert "首班" not in out["access_note"]


def test_summarize_picks_fastest_plan():
    slow = _plan(7200, _ride_seg(_ride("A线", duration_s=7000)))
    fast = _plan(3600, _ride_seg(_ride("B线", duration_s=3400)))
    out = summarize([slow, fast])
    assert out["access_minutes"] == 60
    assert "B线" in out["access_note"]


def test_summarize_walk_only_plan():
    out = summarize([_plan(900, _walk_seg(600, 900))])
    assert out["access_mode"] == "walk"
    assert out["access_gateway"] is None
    assert out["access_minutes"] == 15


def test_summarize_returns_none_without_usable_plan():
    assert summarize(None) is None
    assert summarize([]) is None
    assert summarize([{"duration_s": 0, "segments": []}]) is None
    assert summarize([{"segments": []}]) is None


def test_note_is_clamped_for_long_chains():
    rides = [
        _ride(f"线路{i}", departure_stop=f"站{i}", arrival_stop=f"站{i + 1}",
              duration_s=600)
        for i in range(6)
    ]
    zh, en = build_note(
        rides, total_minutes=200, walk_minutes=12, gateway="终点站"
    )
    assert len(zh) <= 300 and len(en) <= 300
    assert "…" in zh
