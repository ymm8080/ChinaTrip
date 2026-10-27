# -*- coding: utf-8 -*-
"""出行人资料层测试（DESIGN/CLIENT_DATA_REQUIREMENTS.md，2026-10-27）。

覆盖：加密落盘往返（库文件里翻不到明文）；列表/读取只回脱敏形；
export 唯一明文出口 + 审计留痕；consent=false 422；删除/清空物理删除；
归属隔离（device/账号互不可见）；参数校验（doc_type/gender/上限）。
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api import travelers as tapi
from app.main import create_app
from app.services import travelers as tsvc

client = TestClient(create_app())
DEVICE = {"X-Device-ID": "dev-trv"}

_VALID = dict(
    label="本人护照",
    full_name_en="SMITH JOHN",
    doc_type="passport",
    doc_number="E12345678",
    nationality="US",
    date_of_birth="1990-01-02",
    gender="m",
    phone="+12025550123",
    email="john@example.com",
    consent=True,
)


def _settings(tmp_path):
    class _S:
        travelers_db_url = f"sqlite:///{tmp_path / 't.db'}"

    return _S()


def _patch_env(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(tsvc, "get_settings", lambda: s)
    monkeypatch.setattr(tapi, "_get_travelers_service", tsvc.get_travelers_service)
    monkeypatch.setattr(tsvc, "_service_singleton", None)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    return tmp_path


# --- store 单元 ----------------------------------------------------------------


def test_store_roundtrip_encrypted_at_rest(tmp_path):
    db = str(tmp_path / "t.db")
    store = tsvc.TravelerStore(db)
    store.create("u1", tsvc.TravelerInput(**_VALID))
    # 落库的是 Fernet 密文：明文证件号/手机号绝不能出现在 db 文件里
    raw = (tmp_path / "t.db").read_bytes()
    assert b"E12345678" not in raw
    assert b"+12025550123" not in raw
    # 重启重载后仍是脱敏形 + 能解密（export 才回明文）
    store2 = tsvc.TravelerStore(db)
    rows = store2.list_for_owner("u1")
    assert rows[0]["doc_number_masked"] == "E1234**78"
    assert "doc_number" not in rows[0]
    exported = store2.export_plaintext("u1")
    assert exported[0]["doc_number"] == "E12345678"


def test_consent_required(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    with pytest.raises(tsvc.InvalidTraveler):
        store.create("u1", tsvc.TravelerInput(**{**_VALID, "consent": False}))


def test_owner_isolation_and_delete_all(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    a = store.create("device:d1", tsvc.TravelerInput(**_VALID))
    store.create("alice", tsvc.TravelerInput(**_VALID))
    assert len(store.list_for_owner("device:d1")) == 1
    assert len(store.list_for_owner("alice")) == 1
    assert store.list_for_owner("bob") == []
    assert store.delete_all("device:d1") == 1
    assert store.list_for_owner("device:d1") == []
    with pytest.raises(tsvc.TravelerNotFound):
        store.delete("device:d1", a["id"])
    # 物理删除：库里没有残留行
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT COUNT(*) FROM travelers").fetchone()[0] == 1


def test_audit_trail_records_actions_not_values(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    created = store.create("u1", tsvc.TravelerInput(**_VALID))
    store.update("u1", created["id"], tsvc.TravelerInput(**_VALID))
    store.export_plaintext("u1")
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    actions = [r[0] for r in conn.execute("SELECT action FROM travel_data_audit")]
    assert actions == ["create", "update", "export"]
    # 审计表不含任何字段值
    dump = "\n".join(conn.iterdump())
    assert "E12345678" not in dump


def test_update_masks_new_number(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    created = store.create("u1", tsvc.TravelerInput(**_VALID))
    updated = store.update(
        "u1", created["id"], tsvc.TravelerInput(**{**_VALID, "doc_number": "PE123456"})
    )
    assert updated["doc_number_masked"] == "PE123*56"
    assert store.export_plaintext("u1")[0]["doc_number"] == "PE123456"


def test_too_many_travelers(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    for _ in range(tsvc.MAX_TRAVELERS_PER_OWNER):
        store.create("u1", tsvc.TravelerInput(**_VALID))
    with pytest.raises(tsvc.InvalidTraveler):
        store.create("u1", tsvc.TravelerInput(**_VALID))


def test_short_doc_number_masked(tmp_path):
    store = tsvc.TravelerStore(str(tmp_path / "t.db"))
    created = store.create("u1", tsvc.TravelerInput(**{**_VALID, "doc_number": "AB12"}))
    assert created["doc_number_masked"] == "****"


# --- API -----------------------------------------------------------------------


def test_api_full_flow(env):
    r = client.post("/api/v1/travelers", json=_VALID, headers=DEVICE)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["doc_number_masked"] == "E1234**78"
    assert "doc_number" not in created
    assert created["consent"] is True and created["consent_at"]

    # 列表：脱敏 + 同意书文案
    r = client.get("/api/v1/travelers", headers=DEVICE)
    body = r.json()
    assert body["consent_notice"]
    assert len(body["travelers"]) == 1
    assert body["travelers"][0]["phone_masked"].startswith("+1202")

    # 修改
    r = client.put(
        f"/api/v1/travelers/{created['id']}",
        json={**_VALID, "label": "Mom"},
        headers=DEVICE,
    )
    assert r.status_code == 200 and r.json()["label"] == "Mom"

    # 导出（明文唯一出口）
    r = client.get("/api/v1/travelers/export", headers=DEVICE)
    assert r.json()["travelers"][0]["doc_number"] == "E12345678"

    # 删除单条 + 404
    assert (
        client.delete(f"/api/v1/travelers/{created['id']}", headers=DEVICE).status_code
        == 204
    )
    assert (
        client.delete(f"/api/v1/travelers/{created['id']}", headers=DEVICE).status_code
        == 404
    )


def test_api_guards(env):
    # 缺设备头
    assert client.post("/api/v1/travelers", json=_VALID).status_code == 400
    # consent=false → 422
    r = client.post(
        "/api/v1/travelers", json={**_VALID, "consent": False}, headers=DEVICE
    )
    assert r.status_code == 422 and r.json()["detail"] == "consent_required"
    # 非法证件类型
    r = client.post(
        "/api/v1/travelers", json={**_VALID, "doc_type": "club_card"}, headers=DEVICE
    )
    assert r.status_code == 422 and r.json()["detail"] == "invalid_doc_type"
    # 清空
    r = client.delete("/api/v1/travelers", headers=DEVICE)
    assert r.status_code == 200 and r.json()["deleted"] == 0
