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


# --- 2026-10-31 青城山误并事故：同站判定的地理闸 ----------------------------


def test_same_visit_geo_guard_blocks_same_name_far_apart():
    """泛名包含吞下同山不同场馆（青城山 ↔ 青城山skydive跳伞基地，实测
    相距 ~6km）：双方有坐标且 >2km 不并；近距同名照并；缺坐标维持名字
    判定（心愿别名路径无坐标可依）。"""
    from app.services.agent.plan import _same_visit
    from app.services.itinerary import GeoPoint

    mountain = _visit("v1", "青城山", location=GeoPoint(lon=103.5949, lat=30.8995))
    skydive = _visit(
        "v2", "青城山skydive跳伞基地", location=GeoPoint(lon=103.6215, lat=30.8479)
    )
    assert _same_visit(skydive, mountain) is False  # ~6km：不同场馆不并

    near_twin = _visit("v3", "青城山景区", location=GeoPoint(lon=103.595, lat=30.900))
    assert _same_visit(mountain, near_twin) is True  # 同点近距：照并

    no_loc = _visit("v4", "青城山景区")
    assert _same_visit(mountain, no_loc) is True  # 缺坐标：名字判定不变


def test_dedupe_plan_keeps_far_apart_same_name_pair():
    """端到端：两个名字包含但相距 >2km 的场馆都留在行程里，去重零合并。"""
    from app.services.itinerary import GeoPoint

    plan = _dup_plan()
    day2 = plan.days[1]
    day2.items.append(
        _visit("v6", "青城山", location=GeoPoint(lon=103.5949, lat=30.8995))
    )
    day2.items.append(
        _visit(
            "v7",
            "青城山skydive跳伞基地",
            location=GeoPoint(lon=103.6215, lat=30.8479),
        )
    )
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    assert "青城山" in names and "青城山skydive跳伞基地" in names
    assert "青城山skydive跳伞基地" not in dropped


# --- 2026-10-31 大足双卡案：同内容配套场馆（博物馆/影院/园区） ---------------


def test_content_dup_merges_dazu_museum_cinema_scenic():
    """实景（it-02287fad / it-c20cc5b5）：大足石刻博物馆 13:30 + 大足石刻
    数字影院 15:00 背靠背，9 天版再加大足区大足石刻景区跨天第三卡——
    三者剥设施词后核心词同为「大足石刻」（博物馆/影院距 ~1.4km、园区
    与博物馆同坐标），同内容只算一站。"""
    from app.services.agent.plan import _content_dup, _same_visit
    from app.services.itinerary import GeoPoint

    assert _content_dup("大足石刻博物馆", "大足石刻数字影院") is True
    assert _content_dup("大足石刻博物馆", "大足区大足石刻景区") is True
    assert _content_dup("大足石刻数字影院", "大足区大足石刻景区") is True

    museum = _visit(
        "v1",
        "大足石刻博物馆",
        city="重庆",
        poi_id="ct_重庆_133",
        location=GeoPoint(lon=105.79484, lat=29.74688),
    )
    cinema = _visit(
        "v2",
        "大足石刻数字影院",
        city="重庆",
        poi_id="ct_重庆_301",
        location=GeoPoint(lon=105.78017, lat=29.74961),
    )
    scenic = _visit(
        "v3",
        "大足区大足石刻景区",
        city="重庆",
        poi_id="5a_243",
        location=GeoPoint(lon=105.79484, lat=29.74688),
    )
    assert _same_visit(museum, cinema) is True  # ~1.4km：同园区配套
    assert _same_visit(scenic, museum) is True  # 同坐标


def test_dedupe_plan_keeps_single_dazu_card():
    """端到端：day2 博物馆+影院背靠背、day3 园区卡 → 全程只留一张大足卡，
    假设区「已合并重复站点」留痕。"""
    from app.services.itinerary import GeoPoint

    plan = ItineraryPlan(
        itinerary_id="it-dazu",
        cities=["重庆"],
        days=[
            DayPlan(
                day=2,
                base_city="重庆",
                items=[
                    _visit(
                        "v1",
                        "大足石刻博物馆",
                        city="重庆",
                        poi_id="ct_重庆_133",
                        location=GeoPoint(lon=105.79484, lat=29.74688),
                    ),
                    _visit(
                        "v2",
                        "大足石刻数字影院",
                        city="重庆",
                        poi_id="ct_重庆_301",
                        location=GeoPoint(lon=105.78017, lat=29.74961),
                    ),
                ],
            ),
            DayPlan(
                day=3,
                base_city="重庆",
                items=[
                    _visit(
                        "v3",
                        "大足区大足石刻景区",
                        city="重庆",
                        poi_id="5a_243",
                        location=GeoPoint(lon=105.79484, lat=29.74688),
                    )
                ],
            ),
        ],
    )
    dropped = dedupe_plan_visits(plan)
    names = _visit_names(plan)
    assert sum(1 for n in names if "大足" in n) == 1
    assert names[0] == "大足石刻博物馆"  # 同 rank 保序：第一张胜出
    assert set(dropped) == {"大足石刻数字影院", "大足区大足石刻景区"}
    assert any("已合并重复站点" in a for a in plan.assumptions)


