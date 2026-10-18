"""Tests for the TrainService abstraction + mock static timetable."""

import asyncio
from datetime import date as date_cls
from datetime import time, timedelta

import httpx

import app.services.train_cache as train_cache_module
import app.services.trains as trains_module
from app.config import Settings
from app.services.itinerary.models import TransferItem
from app.services.trains import (
    MockTrainService,
    RemoteTrainService,
    Train12306Source,
    TrainOption,
    TrainSourceError,
    _city_station_names,
    _parse_station_js,
    build_transfer_item,
    get_train_service,
    pick_best_train,
)

DATE = "2026-11-03"
SERVICE = MockTrainService()

ALL_PAIRS = [
    ("北京", "上海"),
    ("上海", "北京"),
    ("北京", "西安"),
    ("西安", "北京"),
    ("上海", "杭州"),
    ("杭州", "上海"),
    ("成都", "重庆"),
    ("重庆", "成都"),
]


class StubTrainService:
    """Minimal TrainService for synthetic schedules (cross-midnight etc.)."""

    def __init__(self, options: list[TrainOption]):
        self._options = options

    async def search(self, from_city: str, to_city: str, date: str):
        return self._options


def minutes(t: time) -> int:
    return t.hour * 60 + t.minute


# --- Mock timetable ---


def test_mock_covers_all_pairs_with_three_trains_each():
    for from_city, to_city in ALL_PAIRS:
        options = asyncio.run(SERVICE.search(from_city, to_city, DATE))
        assert len(options) == 3, (from_city, to_city)
        for opt in options:
            assert isinstance(opt, TrainOption)
            assert opt.from_city == from_city
            assert opt.to_city == to_city
            assert opt.date == DATE
            assert opt.train_no
            assert opt.from_station
            assert opt.to_station
            assert opt.arr_time > opt.dep_time  # all mock trains are same-day
            assert opt.duration_minutes == minutes(opt.arr_time) - minutes(opt.dep_time)


def test_mock_beijing_shanghai_plausible_duration():
    options = asyncio.run(SERVICE.search("北京", "上海", DATE))
    train_nos = {opt.train_no for opt in options}
    assert train_nos == {"G1", "G3", "G5"}
    for opt in options:
        assert 4 * 60 + 30 <= opt.duration_minutes <= 6 * 60
        assert opt.from_station == "北京南"
        assert opt.to_station == "上海虹桥"
    g1 = next(opt for opt in options if opt.train_no == "G1")
    assert g1.dep_time == time(7, 0)
    assert g1.arr_time == time(11, 30)
    assert g1.duration_minutes == 270


def test_mock_reverse_direction():
    options = asyncio.run(SERVICE.search("上海", "北京", DATE))
    assert {opt.train_no for opt in options} == {"G2", "G4", "G6"}
    assert all(opt.from_station == "上海虹桥" for opt in options)
    assert all(opt.to_station == "北京南" for opt in options)
    # Short hops stay short in both directions.
    hz = asyncio.run(SERVICE.search("杭州", "上海", DATE))
    assert all(opt.duration_minutes <= 75 for opt in hz)
    cq = asyncio.run(SERVICE.search("重庆", "成都", DATE))
    assert all(80 <= opt.duration_minutes <= 130 for opt in cq)


def test_mock_uncovered_pair_returns_empty():
    assert asyncio.run(SERVICE.search("北京", "杭州", DATE)) == []
    assert asyncio.run(SERVICE.search("拉萨", "北京", DATE)) == []
    assert asyncio.run(SERVICE.search("上海", "上海", DATE)) == []


def test_mock_date_is_pure_passthrough():
    for date in ("2026-01-01", "2026-12-31", "not-even-a-date"):
        options = asyncio.run(SERVICE.search("北京", "上海", date))
        assert options and all(opt.date == date for opt in options)


# --- pick_best_train ---


def test_pick_best_no_window_takes_earliest():
    best = asyncio.run(pick_best_train(SERVICE, "北京", "上海", DATE))
    assert best is not None
    assert best.train_no == "G1"
    assert best.dep_time == time(7, 0)


def test_pick_best_window_hits_only_in_window():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(8, 30), time(12, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G3"  # G1 07:00 before window, G5 14:00 after


def test_pick_best_window_prefers_closest_to_window_start():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(6, 0), time(15, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G1"  # earliest of G1/G3/G5 = closest to 06:00


def test_pick_best_window_without_trains_returns_none():
    # Last Beijing→Shanghai departure is 14:00; evening window is empty.
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(19, 30), time(20, 30)),
        )
    )
    assert best is None


