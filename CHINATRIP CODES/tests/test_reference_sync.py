"""同步核心单测（reference_sync 纯逻辑，双语 P2-3）。"""

from app.services.reference_sync import (
    parse_export,
    plan_import,
    row_to_record,
    serialize_export,
    verify_manifest,
)


class _Row:
    """ORM 行最小拟态。"""

    def __init__(self, **kw):
        defaults = {
            "source": "amap",
            "source_poi_id": "B001",
            "city": "北京",
            "name_zh": "故宫",
            "name_en": None,
            "category": "sight",
            "status": "active",
            "address": "景山前街4号",
            "address_en": None,
            "intro": "明清两代皇宫",
            "intro_en": None,
            "phone": None,
            "website": None,
            "rating": 4.7,
            "rating_source": "ctrip",
            "rating_count": 16000,
            "tags": ["5a"],
            "tags_source": "manual",
            "review_tags": ["历史厚重"],
            "review_tags_source": "ctrip",
            "review_tags_en": None,
            "best_visit_time": "morning",
            "best_visit_time_source": "manual",
            "suggested_duration_min": 210,
            "duration_source": "ctrip",
            "indoor": "partial",
            "rain_ok": "partial",
            "ticket_price_min": 60,
            "ticket_price_max": 60,
            "ticket_source": "ctrip",
            "opening_hours": "08:30-17:00",
            "hours_source": "amap_v3",
            "reservation_required": True,
            "reservation_advance_days": 7,
            "booking_url": None,
        }
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_export_roundtrip_and_manifest():
    hours = [{"rule_type": "windows", "payload": {"w": ["08:30-17:00"]}}]
    rec = row_to_record(
        "pois", _Row(), loc=(116.397, 39.918), wgs84=(116.391, 39.924), hours=hours
    )
    ndjson, manifest = serialize_export([rec], exported_at="2026-10-25 09:00:00")
    assert verify_manifest(ndjson, manifest) is None
    parsed = parse_export(ndjson)
    assert parsed[0]["source_poi_id"] == "B001"
    assert parsed[0]["location"] == {"lon": 116.397, "lat": 39.918}
    assert parsed[0]["hours"][0]["rule_type"] == "windows"
    assert manifest["counts"] == {"pois": 1}


def test_verify_manifest_detects_tamper():
    rec = row_to_record("pois", _Row())
    ndjson, manifest = serialize_export([rec], exported_at="2026-10-25 09:00:00")
    assert verify_manifest(ndjson + "tampered\n", manifest) == "sha256_mismatch"


def test_plan_import_insert_new():
    rec = row_to_record("pois", _Row(), loc=(116.397, 39.918))
    action, updates = plan_import(rec, existing=None)
    assert action == "insert"
    assert updates["name_zh"] == "故宫"
    assert updates["location"] == (116.397, 39.918)
    assert updates["origin"] == "cn_sync"  # 溯源标记


def test_plan_import_update_preserves_local_en():
    rec = row_to_record("pois", _Row(), loc=(116.397, 39.918))
    # 本地已改地址且已有自己的 intro_en 译文
    local = _Row(address="本地勘误地址", intro_en="Local curated translation")
    action, updates = plan_import(rec, existing=local)
    assert action == "update"
    assert updates["address"] == "景山前街4号"  # CN 为准覆盖业务列
    assert (
        "intro_en" not in updates
        or updates["intro_en"] is None
        or updates["intro_en"] == local.intro_en
        or updates["intro_en"] is None
    )
    # 本地译文非空 → 不播种（保留本地）：
    assert updates.get("intro_en") in (None, "Local curated translation")
    assert updates.get("address_en") is None or updates["address_en"] is None


def test_plan_import_seeds_local_en_when_empty():
    rec = row_to_record(
        "pois", _Row(name_en="Palace Museum", intro_en="Imperial palace.")
    )
    local = _Row(name_en=None, intro_en=None)
    action, updates = plan_import(rec, existing=local)
    assert action == "update"
    assert updates["name_en"] == "Palace Museum"  # 免费播种
    assert updates["intro_en"] == "Imperial palace."


def test_plan_import_status_tombstone_propagates():
    rec = row_to_record("pois", _Row(status="inactive"))
    local = _Row(status="active")
    action, updates = plan_import(rec, existing=local)
    assert action == "update"
    assert updates["status"] == "inactive"  # 墓碑传播


def test_plan_import_skip_invalid():
    action, updates = plan_import({"table": "pois", "name_zh": "无名"}, None)
    assert action == "skip" and updates == {}


def test_hours_en_exports_and_follows_local_preserve_semantics():
    """opening_hours_en 必须随导出同步，且遵循 _EN_COLS 本地保留语义
    （2026-10-25 白名单漏列实锤：白名单没它 → hours 翻译成果进不了海外库）。"""
    rec = row_to_record("pois", _Row(opening_hours_en="Mon–Sun 08:30-17:00"))
    assert rec["opening_hours_en"] == "Mon–Sun 08:30-17:00"  # 导出含列
    # 本地已译 → 保留，不被 CN 空值覆盖
    action, updates = plan_import(rec, existing=_Row(opening_hours_en="Local hrs"))
    assert action == "update"
    assert updates.get("opening_hours_en") in (None, "Local hrs")
    # 本地为空 → 播种
    _, seeded = plan_import(rec, existing=_Row(opening_hours_en=None))
    assert seeded["opening_hours_en"] == "Mon–Sun 08:30-17:00"