def test_content_dup_far_apart_same_core_not_merged():
    """地理闸：核心词相同但相距 >30km（内容通道闸）的两个同名异地
    分馆不并；~35km 实测距离落在闸外。"""
    from app.services.agent.plan import _same_visit
    from app.services.itinerary import GeoPoint

    a = _visit("v1", "大足石刻博物馆", location=GeoPoint(lon=105.79, lat=29.74))
    b = _visit(
        "v2",
        "大足石刻数字影院",
        location=GeoPoint(lon=106.10, lat=29.90),  # ~35km 外
    )
    assert _same_visit(a, b) is False


def test_content_dup_single_side_and_guards():
    """单侧剥过即可（伞名行 vs 配套行，2026-10-31 拍板放宽）；双侧
    裸名/无设施词的组合交给 containment；2 字核心词剥不动。"""
    from app.services.agent.plan import _content_core, _content_dup

    assert _content_dup("大足石刻", "大足石刻数字影院") is True  # 伞名 vs 配套
    assert _content_dup("大足石刻", "大足石刻博物馆") is True
    assert _content_dup("青城山", "青城山skydive跳伞基地") is False  # 双侧无设施词
    assert _content_dup("大足石刻", "都江堰水利工程") is False
    assert _content_core("苏州博物馆") == ("苏州博物馆", False)
    assert _content_core("大足石刻博物馆") == ("大足石刻", True)
    assert _content_core("大足区大足石刻景区") == ("大足石刻", True)
    assert _content_core("大足石刻数字影院") == ("大足石刻", True)


def test_same_visit_content_channel_uses_wide_gate():
    """跨集群同内容按 30km 闸合并（宝顶影院 vs 北山研究院伞名行
    ~8km，同一遗产两个摩崖集群）；>30km 仍不并。"""
    from app.services.agent.plan import _same_visit
    from app.services.itinerary import GeoPoint

    cinema = _visit(
        "v1",
        "大足石刻数字影院",
        location=GeoPoint(lon=105.78017, lat=29.74961),  # 宝顶
    )
    beishan = _visit(
        "v2",
        "大足石刻",
        location=GeoPoint(lon=105.71286, lat=29.70399),  # 北山研究院 ~8km
    )
    assert _same_visit(cinema, beishan) is True

    far = _visit(
        "v3",
        "大足石刻",
        location=GeoPoint(lon=106.50, lat=29.70),  # ~68km 外
    )
    assert _same_visit(cinema, far) is False


# --- 2026-10-31 碑林拍板：博物馆本体优先于伞形景区挂牌行 ---------------------


def test_museum_twin_replaces_umbrella_scenic():
    """「城墙·碑林历史文化景区」（5A 伞形挂牌）先入列、「西安碑林博物馆」
    后来 → 同站判定命中（词素 + ≤2km），博物馆替换胜出。"""

    from app.services.agent.plan import _dedupe_visit_keepers
    from app.services.itinerary.models import GeoPoint

    wall = _visit(
        "v1",
        "城墙·碑林历史文化景区",
        poi_id="5a_304",
        category="attraction",
        location=GeoPoint(lon=108.9405, lat=34.2569),
    )
    museum = _visit(
        "v2",
        "西安碑林博物馆",
        poi_id="amap_1",
        category="museum",
        location=GeoPoint(lon=108.9402, lat=34.2544),
    )
    keepers, dropped = _dedupe_visit_keepers([wall, museum])
    assert [k.name for k in keepers] == ["西安碑林博物馆"]
    assert dropped == ["城墙·碑林历史文化景区"]


