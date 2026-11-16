"""POI 同地名合并 / 补建（2026-11-16 朱家角案）单测。

口径来源（用户拍板）：
* 「we should set one record valid with all necessary information, another
  record to be inactive」——同城同地名内核的多行合并成一条有效记录；
* 「if sites is not in pois table, we should get address and transportation
  from amap」——库里没有才打图商（本文件只测选词/选行语义，不连网连库）。
"""

from __future__ import annotations

from app.services import poi_ingest as ingest
from app.services.poi_ingest import MapHit, PoiRow, merge_place, pick_hit
from app.services.poi_names import place_core


def _row(
    name: str,
    *,
    pid: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    address: str | None = None,
    category: str | None = None,
    duration: int | None = None,
    status: str = "active",
    source: str = "ctrip",
    spid: str | None = None,
    intro: str | None = None,
    name_en: str | None = None,
    aliases: list[str] | None = None,
) -> PoiRow:
    return PoiRow(
        id=pid or name,
        name=name,
        city="上海",
        status=status,
        source=source,
        source_poi_id=spid or name,
        category=category,
        address=address,
        lon=lon,
        lat=lat,
        duration_minutes=duration,
        name_en=name_en,
        intro=intro,
        name_aliases=list(aliases or []),
    )


def _zhujiajiao_rows() -> list[PoiRow]:
    return [
        # 今天的 ctrip 刷新刚建的骨架：有名字、没坐标没地址
        _row(
            "朱家角古镇",
            pid="ctrip",
            category="ancient_town",
            duration=180,
            source="ctrip",
            spid="ctrip:上海:朱家角古镇",
        ),
        # 名录行：坐标/地址/简介齐全（行政区地址）
        _row(
            "朱家角镇",
            pid="histown",
            lon=121.04651016252956,
            lat=31.103649244332725,
            address="上海市青浦区朱家角镇沙家埭路18号",
            category="ancient_town",
            duration=180,
            source="histown",
            name_en="Zhujiajiao Town",
            intro="朱家角镇是上海青浦区的江南水乡古镇。",
        ),
        # 4A 行（此前被退役）：景区名 + 景区坐标 + 游客中心地址
        _row(
            "朱家角古镇",
            pid="4a",
            lon=121.05052418499841,
            lat=31.11416165422822,
            address="上海市青浦区朱家角古镇游客中心",
            category="attraction",
            duration=90,
            source="4a",
            status="inactive",
            aliases=["朱家角古镇景区"],
        ),
    ]


# --- 名字内核 ---------------------------------------------------------------


def test_place_core_strips_generic_suffixes():
    assert place_core("朱家角古镇") == "朱家角"
    assert place_core("朱家角镇") == "朱家角"
    assert place_core("朱家角景区") == "朱家角"
    assert place_core("朱家角") == "朱家角"
    # 专名不误削：邮局不是通用尾缀
    assert place_core("朱家角大清邮局") == "朱家角大清邮局"
    assert place_core("西湖") == "西湖"
    assert place_core("朱家角古镇（青浦）") == "朱家角"
    # 英文全称同一口径（2026-11-16 用户「ZHUJIAJIAO 认不出」案）：只削聚落/
    # 景区类尾缀，园林/博物馆这类不动
    assert place_core("Zhujiajiao Ancient Town") == "Zhujiajiao"
    assert place_core("Wuzhen Water Town") == "Wuzhen"
    assert place_core("Shanghai Botanical Garden") == "Shanghai Botanical Garden"


# --- 图商命中挑选 -----------------------------------------------------------


def test_pick_hit_prefers_same_city_exact_name_with_address():
    hits = [
        MapHit(
            name="朱家角古镇",
            city="上海",
            lon=121.05,
            lat=31.11,
            address="青浦区课植园路555号",
        ),
        MapHit(name="朱家角镇人民政府", city="上海", lon=121.04, lat=31.10),
        MapHit(name="朱家角古镇", city="嘉兴", lon=120.9, lat=30.9),
    ]
    best = pick_hit("朱家角古镇", "上海", hits)
    assert best is not None
    assert best.city == "上海"
    assert best.address == "青浦区课植园路555号"


def test_pick_hit_skips_rows_without_location():
    hits = [MapHit(name="朱家角古镇", city="上海", lon=None, lat=None)]
    assert pick_hit("朱家角古镇", "上海", hits) is None


def test_pick_hit_rejects_unrelated_names():
    hits = [MapHit(name="上海朱家角宽璟酒店", city="上海", lon=121.02, lat=31.11)]
    # 「朱家角古镇」vs「上海朱家角宽璟酒店」形似度低 → 分数 < 30，不采用
    assert pick_hit("朱家角古镇", "上海", hits) is None


# --- 合并（一条有效，其余 inactive） ----------------------------------------


def test_merge_place_keeps_richest_active_row_and_retires_the_rest(monkeypatch):
    rows = _zhujiajiao_rows()
    monkeypatch.setattr(ingest, "_query_rows", lambda *a, **k: list(rows))

    result = merge_place("朱家角", "上海", dry_run=True)

    assert result is not None
    assert result.keeper.name == "朱家角镇"  # 信息最全的 active 行
    assert [r.name for r in result.retired] == ["朱家角古镇"]  # 只列现在还是 active 的
    assert "name_aliases" in result.filled  # 退役行的名字要并成别名


