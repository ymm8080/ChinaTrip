import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.ratelimit import RateLimiter, RateLimitMiddleware
from app.middleware.usage import TraceIdMiddleware

USAGE_KEYS = {
    "ts",
    "trace_id",
    "device_id",
    "client_ip",
    "region",
    "method",
    "path",
    "status_code",
    "duration_ms",
}


class MutableClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_app(**mw_kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, **mw_kwargs)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def make_trace_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def usage_payload(caplog) -> dict:
    records = [r for r in caplog.records if r.name == "chinatrip.usage"]
    assert len(records) == 1
    return json.loads(records[0].message)


def test_limiter_allows_n_then_blocks():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=2, per_hour=10, clock=clock)
    assert limiter.check("k").allowed
    clock.now = 1
    assert limiter.check("k").allowed
    clock.now = 2
    result = limiter.check("k")
    assert not result.allowed
    assert result.retry_after >= 1


def test_limiter_minute_window_recovery():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=2, per_hour=100, clock=clock)
    assert limiter.check("k").allowed
    clock.now = 5
    assert limiter.check("k").allowed
    clock.now = 10
    assert not limiter.check("k").allowed
    clock.now = 60.5
    assert limiter.check("k").allowed


def test_limiter_hour_cap_triggers_after_minute_reset():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=2, per_hour=3, clock=clock)
    assert limiter.check("k").allowed
    clock.now = 10
    assert limiter.check("k").allowed
    clock.now = 100
    assert limiter.check("k").allowed
    clock.now = 110
    result = limiter.check("k")
    assert not result.allowed
    assert result.retry_after == 3600 - 110


def test_limiter_retry_after_decreases_as_clock_advances():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=1, per_hour=10, clock=clock)
    limiter.check("k")
    clock.now = 10
    first = limiter.check("k")
    clock.now = 30
    second = limiter.check("k")
    assert first.retry_after == 50
    assert second.retry_after == 30
    assert second.retry_after < first.retry_after


def test_limiter_retry_after_minimum_one_second():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=1, per_hour=10, clock=clock)
    limiter.check("k")
    clock.now = 59.999
    result = limiter.check("k")
    assert not result.allowed
    assert result.retry_after == 1


def test_limiter_blocked_hits_do_not_consume_capacity():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=1, per_hour=10, clock=clock)
    assert limiter.check("k").allowed
    clock.now = 10
    assert not limiter.check("k").allowed
    clock.now = 30
    assert not limiter.check("k").allowed
    clock.now = 61
    assert limiter.check("k").allowed


def test_limiter_independent_keys():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=1, per_hour=10, clock=clock)
    assert limiter.check("a").allowed
    assert limiter.check("b").allowed
    assert not limiter.check("a").allowed
    assert not limiter.check("b").allowed


def test_limiter_evicts_entries_older_than_hour():
    clock = MutableClock()
    limiter = RateLimiter(per_minute=10, per_hour=1, clock=clock)
    assert limiter.check("k").allowed
    clock.now = 3600.5
    assert limiter.check("k").allowed


def test_middleware_blocks_after_limit():
    client = TestClient(make_app(per_minute=2, per_hour=100))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    resp = client.get("/ping")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.json() == {"detail": "rate_limited"}


def test_middleware_independent_device_budgets():
    client = TestClient(make_app(per_minute=1, per_hour=100))
    assert client.get("/ping", headers={"X-Device-ID": "d1"}).status_code == 200
    assert client.get("/ping", headers={"X-Device-ID": "d2"}).status_code == 200
    assert client.get("/ping", headers={"X-Device-ID": "d1"}).status_code == 429
    assert client.get("/ping", headers={"X-Device-ID": "d2"}).status_code == 429


def test_middleware_limits_without_device_id():
    client = TestClient(make_app(per_minute=1, per_hour=100))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429


def test_middleware_exempt_path_bypasses_limit():
    client = TestClient(make_app(per_minute=1, per_hour=1))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429
    assert client.get("/health").status_code == 200


def test_trace_id_generated_and_logged(caplog):
    caplog.set_level(logging.INFO, logger="chinatrip.usage")
    client = TestClient(make_trace_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    trace_id = resp.headers["X-Trace-Id"]
    assert len(trace_id) == 32
    payload = usage_payload(caplog)
    assert set(payload) == USAGE_KEYS
    assert payload["trace_id"] == trace_id
    assert payload["device_id"] == "-"
    assert payload["client_ip"] == "testclient"
    assert payload["region"] == "CN"
    assert payload["method"] == "GET"
    assert payload["path"] == "/ping"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] >= 0


def test_trace_id_incoming_echoed(caplog):
    caplog.set_level(logging.INFO, logger="chinatrip.usage")
    client = TestClient(make_trace_app())
    resp = client.get("/ping", headers={"X-Trace-Id": "abc-123"})
    assert resp.headers["X-Trace-Id"] == "abc-123"
    payload = usage_payload(caplog)
    assert payload["trace_id"] == "abc-123"