def test_pinned_scenic_defends_against_museum_twin():
    """用户确认过（pinned）的景区卡不让位——博物馆层排在 pinned 之后。"""
    from datetime import time

    from app.services.agent.plan import _dedupe_visit_keepers
    from app.services.itinerary.models import GeoPoint

    wall = _visit(
        "v1",
        "城墙·碑林历史文化景区",
        poi_id="5a_304",
        category="attraction",
        pinned=True,
        start_time=time(9, 0),
        location=GeoPoint(lon=108.9405, lat=34.2569),
    )
    museum = _visit(
        "v2",
        "西安碑林博物馆",
        poi_id="amap_1",
        category="museum",
        location=GeoPoint(lon=108.9402, lat=34.2544),
    )
    keepers, _dropped = _dedupe_visit_keepers([wall, museum])
    assert [k.name for k in keepers] == ["城墙·碑林历史文化景区"]


def test_museum_shadow_pairs_and_far_twin():
    """候选层让位对：同站景区让位博物馆；异地（>2km）同名不并。"""
    from app.services.agent.plan import _museum_shadow_pairs

    near = [
        (
            0,
            {
                "name": "城墙·碑林历史文化景区",
                "category": "attraction",
                "location": {"lon": 108.9405, "lat": 34.2569},
            },
        ),
        (
            1,
            {
                "name": "兵马俑",
                "category": "attraction",
                "location": {"lon": 109.28, "lat": 34.38},
            },
        ),
        (
            2,
            {
                "name": "西安碑林博物馆",
                "category": "museum",
                "location": {"lon": 108.9402, "lat": 34.2544},
            },
        ),
    ]
    assert _museum_shadow_pairs(near) == [("城墙·碑林历史文化景区", "西安碑林博物馆")]
    far = [
        (0, near[0][1]),
        (
            2,
            {
                "name": "西安碑林博物馆",
                "category": "museum",
                "location": {"lon": 109.02, "lat": 34.28},
            },
        ),
    ]
    assert _museum_shadow_pairs(far) == []


# --- 2026-11-01 秦陵三行案：同馆配列桶（骊山园/遗址公园/兵马俑馆一票同站） ---


def test_heritage_dup_merges_qin_mausoleum_family():
    """秦始皇陵 ↔ 秦始皇兵马俑博物馆：互不包含、剥尾核心词不等（秦始皇陵

    vs 秦始皇兵马俑），containment/同内容/演出三通道全漏——同馆桶收拢。"""

    from app.services.agent.plan import _name_dup, _same_visit
    from app.services.itinerary import GeoPoint

    a = _visit("v1", "秦始皇陵", location=GeoPoint(lon=109.2589, lat=34.3803))

    b = _visit("v2", "秦始皇兵马俑博物馆", location=GeoPoint(lon=109.2820, lat=34.3862))

    assert _name_dup("秦始皇陵", "秦始皇兵马俑博物馆") is True

    assert _name_dup("兵马俑", "秦始皇陵国家考古遗址公园") is True

    assert _same_visit(a, b) is True  # ~3km：同馆 30km 闸内

    # 反例：别的博物馆/景点不进桶

    assert _name_dup("西安碑林博物馆", "秦始皇陵") is False

    assert _name_dup("西安城墙", "秦始皇兵马俑博物馆") is False


def test_dedupe_plan_keeps_single_qin_card():
    """端到端：D1 秦始皇陵 + D4 兵马俑（2026-11-01 用户事故形状）→ 全程

    只留一张秦陵卡，博物馆卡胜出（keep-rank 博物馆层），假设区留痕。"""

    from app.services.itinerary import GeoPoint

    plan = ItineraryPlan(
        itinerary_id="it-qin",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    _visit(
                        "v1",
                        "秦始皇陵",
                        city="西安",
                        poi_id="unesco_Q910180",
                        location=GeoPoint(lon=109.2589, lat=34.3803),
                    )
                ],
            ),
            DayPlan(
                day=4,
                base_city="西安",
                items=[
                    _visit(
                        "v2",
                        "秦始皇兵马俑博物馆",
                        city="西安",
                        poi_id="5a_296",
                        location=GeoPoint(lon=109.2820, lat=34.3862),
                    )
                ],
            ),
        ],
    )

    dropped = dedupe_plan_visits(plan)

    names = _visit_names(plan)

    assert names == ["秦始皇兵马俑博物馆"]  # 博物馆层胜出

    assert set(dropped) == {"秦始皇陵"}

    assert any("已合并重复站点" in a for a in plan.assumptions)


# --- 2026-11-01 秦陵双卡案：回填守卫全量同站判定 ------------------------------


