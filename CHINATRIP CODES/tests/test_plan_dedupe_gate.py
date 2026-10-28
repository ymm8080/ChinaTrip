"""行程单同站合并收口测试（2026-10-28，变脸 x4 事故）。

生成期/编辑期去重 2026-10-24 已有，但只挂在部分分支；本文件钉死：
- dedupe_plan_visits 唯一入口语义（跨天合并、动词变体、富者胜出、假设留痕）
- GET /plan/{id} 读闸：打开即自愈并持久化
- /plan/from-itinerary 开档闸
- /plan/{id}/save 入库终闸：重复站点冻结不进行程库
- snapshot restore 恢复闸：工作副本合并、快照本体 WORM 不动

App 装配镜像 tests/test_plan_api.py：stub 依赖 + dependency overrides，
全部离线确定（无 LLM/无地图/无库）。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import (
    _account_from_auth,
    get_entitlement_service,
    get_itinerary_service,
    get_store,
)
from app.api.itineraries import router as itineraries_router
from app.api.plan import get_plan_sessions, get_planning_agent
from app.api.plan import router as plan_router
from app.config import Settings, get_settings
from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    PlanSessionStore,
    dedupe_plan_visits,
)
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary import DayPlan, ItineraryPlan, TransferItem, VisitItem
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    ItineraryService,
)

DEVICE_HEADERS = {"X-Device-ID": "device-1"}


class _StubLLM:
    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("LLM not expected in dedupe gate tests")


def _visit(item_id: str, name: str, **kw) -> VisitItem:
    base = dict(item_id=item_id, name=name, city="成都", day=2)
    base.update(kw)
    return VisitItem(**base)


def _dup_plan() -> ItineraryPlan:
    """变脸 x4 实景还原（it-bf69b5c7）：3 同名 + 1 动词变体，全在 day2。"""
    day1 = DayPlan(
        day=1,
        base_city="北京",
        items=[
            TransferItem(
                item_id="t1",
                day=1,
                seq=1,
                from_city="北京",
                to_city="成都",
                mode="flight",
            ),
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="成都",
        items=[
            _visit("v1", "变脸表演（川剧）"),
            _visit("v2", "变脸表演（川剧）"),
            _visit("v3", "看变脸表演", city="未标注"),
            _visit("v4", "变脸表演（川剧）", poi_id="poi-1"),
            _visit("v5", "宽窄巷子"),
        ],
    )
    return ItineraryPlan(
        itinerary_id="it-dedup", cities=["北京", "成都"], days=[day1, day2]
    )


def _visit_names(plan: ItineraryPlan) -> list[str]:
    return [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]


def _make_harness():
    app = FastAPI()
    store = PlanSessionStore()
    itins = InMemoryItineraryStore()
    entitlement = EntitlementService(InMemoryQuotaStore(), rules=[])
    app.dependency_overrides[get_settings] = lambda: Settings(llm_backend="mock")
    app.dependency_overrides[get_planning_agent] = lambda: PlanningAgent(_StubLLM())
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.dependency_overrides[get_store] = lambda: itins
    app.dependency_overrides[get_entitlement_service] = lambda: entitlement
    app.dependency_overrides[get_itinerary_service] = lambda: ItineraryService(itins)
    app.dependency_overrides[_account_from_auth] = lambda: None
    app.include_router(plan_router)
    app.include_router(itineraries_router)
    return TestClient(app), store, itins, entitlement


def _seed_session(store: PlanSessionStore, plan: ItineraryPlan) -> str:
    session = PlanSession(
        session_id="s-dedup",
        device_id="device-1",
        cities=list(plan.cities),
        days=len(plan.days),
        state="ready",
        plan=plan,
        assumptions=[],
        history=[],
    )
    store.save(session)
    return session.session_id


# --- dedupe_plan_visits 唯一入口 ------------------------------------------


def test_dedupe_plan_visits_merges_duplicates_across_days():
    plan = _dup_plan()
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    assert names.count("变脸表演（川剧）") == 1
    assert "看变脸表演" not in names
    assert "宽窄巷子" in names
    assert len(dropped) == 3
    # 信息更全的孪生（poi_id）胜出
    kept_item = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.name == "变脸表演（川剧）"
    )
    assert kept_item.item_id == "v4"
    # 转移段不受影响
    assert any(isinstance(i, TransferItem) for d in plan.days for i in d.items)
    # 假设区留痕
    assert any("已合并重复站点" in a for a in plan.assumptions)


def test_dedupe_plan_visits_noop_on_clean_plan():
    plan = _dup_plan()
    # 先合并一遍，再跑应是空操作且不再追加假设
    dedupe_plan_visits(plan)
    assumptions_after_first = list(plan.assumptions)
    assert dedupe_plan_visits(plan) == []
    assert plan.assumptions == assumptions_after_first


# --- 演出活动内核判重（2026-10-28 变脸 x3 事故） ---------------------------


def test_show_dup_merges_venue_aliases_of_one_show():
    # ceca3c4b 实景：同一行程 3 条变脸演出，名字互不包含
    plan = ItineraryPlan(
        itinerary_id="it-show",
        cities=["上海", "成都", "重庆", "上海"],
        days=[
            DayPlan(
                day=1,
                base_city="成都",
                items=[
                    _visit(
                        "v29",
                        "橙煌梨园·看川剧变脸·喝盖碗茶",
                        category="food",
                        poi_id="570c94e906cf7df01d1d112a",
                    ),
                    _visit(
                        "v34", "变脸表演（川剧）", poi_id="665fd642e890d21fc9c3db7e"
                    ),
                ],
            ),
            DayPlan(
                day=3,
                base_city="成都",
                items=[
                    _visit("v10", "蜀兿剧院·变脸川剧·盖碗茶", poi_id="ct_成都_53"),
                ],
            ),
        ],
    )
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    assert sum(1 for n in names if "变脸" in n) == 1
    assert len(dropped) == 2
    # 首个钉住的孪生胜出（rank 相同保序）
    assert names[0] == "橙煌梨园·看川剧变脸·喝盖碗茶"


def test_same_poi_id_merges_even_with_different_names():
    # ceca3c4b 实景：青蓝湾茶楼 与 心愿落实的 茶馆喝茶 同一 poi
    plan = ItineraryPlan(
        itinerary_id="it-poi",
        cities=["成都"],
        days=[
            DayPlan(
                day=3,
                base_city="成都",
                items=[
                    _visit(
                        "v30",
                        "青蓝湾茶楼(民主小区A5区店)",
                        category="food",
                        poi_id="064fb21e1a21e940744ff15b",
                    ),
                    _visit("v33", "茶馆喝茶", poi_id="064fb21e1a21e940744ff15b"),
                ],
            ),
        ],
    )
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    assert names == ["青蓝湾茶楼(民主小区A5区店)"]
    assert dropped == ["茶馆喝茶"]


def test_show_dup_does_not_merge_museum_with_show():
    # 防误并：「川剧博物馆」不含「变脸」，与变脸演出是两种体验
    plan = ItineraryPlan(
        itinerary_id="it-no",
        cities=["成都"],
        days=[
            DayPlan(
                day=1,
                base_city="成都",
                items=[
                    _visit("v1", "川剧博物馆"),
                    _visit("v2", "变脸表演（川剧）"),
                    _visit("v3", "成都博物馆", poi_id="ct_成都_6"),
                    _visit("v4", "重庆博物馆", poi_id="ct_重庆_3"),
                ],
            ),
        ],
    )
    assert dedupe_plan_visits(plan) == []
    assert len(_visit_names(plan)) == 4


def test_show_bucket_merges_theatre_and_style_variants():
    # 二轮（用户刚建的行程同类泄露）：「四川省川剧院」「蜀风雅韵」
    # 「蜀兿剧院·川剧表演(太古里店)」不含「变脸」，桶语义下全部并入
    plan = ItineraryPlan(
        itinerary_id="it-bucket",
        cities=["成都"],
        days=[
            DayPlan(
                day=4,
                base_city="成都",
                items=[
                    _visit("v12", "四川省川剧院", poi_id="ct_成都_77"),
                    _visit(
                        "v13", "变脸表演（川剧）", poi_id="665fd642e890d21fc9c3db7e"
                    ),
                ],
            ),
            DayPlan(
                day=6,
                base_city="成都",
                items=[
                    _visit("v20", "看变脸"),
                    _visit("v21", "蜀兿剧院·川剧表演(太古里店)", poi_id="ct_成都_53"),
                ],
            ),
        ],
    )
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    from app.services.agent.plan import _show_bucket

    assert sum(1 for n in names if _show_bucket(n)) == 1
    assert len(dropped) == 3


# --- GET 读闸 ---------------------------------------------------------------


def test_get_plan_self_heals_duplicates_and_persists():
    client, store, _, _ = _make_harness()
    sid = _seed_session(store, _dup_plan())
    resp = client.get(f"/api/v1/plan/{sid}", headers=DEVICE_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    names = [i["name"] for d in body["plan"]["days"] for i in d["items"] if "name" in i]
    assert names.count("变脸表演（川剧）") == 1
    assert "看变脸表演" not in names
    # 读闸修复持久化：会话里的工作副本已合并
    saved = store.get(sid, device_id="device-1")
    assert _visit_names(saved.plan).count("变脸表演（川剧）") == 1


# --- from-itinerary 开档闸 ---------------------------------------------------


def test_from_itinerary_dedupes_on_open():
    client, _, itins, _ = _make_harness()
    itins.put(
        ItineraryRecord(
            itinerary_id="it-dedup",
            owner_device_id="device-1",
            plan=_dup_plan(),
        )
    )
    resp = client.post("/api/v1/plan/from-itinerary/it-dedup", headers=DEVICE_HEADERS)
    assert resp.status_code == 201
    names = [
        i["name"]
        for d in resp.json()["plan"]["days"]
        for i in d["items"]
        if "name" in i
    ]
    assert names.count("变脸表演（川剧）") == 1
    assert "看变脸表演" not in names


# --- save 入库终闸 -----------------------------------------------------------


def test_save_freezes_deduped_plan_into_itinerary_store():
    client, store, itins, _ = _make_harness()
    _seed_session(store, _dup_plan())
    resp = client.post(
        "/api/v1/plan/s-dedup/save",
        json={"name": "收口验证"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 201
    record = itins.get("it-dedup")
    assert record is not None
    names = _visit_names(record.plan)
    assert names.count("变脸表演（川剧）") == 1
    assert "看变脸表演" not in names
    assert "宽窄巷子" in names


# --- restore 恢复闸（快照 WORM 不动） ----------------------------------------


def test_restore_merges_working_copy_keeps_snapshot_frozen():
    client, _, itins, entitlement = _make_harness()
    record = ItineraryRecord(
        itinerary_id="it-dedup",
        owner_device_id="device-1",
        plan=_dup_plan(),
    )
    itins.put(record)
    service = ItineraryService(itins)
    snapshot = service.create_snapshot(
        record, name="v1", entitlement=entitlement, subject_id="device-1"
    )
    resp = client.post(
        f"/api/v1/itineraries/it-dedup/snapshots/{snapshot.snapshot_id}/restore",
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    merged = itins.get("it-dedup")
    assert _visit_names(merged.plan).count("变脸表演（川剧）") == 1
    assert "看变脸表演" not in _visit_names(merged.plan)
    # 快照本体冻结不动（WORM）：重复站点原样保留
    frozen = merged.snapshots[0]
    assert len(_visit_names(frozen.plan)) == 5
