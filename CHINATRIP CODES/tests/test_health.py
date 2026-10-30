def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "chinatrip-api"
    assert body["version"] == "0.1.0"
    assert "llm_backend" in body  # 2026-10-30: mock 泄漏可监控
