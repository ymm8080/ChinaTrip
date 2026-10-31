"""百度智能云语音翻译 ASR 后端单测（fake transport：OAuth+翻译两跳）。"""

import asyncio
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import asr as asr_module
from app.api.asr import get_asr_client, router
from app.config import Settings, get_settings
from app.services.asr_client import AsrError, BaiduVoiceTranslateClient

API_KEY = "qs7I8l60Jy8Zdh5TSHQVGhlz"
SECRET = "testsecret"
TOKEN = "tok.abc123"

OK = {"log_id": 1, "result": {"source": "你好", "target": "Hello"}}


def handler_token_then_ok(cap):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            qs = parse_qs(url.split("?", 1)[1])
            cap["oauth"] = qs
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        cap["url"] = url
        cap["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=OK)

    return handler


def make_baidu(handler, **kw) -> BaiduVoiceTranslateClient:
    return BaiduVoiceTranslateClient(
        api_key=API_KEY,
        secret_key=SECRET,
        timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
        **kw,
    )


def post_wav(app, data=b"RIFFxxxx"):
    c = TestClient(app)
    return c.post(
        "/api/v1/asr",
        files={"file": ("speech.wav", data, "audio/wav")},
        headers={"X-Device-ID": "dev-test"},
    )


def make_app(settings=None, client=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings or Settings()
    if client is not None:
        app.dependency_overrides[get_asr_client] = lambda: client
    return app


def test_happy_path_oauth_then_translate():
    cap = {}
    client = make_baidu(handler_token_then_ok(cap))
    out = asyncio.run(client.transcribe_full(b"RIFF123", filename="speech.wav"))
    assert out == {"text": "你好", "translated": "Hello"}
    qs = cap["oauth"]
    assert qs["grant_type"][0] == "client_credentials"
    assert qs["client_id"][0] == API_KEY and qs["client_secret"][0] == SECRET
    assert "access_token=" + TOKEN in cap["url"]
    body = cap["json"]
    assert body["from"] == "zh" and body["to"] == "en"
    assert base64.b64decode(body["voice"]) == b"RIFF123"
    assert body["format"] in ("pcm", "wav")


def test_token_cached_between_calls():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            calls["n"] += 1
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        return httpx.Response(200, json=OK)

    client = make_baidu(handler)
    asyncio.run(client.transcribe_full(b"RIFF123"))
    asyncio.run(client.transcribe_full(b"RIFF123"))
    assert calls["n"] == 1  # 第二次命中缓存


def test_oauth_failure_maps_asr_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "invalid_client", "error_description": "unknown client"}
        )

    client = make_baidu(handler)
    with pytest.raises(AsrError):
        asyncio.run(client.transcribe_full(b"RIFF123"))


def test_business_error_maps_asr_error():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        return httpx.Response(
            200, json={"error_code": 517, "error_msg": "Unknown Error Code"}
        )

    client = make_baidu(handler)
    with pytest.raises(AsrError):
        asyncio.run(client.transcribe_full(b"RIFF123"))


def test_non_200_translate_maps_asr_error():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        return httpx.Response(503, json={})

    client = make_baidu(handler)
    with pytest.raises(AsrError):
        asyncio.run(client.transcribe_full(b"RIFF123"))


def test_configured_requires_both():
    assert BaiduVoiceTranslateClient(api_key="", secret_key="").configured is False
    assert BaiduVoiceTranslateClient(api_key="a", secret_key="").configured is False
    assert BaiduVoiceTranslateClient(api_key="a", secret_key="k").configured is True


def test_endpoint_returns_translated_when_present():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        return httpx.Response(200, json=OK)

    app = make_app(
        settings=Settings(asr_backend="baidu_voice_trans"), client=make_baidu(handler)
    )
    r = post_wav(app)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "你好" and body["translated"] == "Hello"


def test_blank_keys_via_factory_503():
    saved = asr_module._client_singleton
    try:
        asr_module._client_singleton = None
        app = make_app(
            settings=Settings(
                asr_backend="baidu_voice_trans",
                baidu_bce_api_key="",
                baidu_bce_secret_key="",
            )
        )
        r = post_wav(app)
        assert r.status_code == 503
        assert r.json()["detail"] == "asr_not_configured"
    finally:
        asr_module._client_singleton = saved


def test_non_riff_audio_passthrough_pcm():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth/2.0/token" in url:
            return httpx.Response(
                200, json={"access_token": TOKEN, "expires_in": 2592000}
            )
        body = json.loads(request.content.decode("utf-8"))
        assert base64.b64decode(body["voice"]) == b"RAWBYTES"
        assert body["format"] == "pcm"
        return httpx.Response(200, json=OK)

    client = make_baidu(handler)
    out = asyncio.run(client.transcribe_full(b"RAWBYTES", filename="clip.mp3"))
    assert out == {"text": "你好", "translated": "Hello"}