def test_dup_blocks_item_full_name_dup_guard():
    """_dup_blocks_item（晨间保底/借调回填/干日回填共用守卫）：poi_id 相等、
    同馆桶（互不包含=事故根因）、包含通道都拦；同名异地 >30km 不拦
    （geo 闸）；无关联不拦。"""
    from app.services.agent.plan import _dup_blocks_item
    from app.services.itinerary import GeoPoint

    relic_park = _visit(
        "v1",
        "秦始皇陵国家考古遗址公园",
        poi_id="relicpark_0054",
        location=GeoPoint(lon=109.256, lat=34.380),
    )
    bmy_cand = {
        "name": "秦始皇兵马俑博物馆",
        "source_poi_id": "5a_296",
        "location": {"lon": 109.282, "lat": 34.386},
    }
    # 同馆桶：互不包含也拦（旧 _same_site 守卫拦不住=双卡事故根因）
    assert _dup_blocks_item(bmy_cand, relic_park) is True
    # poi_id 相等直接拦（名字无关）
    same_pid = {"name": "别名行", "source_poi_id": "relicpark_0054"}
    assert _dup_blocks_item(same_pid, relic_park) is True
    # 包含通道照旧生效
    contain_cand = {"name": "城墙·碑林历史文化景区", "source_poi_id": "5a_304"}
    assert _dup_blocks_item(contain_cand, _visit("v2", "城墙")) is True
    # 同馆名但异地 >30km：geo 闸放行（巡展/同名馆不是同站）
    far_show = _visit(
        "v3",
        "秦始皇兵马俑博物馆(异地巡展)",
        location=GeoPoint(lon=116.4, lat=39.9),
    )
    assert _dup_blocks_item(bmy_cand, far_show) is False
    # 无关联：不拦
    assert _dup_blocks_item(bmy_cand, _visit("v4", "西安城墙")) is False


def test_heritage_family_shadows_to_museum_card():
    """2026-11-01 用户拍板「当然选兵马俑」：同馆家族在池时骊山园/遗址
    公园行让位兵马俑博物馆本体（选点层影子，碑林拍板同款）；异地同馆
    名 >30km 不让位；大足类同内容家族维持「组装层合并、选点层双卡」
    既有语义不变。"""
    from app.services.agent.plan import _museum_shadow_pairs, _umbrella_cand_dup

    bmy = {
        "name": "秦始皇兵马俑博物馆",
        "category": "attraction",
        "location": {"lon": 109.2820, "lat": 34.3862},
    }
    park = {
        "name": "秦始皇陵国家考古遗址公园",
        "category": "attraction",
        "location": {"lon": 109.2561, "lat": 34.3800},
    }
    ling = {
        "name": "秦始皇陵",
        "category": "attraction",
        "location": {"lon": 109.2589, "lat": 34.3803},
    }
    pool = [(0, ling), (1, bmy), (2, park)]
    pairs = _museum_shadow_pairs(pool)
    assert set(pairs) == {
        ("秦始皇陵", "秦始皇兵马俑博物馆"),
        ("秦始皇陵国家考古遗址公园", "秦始皇兵马俑博物馆"),
    }

    # 异地同馆名（巡展）>30km：不让位
    far = {
        "name": "秦始皇陵(异地展馆)",
        "category": "attraction",
        "location": {"lon": 116.4, "lat": 39.9},
    }
    assert _umbrella_cand_dup(bmy, far) is False

    # 同馆家族 5km 闸边界：~8km 的同名遗产集群不让位（大足北山+宝顶类
    # 走 30km 内容闸在组装层合并，选点层各自入选）
    far_family = {
        "name": "秦始皇陵(北山区)",
        "category": "attraction",
        "location": {"lon": 109.28, "lat": 34.31},  # 距兵马俑 ~8.4km
    }
    assert _umbrella_cand_dup(bmy, far_family) is False

    # 大足类同内容家族：2026-11-01 拍板「核心词匹配运用到所有景点」——
    # 撤豁免后选点层也让位博物馆本体（旧「保双卡、组装层合并」退役）
    dazu_museum = {
        "name": "大足石刻博物馆",
        "category": "museum",
        "location": {"lon": 105.79484, "lat": 29.74688},
    }
    dazu_scenic = {
        "name": "大足区大足石刻景区",
        "category": "attraction",
        "location": {"lon": 105.79484, "lat": 29.74688},
    }
    assert _umbrella_cand_dup(dazu_museum, dazu_scenic) is True
