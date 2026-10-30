# -*- coding: utf-8 -*-
"""雨天感知选点（2026-10-30 用户拍板：有雨自动排室内，不问用户；二轮
拍板：避免露天活动与下雨时间段一致；三轮拍板：白天/夜间双窗——白天
雨管白天露天点，夜间雨只影响夜间露天活动（游船观景/夜游/夜市等
best_visit_time=evening 点））。

根因链：H5 雨天横幅曾按 day+night 任一含雨判雨，天头图标只看白天——
库内 171/2100 cast 是「白天无雨/夜间雨」（成都 11-03 白天多云夜间
小雨），既出现「横幅说有雨、图标晴天」的错位，也让夜间雨误触发了
白天的避露天安排。三轮后：横幅/图标/规划全部分窗。本组锁三层：
① _rain_map：注入 weather_lookup（回 (day, night) 双窗）按城×日产出
   （白天雨, 夜间雨）两个日集（异常降级、无 start_date/lookup 空表）；
② _deterministic_selection：白天窗——整段有雨→白天露天降权室内优先
   入池、部分日有雨→雨天露天↔干燥日室内对调；夜间窗——雨夜里的夜间
   露天点换到干夜；白天雨不动夜间点（notes 留痕）；
③ weather.daily_weather_text：forecast 优先、forecast14 兜底、双窗
   分开回、无数据 None、读库异常降级。
"""

from types import SimpleNamespace

from app.services.agent.plan import PlanningAgent
from app.services.weather import daily_weather_text


def _agent(lookup=None):
    return PlanningAgent(None, weather_lookup=lookup)


def _cand(name, city, rain_ok, *, lon=104.0, lat=30.6, source="08", bvt=None):
    cand = {
        "name": name,
        "city": city,
        "category": "sight",
        "source": source,
        "rain_ok": rain_ok,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": 60,
    }
    if bvt is not None:
        cand["best_visit_time"] = bvt
    return cand


# ---------- ① _rain_map ----------


def test_rain_map_builds_day_and_night_sets_from_lookup():
    # lookup 回 (day, night) 双窗：白天雨入 day 集、夜间雨入 night 集
    agent = _agent(
        lambda city, iso: (
            ("小雨", "晴")
            if iso == "2026-11-03"
            else ("多云", "小雨")
            if iso == "2026-11-04"
            else ("多云", "晴")
        )
    )
    session = SimpleNamespace(start_date="2026-11-02", cities=["成都"])
    day_rain, night_rain = agent._rain_map(session, {"成都": (1, 3)})
    assert day_rain == {"成都": {2}}
    assert night_rain == {"成都": {3}}


def test_rain_map_empty_without_start_date_or_lookup():
    session = SimpleNamespace(start_date=None, cities=["成都"])
    assert _agent(lambda *a: ("暴雨", "暴雨"))._rain_map(session, {"成都": (1, 2)}) == (
        {},
        {},
    )
    no_lookup = _agent()
    assert no_lookup._rain_map(
        SimpleNamespace(start_date="2026-11-02", cities=["成都"]), {"成都": (1, 2)}
    ) == ({}, {})


def test_rain_map_degrades_on_lookup_error():
    def boom(city, iso):
        raise RuntimeError("db down")

    agent = _agent(boom)
    day_rain, night_rain = agent._rain_map(
        SimpleNamespace(start_date="2026-11-02", cities=["成都"]), {"成都": (1, 1)}
    )
    assert day_rain == {} and night_rain == {}


# ---------- ② _deterministic_selection 雨天感知（白天窗 + 夜间窗） ----------


def test_selection_prefers_indoor_when_whole_window_rainy():
    cands = [
        _cand("青城山", "成都", "no"),
        _cand("街子古镇", "成都", "no"),
        _cand("成都博物馆", "成都", "yes"),
        _cand("四川博物院", "成都", "yes"),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, rain_days={"成都": {1}}, notes=notes
    )
    names = [p["name"] for p in picked]
    # 单日窗全量装下（4×60≤360、4 个/日闸）：室内在前、露天垫后
    assert names[:2] == ["成都博物馆", "四川博物院"]
    assert set(names[2:]) == {"青城山", "街子古镇"}
    assert any("室内" in n for n in notes)


def test_selection_unchanged_without_rain_days():
    cands = [
        _cand("青城山", "成都", "no"),
        _cand("成都博物馆", "成都", "yes"),
    ]
    picked = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    # 无雨：库序选点，露天不降权（回归闸——雨天感知缺省零侵入）
    assert [p["name"] for p in picked] == ["青城山", "成都博物馆"]


