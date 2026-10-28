from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


def make_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        llm_backend="mock", amap_api_key="", map_provider="amap"
    )
    return TestClient(app)


def test_health_has_trace_id(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("x-trace-id")


def test_extract_mounted_with_mock_backend():
    with make_client() as c:
        resp = c.post(
            "/api/v1/extract",
            json={"text": "- 外滩\n? 田子坊"},
            headers={"X-Device-ID": "dev-1"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock"
    assert body["quarantined"] is False
    statuses = {c["name"]: c["status"] for c in body["candidates"]}
    assert statuses["外滩"] == "confirmed"
    assert statuses["田子坊"] == "pending_confirmation"


def test_extract_requires_device_id():
    with make_client() as c:
        resp = c.post("/api/v1/extract", json={"text": "- 外滩"})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}


def test_amap_mounted_unconfigured_returns_503():
    with make_client() as c:
        resp = c.get("/api/v1/amap/poi/search", params={"keywords": "外滩"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "amap_not_configured"}


def test_health_exempt_from_rate_limit():
    with make_client() as c:
        for _ in range(70):
            resp = c.get("/health")
            assert resp.status_code == 200