def test_pick_best_uncovered_pair_returns_none():
    assert asyncio.run(pick_best_train(SERVICE, "北京", "杭州", DATE)) is None


def test_pick_best_window_boundaries_are_inclusive():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(7, 0), time(7, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G1"


# --- build_transfer_item ---


def test_build_transfer_item_fills_fields():
    item = asyncio.run(
        build_transfer_item(
            SERVICE,
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=3,
            seq=1,
            item_id="t-day3-1",
        )
    )
    assert isinstance(item, TransferItem)
    assert item.item_id == "t-day3-1"
    assert item.day == 3
    assert item.seq == 1
    assert item.from_city == "北京"
    assert item.to_city == "上海"
    assert item.mode == "train"
    assert item.start_time == time(7, 0)
    assert item.end_time == time(11, 30)
    assert item.duration_minutes == 270
    assert item.train_no == "G1"


def test_build_transfer_item_respects_window():
    item = asyncio.run(
        build_transfer_item(
            SERVICE,
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=2,
            seq=2,
            item_id="t-day2-2",
            preferred_window=(time(8, 30), time(12, 0)),
        )
    )
    assert item is not None
    assert item.train_no == "G3"
    assert item.start_time == time(9, 0)


def test_build_transfer_item_no_train_returns_none():
    # Uncovered pair and empty window both degrade to None.
    assert (
        asyncio.run(
            build_transfer_item(
                SERVICE,
                from_city="北京",
                to_city="杭州",
                date=DATE,
                day=1,
                seq=1,
                item_id="t-none-1",
            )
        )
        is None
    )
    assert (
        asyncio.run(
            build_transfer_item(
                SERVICE,
                from_city="北京",
                to_city="上海",
                date=DATE,
                day=1,
                seq=1,
                item_id="t-none-2",
                preferred_window=(time(19, 30), time(20, 30)),
            )
        )
        is None
    )


def test_build_transfer_item_cross_midnight_truncates_end_time():
    overnight = TrainOption(
        train_no="D311",
        dep_time=time(22, 15),
        arr_time=time(6, 40),  # next day: arr < dep
        duration_minutes=505,
        from_station="北京南",
        to_station="上海虹桥",
        from_city="北京",
        to_city="上海",
        date=DATE,
    )
    item = asyncio.run(
        build_transfer_item(
            StubTrainService([overnight]),
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=1,
            seq=1,
            item_id="t-overnight",
        )
    )
    assert item is not None
    assert item.start_time == time(22, 15)
    assert item.end_time == time(23, 59)  # day-boundary approximation
    assert item.duration_minutes == 505  # true duration is kept
    assert item.train_no == "D311"


# --- RemoteTrainService: 数据源链 携程>美团>12306>mock（全部离线 MockTransport） ---

# 真实 station_name.js 格式片段：@简拼|站名|电报码|全拼|简拼|序|序号|...|
STATION_JS = (
    "var station_name ='"
    "@bjb|北京北|VAP|beijingbei|bjb|0|0357|10579|1|||"
    "@bjn|北京南|VNP|beijingnan|bjn|1|0357|10579|1|||"
    "@bj|北京|BJP|beijing|bj|0|0357|10579|1|||"
    "@shh|上海|SHH|shanghai|shh|0|0357|10579|1|||"
    "@snn|上海南|SNH|shanghainan|snn|1|0357|10579|1|||"
    "@aoh|上海虹桥|AOH|shanghaihongqiao|aoh|1|0357|10579|1|||"
    "@hzh|杭州|HZH|hangzhou|hzh|0|0357|10579|1|||';"
)


# 真实 result 行格式：下标 3=车次、6/7=站名（本行为所查区间=全程）、
# 8/9=时刻、10=历时（HH:MM 形状，是锚定解析的干扰项）。
def _result_row(code: str, from_st: str, to_st: str, dep: str, arr: str, lushi: str):
    return "|".join(
        [
            "",
            "预订",
            "2400000" + code,
            code,
            "VAP",
            "AOH",
            from_st,
            to_st,
            dep,
            arr,
            lushi,
            "Y",
        ]
        + [""] * 8
    )


def test_parse_station_js_entries():
    stations = _parse_station_js(STATION_JS)
    assert stations["北京南"] == "VNP"
    assert stations["上海虹桥"] == "AOH"
    assert stations["北京"] == "BJP"
    assert len(stations) == 7  # JS 前缀/尾缀不产生假条目


def test_parse_station_js_skips_malformed_chunks():
    broken = "var x ='" + "@ok|南京|NJH|nanjing|nj|0|0357|x" + "@bad"
    stations = _parse_station_js(broken)
    assert stations == {"南京": "NJH"}


def test_city_station_names_multistation_city():
    stations = _parse_station_js(STATION_JS)
    beijing = _city_station_names(stations, "北京")
    assert beijing[0] == "北京"  # 站名==城市 优先
    assert "北京南" in beijing and "北京北" in beijing
    hangzhou = _city_station_names(stations, "杭州")  # 单站城市
    assert hangzhou == ["杭州"]
    assert _city_station_names(stations, "深空") == []  # 未知城市 -> 无候选


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _mock_12306_service(handler):
    """RemoteTrainService wrapping one offline (MockTransport) 12306 source."""
    return RemoteTrainService(
        MockTrainService(),
        sources=[
            Train12306Source(timeout_seconds=1, transport=_mock_transport(handler))
        ],
    )


def _station_ok(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/otn/resources/js/framework/station_name.js":
        return httpx.Response(200, text=STATION_JS)
    if path == "/otn/leftTicket/init":
        return httpx.Response(200, text="<html>init</html>")
    return httpx.Response(404)


def test_12306_source_parses_rows_via_station_anchor():
    """成功链路：电报码组合按序尝试 + 站名锚定解析（含跨零点/历时干扰）。"""
    combos = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/otn/leftTicket/query"):
            params = request.url.params
            key = (
                params.get("leftTicketDTO.from_station"),
                params.get("leftTicketDTO.to_station"),
            )
            combos.append(key)
            if key == ("VAP", "AOH"):  # 第 6 个组合（北京北->上海虹桥）
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "result": [
                                _result_row(
                                    "G103",
                                    "北京北",
                                    "上海虹桥",
                                    "06:20",
                                    "12:08",
                                    "05:48",
                                ),
                                _result_row(
                                    "D311",
                                    "北京北",
                                    "上海虹桥",
                                    "21:15",
                                    "06:40",
                                    "09:25",
                                ),
                                # 历时字段形状的干扰：锚不到相邻时刻对的行被跳过
                                _result_row(
                                    "X99", "天津", "南京", "01:00", "02:00", "01:00"
                                ),
                            ]
                        }
                    },
                )
            return httpx.Response(200, json={"data": {"result": []}})
        return _station_ok(request)

    source = Train12306Source(timeout_seconds=1, transport=_mock_transport(handler))
    options = asyncio.run(source.fetch("北京", "上海", DATE))

    assert combos[0] == ("BJP", "SHH")  # 站名==城市 的组合优先
    assert ("VAP", "AOH") in combos
    assert [o.train_no for o in options] == ["G103", "D311"]  # 按出发时刻排序
    g103, d311 = options
    assert (g103.dep_time, g103.arr_time, g103.duration_minutes) == (
        time(6, 20),
        time(12, 8),
        348,
    )
    assert d311.duration_minutes == 565  # 21:15->06:40 跨零点补 24h
    assert g103.from_station == "北京北" and g103.to_station == "上海虹桥"
    assert g103.from_city == "北京" and g103.to_city == "上海"
    assert g103.date == DATE