def test_selection_swaps_outdoor_on_rainy_day_with_indoor_on_dry_day():
    # 地理两组：露天组在北（31.5/31.4），室内组在南（30.66/30.65）——
    # cluster_days k=2 确定性切两片，露天片（库序在前）落第 1 天
    cands = [
        _cand("青城山", "成都", "no", lat=31.5),
        _cand("街子古镇", "成都", "no", lat=31.4),
        _cand("成都博物馆", "成都", "yes", lat=30.66),
        _cand("四川博物院", "成都", "yes", lat=30.65),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 第 1 天（雨天）不剩露天点：两个露天点已换到第 2 天
    assert day_of["青城山"] == 2 and day_of["街子古镇"] == 2
    assert day_of["成都博物馆"] == 1 and day_of["四川博物院"] == 1
    assert sum("对调" in n for n in notes) == 2


def test_selection_keeps_outdoor_when_no_indoor_to_swap():
    # 全窗有雨且候选全是露天：无室内可换，保持原排不丢点（宁露天不空天）
    cands = [
        _cand("青城山", "成都", "no", lat=31.5),
        _cand("街子古镇", "成都", "no", lat=30.6),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1, 2}}, notes=notes
    )
    assert {p["name"] for p in picked} == {"青城山", "街子古镇"}
    # 全露天无室内 → 不发「已优先室内」note（没优先成）
    assert not any("室内" in n for n in notes)


def test_selection_moves_night_activity_off_rainy_night():
    # 三轮拍板：夜间雨只影响夜间露天活动——珠江夜游（bvt=evening）在
    # 雨夜（第 1 天）→ 与干夜（第 2 天）的室内点对调；白天露天点不动
    cands = [
        _cand("珠江夜游", "广州", "no", lat=23.00, bvt="evening"),
        _cand("广州塔", "广州", "no", lat=23.01),
        _cand("广东省博物馆", "广州", "yes", lat=23.60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"广州": (1, 2)}, night_rain_days={"广州": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["珠江夜游"] == 2  # 雨夜 → 干夜
    assert day_of["广东省博物馆"] == 1
    assert day_of["广州塔"] == 1  # 白天露天点不受夜间雨影响
    assert any("夜间有雨" in n and "珠江夜游" in n for n in notes)


def test_selection_day_rain_does_not_move_night_activity():
    # 三轮拍板：白天雨不动夜间点——夜游留原日（夜窗无雨），白天露天点
    # 才被换到晴日
    cands = [
        _cand("白云山", "广州", "no", lat=23.00),
        _cand("珠江夜游", "广州", "no", lat=23.01, bvt="evening"),
        _cand("广东省博物馆", "广州", "yes", lat=23.60),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"广州": (1, 2)}, rain_days={"广州": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["珠江夜游"] == 1  # 夜间点不受白天雨影响
    assert day_of["白云山"] == 2  # 白天露天换到晴日
    assert day_of["广东省博物馆"] == 1
    assert any("白云山" in n for n in notes)


# ---------- ③ weather.daily_weather_text ----------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeFactory:
    def __init__(self, rows):
        self._rows = rows

    def __call__(self):
        return _FakeSession(self._rows)


def _row(kind, casts, adcode="510100"):
    return SimpleNamespace(kind=kind, adcode=adcode, payload={"casts": casts})


def test_daily_weather_text_prefers_short_forecast_over_forecast14():
    factory = _FakeFactory(
        [
            _row(
                "forecast14",
                [{"date": "2026-11-03", "day_weather": "阴", "night_weather": "晴"}],
            ),
            _row(
                "forecast",
                [
                    {
                        "date": "2026-11-03",
                        "day_weather": "多云",
                        "night_weather": "小雨",
                    }
                ],
            ),
        ]
    )
    # 短程源优先 + 双窗分开回
    assert daily_weather_text(factory, "成都", "2026-11-03") == ("多云", "小雨")


def test_daily_weather_text_falls_back_to_forecast14_and_none():
    factory = _FakeFactory(
        [
            _row(
                "forecast14",
                [{"date": "2026-11-20", "day_weather": "晴", "night_weather": "晴"}],
            )
        ]
    )
    assert daily_weather_text(factory, "成都", "2026-11-20") == ("晴", "晴")
    assert daily_weather_text(factory, "成都", "2026-12-01") is None
    assert daily_weather_text(factory, "火星", "2026-11-20") is None  # 未收录城市


def test_daily_weather_text_dual_windows_split():
    # 三轮拍板：白天/夜间分开回——夜间小雨只进 night 位
    factory = _FakeFactory(
        [
            _row(
                "forecast",
                [
                    {
                        "date": "2026-11-03",
                        "day_weather": "多云",
                        "night_weather": "小雨",
                    }
                ],
            )
        ]
    )
    assert daily_weather_text(factory, "成都", "2026-11-03") == ("多云", "小雨")


def test_daily_weather_text_degrades_on_db_error():
    class Boom:
        def __call__(self):
            raise RuntimeError("db down")

    assert daily_weather_text(Boom(), "成都", "2026-11-03") is None
