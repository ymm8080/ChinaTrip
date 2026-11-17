"""路途行程三件套（2026-11-04 规划页）：改乘 mode / 班次号 number / 订票
跳转 booking-links 端点级测试。

App 组装同 tests/test_plan_api.py 口径（stub 依赖 + 每例新 store）；班次源
注入脚本化 TrainService / FlightService，LLM 零参与（改乘与校时都是
确定性管线）。"""

from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import get_entitlement_service
from app.api.plan import (
    get_fast_lane,
    get_plan_sessions,
    get_planning_agent,
    get_request_gate,
    get_task_store,
)
from app.api.plan import router as plan_router
from app.config import Settings, get_settings
from app.services.agent.plan import PlanningAgent, PlanSession, PlanSessionStore
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.flights import FlightOption, MockFlightService
from app.services.gate import RequestGate
from app.services.itinerary import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.trains import MockTrainService, TrainOption, TrainService

DEVICE = {"X-Device-ID": "device-1"}


class _NoLLM:
    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("transfer endpoints must not call the LLM")


class ScriptedTrains(TrainService):
    """固定班次表：search 恒返回同一组（城市对/日期不做过滤——按 12306
    源语义，过滤在选班层）。"""

    def __init__(self, options):
        self.options = options

    async def search(self, from_city, to_city, date):
        return list(self.options)


class ScriptedFlights(MockFlightService):
    def __init__(self, options):
        self.options = options

    async def search(self, from_city, to_city, date):
        return list(self.options)


def _train(train_no, dep, arr, dur):
    return TrainOption(
        train_no=train_no,
        dep_time=dep,
        arr_time=arr,
        duration_minutes=dur,
        from_station="北京南",
        to_station="上海虹",
        from_city="北京",
        to_city="上海",
        date="2026-11-10",
    )


def _plan(mode="train", train_no="G1", flight_no=None) -> ItineraryPlan:
    """day1: 北京→上海 腿 + 外滩；day2: 返程腿。start_date 已设。"""
    return ItineraryPlan(
        itinerary_id="itin-x",
        cities=["北京", "上海"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    TransferItem(
                        item_id="t1",
                        day=1,
                        seq=1,
                        from_city="北京",
                        to_city="上海",
                        mode=mode,
                        start_time=time(8, 0),
                        end_time=time(13, 30),
                        duration_minutes=330,
                        train_no=train_no,
                        flight_no=flight_no,
                    ),
                    VisitItem(
                        item_id="v1",
                        name="两江夜游",
                        city="上海",
                        day=1,
                        category="entertainment",  # 演出/夜游=16:30 白闸豁免件
                        start_time=time(16, 0),
                        end_time=time(17, 0),
                        duration_minutes=60,
                    ),
                ],
            ),
            DayPlan(
                day=2,
                base_city="上海",
                items=[
                    TransferItem(
                        item_id="t2",
                        day=2,
                        seq=1,
                        from_city="上海",
                        to_city="北京",
                        mode="flight",
                        start_time=time(17, 0),
                        end_time=time(20, 0),
                        duration_minutes=180,
                        flight_no="MU1002",
                    )
                ],
            ),
        ],
        start_date="2026-11-10",
    )


def make_agent(trains, flights) -> PlanningAgent:
    return PlanningAgent(_NoLLM(), train_service=trains, flight_service=flights)


def make_client(agent) -> tuple[TestClient, PlanSessionStore]:
    app = FastAPI()
    store = PlanSessionStore()
    session = PlanSession(
        session_id="s1",
        device_id="device-1",
        cities=["北京", "上海"],
        days=2,
        start_date="2026-11-10",
        state="planning",
    )
    session.plan = _plan()
    store.save(session)
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.dependency_overrides[get_entitlement_service] = lambda: EntitlementService(
        InMemoryQuotaStore(), rules=[]
    )
    app.dependency_overrides[get_request_gate] = lambda: RequestGate(_NoLLM())
    from app.services.fast_lane import FastLane

    app.dependency_overrides[get_fast_lane] = lambda: FastLane(
        poi_details=_NoopPoi(), trip_items=_NoopTrip(), translate=_NoopTranslate()
    )
    from app.services.task_queue import TaskStore

    app.dependency_overrides[get_task_store] = lambda: TaskStore(":memory:")
    app.include_router(plan_router)
    return TestClient(app), store


