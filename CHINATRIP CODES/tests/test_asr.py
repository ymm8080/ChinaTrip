import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import asr as asr_api
from app.api.asr import get_asr_client, router
from app.config import Settings, get_settings
from app.services.asr_client import AsrClient

API_KEY = "test-key-123"
BASE_URL = "https://asr.test/paas/v4"


def make_client(handler) -> AsrClient:
    return AsrClient(
        key=API_KEY,
        base_url=BASE_URL,
        model="glm-asr-2512",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )


def make_app(handler=None, api_key: str = API_KEY) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    settings = Settings(glm_api_key=api_key)
    app.dependency_overrides[get_settings] = lambda: settings
    if handler is not None:
        asr = make_client(handler)
        app.dependency_overrides[get_asr_client] = lambda: asr
    return app


def captured_handler(captured: dict, status: int = 200, text: str = "我想去北京玩三天"):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type", "")
        body = request.content
        captured["has_model"] = b'name="model"' in body and b"glm-asr-2512" in body
        captured["has_file"] = b'name="file"' in body and b"RIFF" in body
        return httpx.Response(status, json={"id": "t1", "text": text})

    return handler


def post_wav(app: FastAPI, name: str = "speech.wav", data: bytes = b"RIFFxxxx", **kw):
    client = TestClient(app)
    return client.post(
        "/api/v1/asr",
        files={"file": (name, data, "audio/wav")},
        headers={"X-Device-ID": "dev-test"},
        **kw,
    )


def test_happy_path_returns_text_and_forwards_upstream():
    cap = {}
    app = make_app(captured_handler(cap))
    r = post_wav(app, data=b"RIFF" + b"\x00" * 100)
    assert r.status_code == 200
    assert r.json() == {"text": "我想去北京玩三天"}
    assert cap["auth"] == f"Bearer {API_KEY}"
    assert cap["has_model"] and cap["has_file"]
    assert cap["content_type"].startswith("multipart/form-data")


def test_missing_device_id_rejected():
    app = make_app(captured_handler({}))
    client = TestClient(app)
    r = client.post(
        "/api/v1/asr", files={"file": ("s.wav", b"RIFF123", "audio/wav")}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "missing_device_id"


def test_unsupported_format_rejected():
    app = make_app(captured_handler({}))
    r = post_wav(app, name="speech.webm", data=b"\x1a\x45\xdf\xa3webm")
    assert r.status_code == 422
    assert r.json()["detail"] == "unsupported_audio_format"


def test_empty_audio_rejected():
    app = make_app(captured_handler({}))
    r = post_wav(app, data=b"")
    assert r.status_code == 422
    assert r.json()["detail"] == "empty_audio"


def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(asr_api, "MAX_AUDIO_BYTES", 10)
    app = make_app(captured_handler({}))
    r = post_wav(app, data=b"RIFF" + b"\x00" * 32)
    assert r.status_code == 413
    assert r.json()["detail"] == "audio_too_large"


def test_no_key_503():
    app = make_app(captured_handler({}), api_key="")
    r = post_wav(app)
    assert r.status_code == 503
    assert r.json()["detail"] == "asr_not_configured"


def test_upstream_error_maps_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "boom"}})

    app = make_app(handler)
    r = post_wav(app)
    assert r.status_code == 502
    assert r.json()["detail"] == "asr_error"


def test_upstream_timeout_maps_504():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    app = make_app(handler)
    r = post_wav(app)
    assert r.status_code == 504
    assert r.json()["detail"] == "asr_timeout"


def test_non_string_text_coerced_to_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "t2", "text": None})

    app = make_app(handler)
    r = post_wav(app)
    assert r.status_code == 200
    assert r.json() == {"text": ""}


def test_asr_client_timeout_raises_asrtimeout():
    from app.services.asr_client import AsrTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route")

    client = make_client(handler)
    with pytest.raises(AsrTimeoutError):
        import asyncio

        asyncio.run(client.transcribe(b"RIFF123"))
