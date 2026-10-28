# -*- coding: utf-8 -*-
"""订单回填三层管道测试（设计 v2.4 §6.11）。

parse_order_text 纯函数独立单测（含无订单号/纯数字噪声边界）+
状态机全弧（opened→user_confirmed→settled/returned、undo 回退、
alliance_api 不可撤、conf<0.8 不写、联盟匹配/跳过）+
PG 写穿钩子（create/推进后 best-effort 落 action_handoffs）。
"""

import uuid as _uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.backfill import get_handoff_store
from app.api.backfill import router as backfill_router
from app.services.backfill import (
    AllianceFeedItem,
    HandoffStore,
    parse_order_text,
    persist_handoff,
)

TRAIN_SMS = "【铁路客服中心】您已购12月05日G101次列车，订单号E123456789，请提前到站。"
CTRIP_SMS = "携程订单确认：订单号1234567890，实付¥358.00，出票成功。"


def make_app() -> FastAPI:
    """TestClient 迷你 app（test_navigation_api.py 同款）：每个 app 绑一个新 store。"""
    app = FastAPI()
    app.include_router(backfill_router)
    store = HandoffStore()
    app.dependency_overrides[get_handoff_store] = lambda: store
    return app


def create_handoff(client: TestClient, **overrides) -> dict:
    body = {
        "action_type": "train",
        "channel": "12306",
        "url": "https://kyfw.12306.cn/otn/leftTicket/init",
        "refund_summary": "开车前8天以上退票免费",
    }
    body.update(overrides)
    resp = client.post("/api/v1/backfill/handoffs", json=body)
    assert resp.status_code == 201
    return resp.json()


def _by_id(records: list[dict], record_id: str) -> dict:
    return next(r for r in records if r["id"] == record_id)


# --- parse_order_text 纯函数 ---------------------------------------------------


def test_parse_train_sms_anchor_without_channel_keyword():
    parsed = parse_order_text(TRAIN_SMS)
    assert parsed.order_ref == "E123456789"
    assert parsed.channel is None  # 无 12306 字面量/渠道关键词
    assert parsed.amount_yuan is None
    assert parsed.confidence == 0.75


def test_parse_ctrip_sms_full_hit():
    parsed = parse_order_text(CTRIP_SMS)
    assert parsed.order_ref == "1234567890"
    assert parsed.channel == "ctrip"
    assert parsed.amount_yuan == 358.0
    assert parsed.confidence == 0.9


def test_parse_qunar_danhao_anchor_and_yuan_amount():
    parsed = parse_order_text("去哪儿网出票成功 单号 MM500123456 实付款 880.50元")
    assert parsed.order_ref == "MM500123456"
    assert parsed.channel == "qunar"
    assert parsed.amount_yuan == 880.5
    assert parsed.confidence == 0.9


def test_parse_meituan_paid_amount():
    parsed = parse_order_text("美团订单已支付45.6元 订单号MT9876543210")
    assert parsed.order_ref == "MT9876543210"
    assert parsed.channel == "meituan"
    assert parsed.amount_yuan == 45.6
    assert parsed.confidence == 0.9


def test_parse_without_order_ref_zero_confidence():
    parsed = parse_order_text("您已购12月05日G101次列车，请持身份证进站乘车")
    assert parsed.order_ref is None
    assert parsed.channel is None
    assert parsed.confidence == 0.0


def test_parse_pure_digit_noise_falls_back_with_low_confidence():
    # 客服热线是 10 位数字：fallback 会当成候选订单号，但无渠道 → 0.75 <0.8，
    # apply 时进待确认，不会被写入。
    parsed = parse_order_text("客服热线4001234567，营业时间8:00-22:00")
    assert parsed.order_ref == "4001234567"
    assert parsed.channel is None
    assert parsed.amount_yuan is None
    assert parsed.confidence == 0.75


def test_parse_refund_amount_without_order_ref():
    parsed = parse_order_text("退款已到账，总额99.00元")
    assert parsed.order_ref is None
    assert parsed.amount_yuan == 99.0
    assert parsed.confidence == 0.0