class _NoopPoi:
    def get_by_name(self, city, name):
        return None


class _NoopTrip:
    def list_groups(self, itinerary_id=None):
        return {"wishlist": []}


class _NoopTranslate:
    async def translate(self, text, *, source_lang, target_lang):
        raise AssertionError("not expected")


def _find(plan, item_id):
    for day in plan["days"]:
        for item in day["items"]:
            if item["item_id"] == item_id:
                return item
    raise AssertionError(f"item {item_id} missing")


def _post_transfer(client, path, body=None):
    return client.post(
        f"/api/v1/plan/s1/transfers/t1/{path}", json=body or {}, headers=DEVICE
    )


# --- 改乘（mode） ---------------------------------------------------------


def test_switch_train_leg_to_flight_requeries_and_updates_times():
    flights = ScriptedFlights([FlightOption("MU1001", time(9, 0), time(12, 0), 180)])
    client, _ = make_client(make_agent(ScriptedTrains([]), flights))
    resp = _post_transfer(client, "mode", {"mode": "flight"})
    assert resp.status_code == 200
    leg = _find(resp.json()["plan"], "t1")
    assert leg["mode"] == "flight"
    assert leg["flight_no"] == "MU1001"
    assert leg["train_no"] is None
    assert leg["start_time"] == "09:00:00"
    assert leg["end_time"] == "12:00:00"
    assert leg["duration_minutes"] == 180


def test_switch_flight_leg_to_train_picks_mock_best():
    # mock 火车表 北京→上海 有班（G1/G3/...）：改乘火车后 train_no 必落
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = client.post(
        "/api/v1/plan/s1/transfers/t2/mode", json={"mode": "train"}, headers=DEVICE
    )
    assert resp.status_code == 200
    leg = _find(resp.json()["plan"], "t2")
    assert leg["mode"] == "train"
    assert leg["train_no"]
    assert leg["flight_no"] is None
    assert leg["start_time"] is not None