def test_merge_place_keep_id_can_force_the_scenic_row(monkeypatch):
    rows = _zhujiajiao_rows()
    monkeypatch.setattr(ingest, "_query_rows", lambda *a, **k: list(rows))

    result = merge_place("朱家角", "上海", dry_run=True, keep_id="4a")

    assert result is not None
    assert result.keeper.id == "4a"
    assert {r.name for r in result.retired} == {"朱家角镇", "朱家角古镇"}


def test_merge_place_geo_gate_keeps_far_same_name_rows_apart(monkeypatch):
    rows = [
        _row("南山", pid="a", lon=121.00, lat=31.00, address="A", category="nature"),
        _row("南山镇", pid="b", lon=121.55, lat=31.00, address="B", category="nature"),
    ]
    monkeypatch.setattr(ingest, "_query_rows", lambda *a, **k: list(rows))

    # 0.55 度经度 ≈ 52km > MERGE_MAX_KM(10km)：同名内核但确是两地，不合并
    assert merge_place("南山", "上海", dry_run=True) is None


def test_merge_place_single_row_returns_none(monkeypatch):
    monkeypatch.setattr(
        ingest, "_query_rows", lambda *a, **k: [_row("朱家角古镇", pid="only")]
    )
    assert merge_place("朱家角", "上海", dry_run=True) is None


# --- 行程级去重（同一地点两行各排一天） ------------------------------------


def test_dedupe_plan_visits_merges_town_suffix_twins():
    """朱家角实景：第1天「朱家角古镇」（骨架行无坐标）+ 第2天「朱家角镇」
    （名录行有坐标）——同一地点必须并成一张卡，有坐标那条胜出。"""
    from datetime import time as dtime

    from app.services.agent.plan import dedupe_plan_visits
    from app.services.itinerary import DayPlan, GeoPoint, ItineraryPlan, VisitItem

    day1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            VisitItem(
                item_id="v1",
                name="朱家角古镇",
                poi_id="ctrip:上海:朱家角古镇",
                category="景点",
                city="上海",
                day=1,
                start_time=dtime(13, 0),
                end_time=dtime(16, 30),
                duration_minutes=210,
            )
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="上海",
        items=[
            VisitItem(
                item_id="v2",
                name="朱家角镇",
                poi_id="ht_2ce7470eedc0",
                category="sight",
                city="上海",
                day=2,
                location=GeoPoint(lat=31.103649244332725, lon=121.04651016252956),
                pinned=True,
                start_time=dtime(13, 3),
                end_time=dtime(14, 3),
                duration_minutes=60,
            )
        ],
    )
    plan = ItineraryPlan(itinerary_id="it-zjj", cities=["上海"], days=[day1, day2])

    dropped = dedupe_plan_visits(plan)

    assert dropped == ["朱家角古镇"]
    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert names == ["朱家角镇"]


# --- 点名合并（only_ids：异名同地的 A 档候选） ------------------------------


def test_merge_place_only_ids_merges_cross_core_rows(monkeypatch):
    """洞庭东山 / 东山镇 内核不同，普通 merge_place 抓不到，only_ids 要能合。"""
    rows = [
        _row(
            "洞庭东山",
            pid="a",
            lon=120.40,
            lat=31.07,
            address="A",
            category="nature",
        ),
        _row(
            "东山镇",
            pid="b",
            lon=120.41,
            lat=31.07,
            address="B",
            category="ancient_town",
        ),
        _row("东山镇人民政府", pid="c", lon=120.42, lat=31.07),
    ]
    monkeypatch.setattr(ingest, "_query_rows", lambda *a, **k: list(rows))

    result = merge_place(
        "东山镇", "上海", dry_run=True, only_ids=["a", "b"], keep_id="a"
    )

    assert result is not None
    assert result.keeper.id == "a"
    assert [r.name for r in result.retired] == ["东山镇"]
    assert "name_aliases" in result.filled


def test_merge_place_only_ids_needs_two_rows(monkeypatch):
    monkeypatch.setattr(
        ingest, "_query_rows", lambda *a, **k: [_row("洞庭东山", pid="a")]
    )
    assert merge_place("洞庭东山", "上海", dry_run=True, only_ids=["a"]) is None


def test_merge_place_only_ids_rejects_far_rows(monkeypatch):
    """点名合并也要过 10km 地距闸：跨城标签可以（周庄=昆山/苏州），真远不行。"""
    from dataclasses import replace

    rows = [
        _row("洞庭东山", pid="a", lon=120.40, lat=31.07),
        replace(_row("东山镇", pid="b", lon=116.40, lat=39.90), city="北京"),
    ]
    monkeypatch.setattr(ingest, "_query_rows", lambda *a, **k: list(rows))
    assert merge_place("东山镇", "上海", dry_run=True, only_ids=["a", "b"]) is None