def test_parse_english_order_hash_anchor():
    parsed = parse_order_text("CONFIRMED Order #AB12CD34EF via gateway")
    assert parsed.order_ref == "AB12CD34EF"
    assert parsed.channel is None
    assert parsed.confidence == 0.75


# --- POST /handoffs：跳转埋点 ---------------------------------------------------


def test_create_handoff_returns_201_opened():
    with TestClient(make_app()) as client:
        record = create_handoff(client)
    assert record["status"] == "opened"
    assert record["action_type"] == "train"
    assert record["channel"] == "12306"
    assert record["order_ref"] is None
    assert record["source_channel"] is None
    assert record["refund_summary"] == "开车前8天以上退票免费"
    assert len(record["id"]) == 32  # uuid4().hex


def test_create_handoff_invalid_channel_returns_422():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/backfill/handoffs",
            json={"action_type": "boat", "channel": "fliggy", "url": "https://x"},
        )
    assert resp.status_code == 422


def test_create_handoff_accepts_show_flavour_types_and_channels():
    """演出路径 A（show_booking P0+）：site_ticket / klook / other 放行。"""
    with TestClient(make_app()) as client:
        r1 = client.post(
            "/api/v1/backfill/handoffs",
            json={
                "action_type": "site_ticket",
                "channel": "klook",
                "url": "https://www.klook.com/x",
                "refund_summary": "以下单页为准",
            },
        )
        assert r1.status_code == 201
        assert r1.json()["action_type"] == "site_ticket"
        assert r1.json()["channel"] == "klook"
        r2 = client.post(
            "/api/v1/backfill/handoffs",
            json={"action_type": "site_ticket", "channel": "other", "url": "https://x"},
        )
        assert r2.status_code == 201


# --- 主通道：粘贴回填 ------------------------------------------------------------


def test_paste_return_high_confidence_confirms():
    with TestClient(make_app()) as client:
        record = create_handoff(client, action_type="hotel", channel="ctrip")
        resp = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True
    assert "reason" not in body
    assert body["parsed"]["confidence"] == 0.9
    assert body["record"]["status"] == "user_confirmed"
    assert body["record"]["source_channel"] == "paste_return"
    assert body["record"]["order_ref"] == "1234567890"


def test_paste_return_low_confidence_needs_confirm_and_writes_nothing():
    with TestClient(make_app()) as client:
        record = create_handoff(client)  # channel=12306，短信无渠道字面量 → 0.75
        resp = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": TRAIN_SMS},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is False
    assert body["reason"] == "needs_confirm"
    assert body["record"]["status"] == "opened"
    assert body["record"]["order_ref"] is None
    assert body["record"]["source_channel"] is None


def test_paste_return_record_channel_literal_boosts_confidence():
    # 文本无「携程」关键词但有 ctrip 字面量 → 记录原 channel 命中 → 0.9 写入
    with TestClient(make_app()) as client:
        record = create_handoff(client, channel="ctrip")
        resp = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": "Ctrip订单确认 订单号E123456789"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True
    assert body["parsed"]["confidence"] == 0.9
    assert body["record"]["status"] == "user_confirmed"


def test_paste_return_after_confirmation_returns_422():
    with TestClient(make_app()) as client:
        record = create_handoff(client, channel="ctrip")
        first = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
    assert second.status_code == 422
    assert second.json()["detail"] == "invalid_transition"


def test_paste_return_unknown_handoff_returns_404():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/backfill/handoffs/deadbeef/paste-return",
            json={"text": CTRIP_SMS},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "handoff_not_found"


# --- 兜底通道：手动标记 ----------------------------------------------------------


