"""240h 过境免签校验测试（G2，DESIGN §14.3）：纯函数 + 端点。"""

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.itinerary.visa_check import (
    VISA_POLICY,
    check_240h_transit,
)

client = TestClient(create_app())


def test_all_allowed_cities_within_hours_is_ok():
    r = check_240h_transit(
        ["上海市", "杭州"],
        entry_date="2026-11-01",
        exit_date="2026-11-08",  # 168h
        entry_port="上海浦东",
    )
    assert r.status == "ok"
    assert r.stay_hours == 168
    assert any("以边检现场认定为准" in m for m in r.messages)
    assert any("联程客票" in m for m in r.messages)


def test_overstay_fails_with_hours():
    r = check_240h_transit(
        ["上海"],
        entry_date="2026-11-01",
        exit_date="2026-11-15",  # 336h > 240h
    )
    assert r.status == "fail"
    assert r.stay_hours == 336
    assert any("超过 240h" in m for m in r.messages)


def test_disallowed_province_fails():
    # 甘肃不在 v0 允许省域名单
    r = check_240h_transit(["兰州"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert r.status == "fail"
    assert any("不在 240h 免签允许省域" in m for m in r.messages)


def test_unknown_city_and_non_mainland_warn():
    r = check_240h_transit(
        ["上海", "神秘城", "香港"],
        entry_date="2026-11-01",
        exit_date="2026-11-05",
    )
    assert r.status == "warning"
    assert any("省份未收录" in m for m in r.messages)
    assert any("港澳台" in m for m in r.messages)


def test_missing_dates_warn_not_fail():
    r = check_240h_transit(["上海"])
    assert r.status == "warning"
    assert r.stay_hours is None
    assert any("停留时钟未校验" in m for m in r.messages)


def test_unknown_port_fails_but_names_are_snapshot_data():
    r = check_240h_transit(
        ["上海"],
        entry_date="2026-11-01",
        exit_date="2026-11-05",
        entry_port="某小口岸",
    )
    assert r.status == "fail"
    assert any("入境口岸" in m for m in r.messages)
    # 快照口径恒带来源与生效日期（可热更）
    assert VISA_POLICY["effective_date"]
    assert "校订" in VISA_POLICY["source"]


def test_api_endpoint_returns_banner_payload():
    resp = client.get(
        "/api/v1/visa/240h",
        params={
            "cities": "上海,杭州",
            "entry_date": "2026-11-01",
            "exit_date": "2026-11-08",
            "entry_port": "上海浦东",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["stay_hours"] == 168
    assert isinstance(body["messages"], list) and body["messages"]


# --- 2026-10-25 二轮校订（24 省勘误 + 市级范围 + 65 口岸全表） ------------------


def test_guizhou_in_scope_jilin_not():
    # 贵州属 24 省（v0 漏）；吉林省不在范围（v0 误入）
    r = check_240h_transit(["贵阳"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert not any("允许省域" in m for m in r.messages)
    r2 = check_240h_transit(["长春"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert r2.status == "fail"
    assert any("不在 240h 免签允许省域" in m for m in r2.messages)
    # 哈尔滨映射修复（黑龙江在范围，v0 误映射吉林导致假红）
    r3 = check_240h_transit(["哈尔滨"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert not any("允许省域" in m for m in r3.messages)


def test_city_scope_sichuan_shanxi():
    # 四川仅 11 市：阿坝（九寨沟）不可、乐山可；山西仅太原/大同
    r = check_240h_transit(["阿坝"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert r.status == "fail"
    assert any("允许活动范围" in m for m in r.messages)
    r2 = check_240h_transit(["乐山"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert not any("允许活动范围" in m for m in r2.messages)
    r3 = check_240h_transit(["太原"], entry_date="2026-11-01", exit_date="2026-11-05")
    assert not any("允许活动范围" in m for m in r3.messages)


def test_port_table_is_full_65_including_land_rail_water():
    air_water = VISA_POLICY["entry_ports"]
    assert len(air_water) == 65
    for port in ("深圳蛇口邮轮中心", "磨憨铁路口岸", "横琴口岸", "丽江三义"):
        r = check_240h_transit(
            ["上海"],
            entry_date="2026-11-01",
            exit_date="2026-11-05",
            entry_port=port,
        )
        assert not any("不在名单" in m for m in r.messages), port


def test_policy_snapshot_official_facts_2026_10_25():
    # 官方源校订回归钉：贵州属允许省域、吉林不在；65 口岸全量
    assert "贵州" in VISA_POLICY["provinces_allowed"]
    assert "吉林" not in VISA_POLICY["provinces_allowed"]
    assert len(VISA_POLICY["entry_ports"]) == 65
    # 2025-11-05 广东新增 5 口岸须在名单
    for port in (
        "广州琶洲港",
        "横琴口岸",
        "港珠澳大桥珠海口岸",
        "中山港",
        "香港西九龙",
    ):
        assert port in VISA_POLICY["entry_ports"]


def test_yunnan_city_scope_nine_prefectures():
    # 云南市级范围（9 市州）：昆明/大理/丽江/西双版纳可活动
    r = check_240h_transit(["昆明", "大理"])
    assert not any("允许活动范围" in m for m in r.messages)


def test_guilin_within_guangxi_scope_ok():
    r = check_240h_transit(["桂林", "南宁"])
    assert not any("允许活动范围" in m for m in r.messages)