def test_switch_to_flight_without_schedule_returns_422_and_keeps_leg():
    client, store = make_client(make_agent(ScriptedTrains([]), ScriptedFlights([])))
    resp = _post_transfer(client, "mode", {"mode": "flight"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "no_flight_found"
    # 旧腿原样保留（422 路径绝不落任何回填）
    leg = _find(store.get("s1", device_id="device-1").plan.model_dump(), "t1")
    assert leg["mode"] == "train"
    assert leg["train_no"] == "G1"
    assert leg["start_time"] == time(8, 0)


def test_rechain_visit_after_earlier_arrival():
    # 原 G1 13:30 到、外滩 16:00 合法；改乘 G9（15:00 到）→ 落地地板
    # 15:00+150=17:30，外滩被清时刻重排到 ≥17:30（铁律 4 衔接缓冲）
    g9 = _train("G9", time(9, 0), time(15, 0), 360)
    client, _ = make_client(make_agent(ScriptedTrains([g9]), ScriptedFlights([])))
    resp = _post_transfer(client, "number", {"number": "G9"})
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    leg = _find(plan, "t1")
    visit = _find(plan, "v1")
    assert leg["end_time"] == "15:00:00"
    assert visit["day"] == 1
    assert visit["start_time"] >= "17:30"


def test_late_arrival_moves_visit_to_next_day_with_note():
    # G9 20:00 到 → 落地地板 22:30 已过日终：夜游挪到第 2 天（到达侧
    # 搁浅口径），reply 披露挪移
    late = _train("G9", time(9, 0), time(20, 0), 660)
    client, _ = make_client(make_agent(ScriptedTrains([late]), ScriptedFlights([])))
    resp = _post_transfer(client, "number", {"number": "G9"})
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    visit = _find(plan, "v1")
    assert visit["day"] == 2
    assert "两江夜游" in resp.json()["reply"]


# --- 班次号（number） -----------------------------------------------------


def test_number_g_train_updates_leg_times_and_mode():
    opts = [
        _train("G1", time(8, 0), time(13, 30), 330),
        _train("G9", time(9, 0), time(14, 0), 300),
    ]
    client, _ = make_client(make_agent(ScriptedTrains(opts), ScriptedFlights([])))
    resp = _post_transfer(client, "number", {"number": " g9 "})
    assert resp.status_code == 200
    leg = _find(resp.json()["plan"], "t1")
    assert leg["mode"] == "train"
    assert leg["train_no"] == "G9"
    assert leg["start_time"] == "09:00:00"
    assert leg["end_time"] == "14:00:00"
    assert leg["flight_no"] is None


def test_number_flight_updates_leg_times_and_mode():
    flights = ScriptedFlights([FlightOption("CA1234", time(10, 30), time(13, 0), 150)])
    client, _ = make_client(make_agent(ScriptedTrains([]), flights))
    resp = _post_transfer(client, "number", {"number": "ca1234"})
    assert resp.status_code == 200
    leg = _find(resp.json()["plan"], "t1")
    assert leg["mode"] == "flight"
    assert leg["flight_no"] == "CA1234"
    assert leg["train_no"] is None
    assert leg["start_time"] == "10:30:00"


def test_number_flight_suffix_letter_and_airline_digit_prefix():
    flights = ScriptedFlights([FlightOption("3U8881", time(7, 30), time(10, 0), 150)])
    client, _ = make_client(make_agent(ScriptedTrains([]), flights))
    resp = _post_transfer(client, "number", {"number": "3U8881"})
    assert resp.status_code == 200
    assert _find(resp.json()["plan"], "t1")["flight_no"] == "3U8881"


def test_number_not_found_returns_422():
    opts = [_train("G1", time(8, 0), time(13, 30), 330)]
    client, _ = make_client(make_agent(ScriptedTrains(opts), ScriptedFlights([])))
    resp = _post_transfer(client, "number", {"number": "G999"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "number_not_found"


def test_number_bad_format_returns_422():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    for bad in ("abc", "12345678", "G12345", "TOOLONG1"):
        resp = _post_transfer(client, "number", {"number": bad})
        assert resp.status_code == 422, bad
        assert resp.json()["detail"] == "bad_number_format"


def test_number_unknown_item_404():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = client.post(
        "/api/v1/plan/s1/transfers/nope/number",
        json={"number": "G1"},
        headers=DEVICE,
    )
    assert resp.status_code == 404


def test_transfer_endpoints_need_matching_device():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = client.post(
        "/api/v1/plan/s1/transfers/t1/mode",
        json={"mode": "flight"},
        headers={"X-Device-ID": "other"},
    )
    assert resp.status_code == 404


# --- 订票跳转（booking-links） --------------------------------------------


def test_booking_links_flight_leg_has_qunar_and_fliggy():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = _post_transfer(client, "mode", {"mode": "flight"})  # t1 → flight
    assert resp.status_code == 200
    resp = _post_transfer(client, "booking-links")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "flight"
    channels = {c["channel"] for c in body["cards"]}
    assert {"ctrip", "qunar", "fliggy"} <= channels
    for card in body["cards"]:
        assert card["url"].startswith("https://")
        assert card["refund_summary"]  # 铁律 23：无摘要禁止跳转
    fliggy = next(c for c in body["cards"] if c["channel"] == "fliggy")
    assert "flight.fliggy.com" in fliggy["url"]
    assert "disclaimer" in body and body["disclaimer"]


def test_booking_links_train_leg_single_12306_card():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = _post_transfer(client, "booking-links")  # t1 是 train
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "train"
    assert [c["channel"] for c in body["cards"]] == ["12306"]
    assert body["cards"][0]["unified_price"] is True
    assert "12306" in body["cards"][0]["url"]


def test_booking_links_car_leg_rejected():
    client, store = make_client(make_agent(MockTrainService(), MockFlightService()))
    session = store.get("s1", device_id="device-1")
    session.plan.days[0].items[0].mode = "car"
    session.plan.days[0].items[0].train_no = None
    store.save(session)
    resp = _post_transfer(client, "booking-links")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "booking_unavailable"


def test_booking_links_unknown_item_404():
    client, _ = make_client(make_agent(MockTrainService(), MockFlightService()))
    resp = client.post("/api/v1/plan/s1/transfers/nope/booking-links", headers=DEVICE)
    assert resp.status_code == 404