def test_manual_confirms_opened_handoff():
    with TestClient(make_app()) as client:
        record = create_handoff(client)
        resp = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/manual",
            json={"order_ref": "MZ000999"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "user_confirmed"
    assert body["source_channel"] == "manual"
    assert body["order_ref"] == "MZ000999"


def test_manual_on_confirmed_handoff_returns_422():
    with TestClient(make_app()) as client:
        record = create_handoff(client, channel="ctrip")
        pasted = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
        assert pasted.status_code == 200
        resp = client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/manual",
            json={"order_ref": "MZ000999"},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_transition"


# --- 可撤销 ---------------------------------------------------------------------


def test_undo_restores_opened_and_clears_fields():
    with TestClient(make_app()) as client:
        record = create_handoff(client)
        client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/manual",
            json={"order_ref": "MZ000999"},
        )
        resp = client.post(f"/api/v1/backfill/handoffs/{record['id']}/undo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "opened"
    assert body["order_ref"] is None
    assert body["source_channel"] is None


def test_undo_alliance_advanced_handoff_returns_422():
    with TestClient(make_app()) as client:
        record = create_handoff(client, channel="ctrip")
        client.post(
            f"/api/v1/backfill/handoffs/{record['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
        client.post(
            "/api/v1/backfill/alliance-sync",
            json={"orders": [{"order_ref": "1234567890", "outcome": "settled"}]},
        )
        resp = client.post(f"/api/v1/backfill/handoffs/{record['id']}/undo")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_transition"


def test_undo_on_opened_handoff_returns_422():
    with TestClient(make_app()) as client:
        record = create_handoff(client)
        resp = client.post(f"/api/v1/backfill/handoffs/{record['id']}/undo")
    assert resp.status_code == 422


# --- 返回询问：列表过滤 ----------------------------------------------------------


def test_list_handoffs_filters_by_status():
    with TestClient(make_app()) as client:
        confirmed = create_handoff(client, channel="ctrip", action_type="hotel")
        create_handoff(client, action_type="flight", channel="qunar")
        client.post(
            f"/api/v1/backfill/handoffs/{confirmed['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
        all_records = client.get("/api/v1/backfill/handoffs").json()
        opened = client.get(
            "/api/v1/backfill/handoffs", params={"status": "opened"}
        ).json()
    assert len(all_records) == 2
    assert len(opened) == 1
    assert opened[0]["action_type"] == "flight"


# --- 自动通道：联盟订单同步（MVP mock） ------------------------------------------


def test_alliance_sync_settles_refunds_and_skips():
    with TestClient(make_app()) as client:
        settled = create_handoff(client, channel="ctrip")
        refunded = create_handoff(client)
        client.post(
            f"/api/v1/backfill/handoffs/{settled['id']}/paste-return",
            json={"text": CTRIP_SMS},
        )
        client.post(
            f"/api/v1/backfill/handoffs/{refunded['id']}/manual",
            json={"order_ref": "MZ000999"},
        )
        resp = client.post(
            "/api/v1/backfill/alliance-sync",
            json={
                "orders": [
                    {"order_ref": "1234567890", "outcome": "settled"},
                    {"order_ref": "MZ000999", "outcome": "refunded"},
                    {"order_ref": "NOPE9999XX", "outcome": "settled"},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] == 2
        assert body["advanced"] == [settled["id"], refunded["id"]]
        assert body["skipped"] == 1
        records = client.get("/api/v1/backfill/handoffs").json()
        assert _by_id(records, settled["id"])["status"] == "settled"
        assert _by_id(records, settled["id"])["source_channel"] == "alliance_api"
        assert _by_id(records, refunded["id"])["status"] == "returned"
        # 重放同 feed：已离开 user_confirmed → 全跳过
        replay = client.post(
            "/api/v1/backfill/alliance-sync",
            json={
                "orders": [
                    {"order_ref": "1234567890", "outcome": "settled"},
                    {"order_ref": "MZ000999", "outcome": "refunded"},
                ]
            },
        ).json()
        assert replay == {"matched": 0, "advanced": [], "skipped": 2}


def test_alliance_sync_skips_opened_unconfirmed_handoff():
    with TestClient(make_app()) as client:
        create_handoff(client)  # 停在 opened，order_ref 未落
        resp = client.post(
            "/api/v1/backfill/alliance-sync",
            json={"orders": [{"order_ref": "ABCDEF123456", "outcome": "settled"}]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"matched": 0, "advanced": [], "skipped": 1}
        records = client.get("/api/v1/backfill/handoffs").json()
        assert records[0]["status"] == "opened"


# --- 路由接线守卫 -----------------------------------------------------------------


def test_router_wires_all_six_endpoints():
    paths = {route.path for route in backfill_router.routes}
    assert {
        "/api/v1/backfill/handoffs",
        "/api/v1/backfill/handoffs/{record_id}/paste-return",
        "/api/v1/backfill/handoffs/{record_id}/undo",
        "/api/v1/backfill/handoffs/{record_id}/manual",
        "/api/v1/backfill/alliance-sync",
    } <= paths


# --- PG 写穿钩子（action_handoffs 账本，2026-10-27 演出预订补全） ---------------


def test_persistence_hook_called_on_create_and_transitions():
    store = HandoffStore()
    seen: list = []
    store.attach_persistence(seen.append)
    rec = store.create(
        action_type="site_ticket", channel="ctrip", url="https://x", refund_summary="s"
    )
    assert seen[-1].id == rec.id and seen[-1].status == "opened"
    store.apply_manual(rec.id, "AB12CD34")
    assert seen[-1].status == "user_confirmed"
    store.undo(rec.id)
    assert seen[-1].status == "opened"
    store.apply_manual(rec.id, "AB12CD34")
    store.alliance_sync([AllianceFeedItem(order_ref="AB12CD34", outcome="settled")])
    assert seen[-1].status == "settled"


def test_persistence_hook_failure_logged_and_swallowed(caplog):
    """DB 缺席：钩子异常只留日志（铁律），内存态照常推进。"""
    store = HandoffStore()

    def boom(record):
        raise RuntimeError("pg down")

    store.attach_persistence(boom)
    rec = store.create(action_type="site_ticket", channel="klook", url="https://x")
    assert rec.status == "opened"
    with caplog.at_level("WARNING"):
        store.apply_manual(rec.id, "AB12CD34")
    assert rec.status == "user_confirmed"
    assert any("handoff_persist_failed" in r.message for r in caplog.records)


def test_persist_handoff_insert_then_update(monkeypatch):
    import app.db as db_mod

    class FakeSession:
        def __init__(self):
            self.store: dict = {}
            self._added: list = []

        def get(self, model, rid):
            return self.store.get(rid)

        def add(self, obj):
            self._added.append(obj)

        def commit(self):
            for o in self._added:
                self.store[o.id] = o
            self._added.clear()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    sess = FakeSession()
    monkeypatch.setattr(db_mod, "get_session_factory", lambda: lambda: sess)
    rec = HandoffStore().create(
        action_type="site_ticket",
        channel="ctrip",
        url="https://u",
        refund_summary="退改以下单页为准",
    )
    persist_handoff(rec)
    rid = _uuid.UUID(rec.id)
    assert rid in sess.store
    row = sess.store[rid]
    assert row.action_type == "site_ticket"
    assert row.deeplink == "https://u"
    assert row.status == "opened"
    assert row.refund_policy == {"summary": "退改以下单页为准"}
    # 推进后再写穿 → 走 update 分支（不新增行）
    rec.status = "user_confirmed"
    rec.order_ref = "AB12CD34"
    rec.source_channel = "paste_return"
    persist_handoff(rec)
    assert len(sess.store) == 1
    assert sess.store[rid].status == "user_confirmed"
    assert sess.store[rid].order_ref == "AB12CD34"


# --- 演出渠道别名（klook 关键词 / trip.com 记录命中） ----------------------------


def test_parse_klook_keyword_lowercase():
    parsed = parse_order_text("Klook预订成功 订单号KL12345678")
    assert parsed.order_ref == "KL12345678"
    assert parsed.channel == "klook"
    assert parsed.confidence == 0.9


def test_record_channel_tripcom_alias_boosts_confidence():
    store = HandoffStore()
    rec = store.create(
        action_type="site_ticket", channel="ctrip", url="https://trip.com/x"
    )
    record, parsed, applied, reason = store.apply_paste_return(
        rec.id, "Trip.com order confirmed 订单号AB12CD34EF"
    )
    assert applied is True
    assert parsed.confidence == 0.9
    assert record.status == "user_confirmed"
