"""Tests for POST /api/v1/translate (design v2.0 §6.10/§6.12 fast lane).

App assembly mirrors tests/test_extract.py; stub adapters only.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.translate import get_translation_service
from app.api.translate import router as translate_router
from app.config import Settings, get_settings
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError
from app.services.translate import TranslationService

DEVICE_HEADERS = {"X-Device-ID": "device-1"}


class StubAdapter:
    name = "stub"

    def __init__(self, reply: str = "Hello") -> None:
        self.reply = reply
        self.chat_count = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.chat_count += 1
        return ChatResult(
            content=self.reply, model="stub-flash", tokens_in=10, tokens_out=20
        )


class ExplodingAdapter(StubAdapter):
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise LLMError("backend down")


def base_settings(**overrides) -> Settings:
    defaults = {
        "llm_backend": "mock",
        "translate_max_chars": 2_000,
        "translate_phrase_cache_max_entries": 4_096,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_app(settings: Settings, adapter: StubAdapter | None = None) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings
    if adapter is not None:
        # One service instance for the whole app: the phrase cache must
        # survive across requests (same as the production singleton).
        service = TranslationService(adapter)
        app.dependency_overrides[get_translation_service] = lambda: service
    app.include_router(translate_router)
    return app


def client_for(settings: Settings, adapter: StubAdapter | None = None) -> TestClient:
    return TestClient(make_app(settings, adapter))


def post(client: TestClient, body: dict, headers: dict | None = None):
    return client.post(
        "/api/v1/translate", json=body, headers=headers or DEVICE_HEADERS
    )


# --- happy path + cache flag ---


def test_200_returns_translation_usage_and_model():
    adapter = StubAdapter(reply="  Hello world  ")
    resp = post(
        client_for(base_settings(), adapter),
        {"text": "你好，世界", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "translated": "Hello world",
        "cached": False,
        "model": "stub-flash",
        "usage": {"tokens_in": 10, "tokens_out": 20},
    }
    assert adapter.chat_count == 1


def test_second_identical_request_reports_cached_true():
    adapter = StubAdapter()
    client = client_for(base_settings(), adapter)
    body = {"text": "这个多少钱", "source_lang": "zh", "target_lang": "en"}
    assert post(client, body).json()["cached"] is False
    second = post(client, body)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["usage"] == {"tokens_in": 0, "tokens_out": 0}
    assert adapter.chat_count == 1  # cache hit = zero LLM calls


# --- validation ---


def test_missing_device_id_returns_400():
    resp = client_for(base_settings(), StubAdapter()).post(
        "/api/v1/translate",
        json={"text": "你好", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}


def test_empty_text_returns_422():
    resp = post(
        client_for(base_settings(), StubAdapter()),
        {"text": "", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 422


def test_whitespace_only_text_returns_422_empty_text():
    resp = post(
        client_for(base_settings(), StubAdapter()),
        {"text": "   ", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "empty_text"}


def test_text_too_long_returns_422():
    resp = post(
        client_for(base_settings(translate_max_chars=10), StubAdapter()),
        {"text": "一" * 11, "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "text_too_long"}


def test_unsupported_language_pair_returns_422():
    resp = post(
        client_for(base_settings(), StubAdapter()),
        {"text": "你好", "source_lang": "zh", "target_lang": "ja"},
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "unsupported_language"}


def test_llm_error_maps_to_502():
    resp = post(
        client_for(base_settings(), ExplodingAdapter()),
        {"text": "你好", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 502
    assert resp.json() == {"detail": "llm_error"}


# --- factory wiring (mock backend default: no network) ---


def test_dependency_default_builds_service_from_settings():
    resp = post(
        client_for(base_settings()),
        {"text": "你好", "source_lang": "zh", "target_lang": "en"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock"
    assert body["cached"] is False