def test_12306_source_follows_c_url_redirect_hint():
    """错路径 302 + {"c_url":"leftTicket/queryG"} 提示 -> 直跳活跃路径。"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/otn/leftTicket/query"):
            calls.append(request.url.path.rsplit("/", 1)[-1])
            if request.url.path.endswith("/query"):
                return httpx.Response(
                    302, json={"c_url": "leftTicket/queryG", "status": False}
                )
            if request.url.path.endswith("/queryG"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "result": [
                                _result_row(
                                    "G1", "北京", "上海", "07:00", "11:30", "04:30"
                                )
                            ]
                        }
                    },
                )
            return httpx.Response(403, text="forbidden")
        return _station_ok(request)

    source = Train12306Source(timeout_seconds=1, transport=_mock_transport(handler))
    options = asyncio.run(source.fetch("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G1"]
    assert calls[0] == "query" and "queryG" in calls


def test_remote_service_falls_back_to_mock_when_all_paths_403():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/otn/leftTicket/query"):
            return httpx.Response(403, text="forbidden")
        return _station_ok(request)

    service = _mock_12306_service(handler)
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G1", "G3", "G5"]


def test_remote_service_falls_back_to_mock_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("network blackhole")

    service = _mock_12306_service(handler)
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G1", "G3", "G5"]


def test_remote_service_falls_back_to_mock_on_empty_or_unanchorable():
    # 全组合空 result / 行内锚不到所查站名 -> 源返回空 -> 降级 mock，
    # 绝不凭错位下标硬凑时刻。
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/otn/leftTicket/query"):
            params = request.url.params
            if (
                params.get("leftTicketDTO.from_station"),
                params.get("leftTicketDTO.to_station"),
            ) == ("BJP", "SHH"):
                # 行内只有全程站名（天津->南京），锚不到 北京/上海
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "result": [
                                _result_row(
                                    "K21", "天津", "南京", "08:00", "19:00", "11:00"
                                )
                            ]
                        }
                    },
                )
            return httpx.Response(200, json={"data": {"result": []}})
        return _station_ok(request)

    service = _mock_12306_service(handler)
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G1", "G3", "G5"]


def test_12306_source_empty_date_uses_today_plus_three():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/otn/leftTicket/query"):
            seen.append(request.url.params.get("leftTicketDTO.train_date"))
            return httpx.Response(200, json={"data": {"result": []}})
        return _station_ok(request)

    source = Train12306Source(timeout_seconds=1, transport=_mock_transport(handler))
    assert asyncio.run(source.fetch("北京", "上海", "")) == []
    expected = (date_cls.today() + timedelta(days=3)).isoformat()
    assert seen and set(seen) == {expected}


def _stub_source(name, options=None, error=None):
    class _Stub:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, from_city, to_city, date):
            self.calls += 1
            if error is not None:
                raise error
            return list(options or [])

    _Stub.name = name
    return _Stub()


def test_source_chain_first_with_trains_wins_and_short_circuits():
    empty = _stub_source("empty", options=[])
    ok = _stub_source(
        "ok",
        options=[
            TrainOption(
                train_no="G999",
                dep_time=time(8, 0),
                arr_time=time(12, 0),
                duration_minutes=240,
                from_station="北京南",
                to_station="上海虹桥",
                from_city="北京",
                to_city="上海",
                date=DATE,
            )
        ],
    )
    never = _stub_source("never", options=[])
    service = RemoteTrainService(MockTrainService(), sources=[empty, ok, never])
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G999"]
    assert empty.calls == 1 and ok.calls == 1 and never.calls == 0


def test_source_chain_skips_failing_sources():
    broken = _stub_source("broken", error=TrainSourceError("probe blocked"))
    ok = _stub_source(
        "ok",
        options=[
            TrainOption(
                train_no="T11",
                dep_time=time(9, 0),
                arr_time=time(23, 0),
                duration_minutes=840,
                from_station="北京",
                to_station="上海",
                from_city="北京",
                to_city="上海",
                date=DATE,
            )
        ],
    )
    service = RemoteTrainService(MockTrainService(), sources=[broken, ok])
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["T11"]


def test_ctrip_and_meituan_are_placeholder_providers():
    placeholders = (
        trains_module.CtripTrainSource,
        trains_module.MeituanTrainSource,
    )
    for source_cls in placeholders:
        source = source_cls()
        with_error = False
        try:
            asyncio.run(source.fetch("北京", "上海", DATE))
        except TrainSourceError:
            with_error = True
        assert with_error

    ok = _stub_source(
        "12306-stub",
        options=[
            TrainOption(
                train_no="G7",
                dep_time=time(10, 0),
                arr_time=time(14, 30),
                duration_minutes=270,
                from_station="北京南",
                to_station="上海虹桥",
                from_city="北京",
                to_city="上海",
                date=DATE,
            )
        ],
    )
    service = RemoteTrainService(
        MockTrainService(),
        sources=[
            trains_module.CtripTrainSource(),
            trains_module.MeituanTrainSource(),
            ok,
        ],
    )
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G7"]


def test_get_train_service_gating_and_singleton(tmp_path):
    train_cache_module._train_cache_engine = None
    disabled = get_train_service(Settings(train_remote_enabled=False))
    assert isinstance(disabled, MockTrainService)
    assert train_cache_module._train_cache_engine is None  # 关闭即零 DB IO

    trains_module._train_service_singleton = None
    try:
        enabled = Settings(
            train_remote_enabled=True,
            travel_train_source_order=["ctrip", "meituan", "12306"],
            train_cache_url=f"sqlite:///{tmp_path}/train_cache.db",
        )
        first = get_train_service(enabled)
        # 开启时 = 日缓存装饰器包住远程链（app.services.train_cache）。
        assert isinstance(first, train_cache_module.CachedTrainService)
        assert isinstance(first._inner, RemoteTrainService)
        assert [s.name for s in first._inner._sources] == [
            "ctrip",
            "meituan",
            "12306",
        ]
        assert get_train_service(enabled) is first  # 进程级缓存
    finally:
        trains_module._train_service_singleton = None
        train_cache_module._train_cache_engine = None
