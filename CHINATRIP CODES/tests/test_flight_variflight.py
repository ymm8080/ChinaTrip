# -*- coding: utf-8 -*-
"""VariFlight 适配骨架（2026-10-28 backlog）：装配闸门/映射/缓存/降级/解析.

契约路径待 key 注册后校正——本套件用 httpx.MockTransport 假传输层钉住
解析与装配语义，零真实网络。
"""

import asyncio

import httpx

from app.config import Settings
from app.services.flights import MockFlightService
from app.services.flights_variflight import (
    VariFlightFlightService,
    build_flight_service,
)


def _payload(*rows: object) -> dict:
    return {"flights": list(rows)}


def _ok_payload(*rows: dict) -> httpx.Response:
    return httpx.Response(200, json=_payload(*rows))


def _search(svc, frm="成都", to="上海", date="2026-11-05"):
    return asyncio.run(svc.search(frm, to, date))


# --- build_flight_service 装配闸门 -------------------------------------------


def test_empty_key_builds_mock():
    assert isinstance(
        build_flight_service(Settings(flight_api_key="")), MockFlightService
    )


def test_configured_key_builds_variflight():
    svc = build_flight_service(Settings(flight_api_key=" k123 "))
    assert isinstance(svc, VariFlightFlightService)
    assert svc._api_key == "k123"


# --- 城市映射与短路 -----------------------------------------------------------


def test_same_city_short_circuits_empty():
    svc = VariFlightFlightService(
        "k", transport=httpx.MockTransport(lambda *_: _ok_payload())
    )
    assert _search(svc, frm="成都", to="成都") == []


def test_unmapped_city_returns_empty_without_http():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_payload()

    svc = VariFlightFlightService("k", transport=httpx.MockTransport(handler))
    # 苏州无民航机场：不入映射，不发起 HTTP，直接 []
    assert _search(svc, frm="苏州", to="成都") == []
    assert calls == []
    # 市尾归一：杭州市 → 杭州 命中映射，发起请求
    assert _search(svc, frm="杭州市", to="成都") == []
    assert len(calls) == 1


# --- 缓存与降级 ---------------------------------------------------------------


def test_cache_hit_sends_one_request():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_payload(
            {"flightNo": "MU5101", "depTime": "09:00", "arrTime": "12:05"}
        )

    cache: dict = {}
    svc = VariFlightFlightService(
        "k", cache=cache, transport=httpx.MockTransport(handler)
    )
    first = _search(svc)
    second = _search(svc)
    assert len(calls) == 1  # 第二次命中缓存，零 HTTP
    assert first == second
    # duration 缺省 = 时刻差（09:00→12:05 = 185 分钟）
    assert [(o.flight_no, o.duration_minutes) for o in first] == [("MU5101", 185)]


def test_http_failure_degrades_to_empty_not_raise():
    svc = VariFlightFlightService(
        "k",
        transport=httpx.MockTransport(lambda *_: httpx.Response(502)),
    )
    assert _search(svc) == []


def test_stale_cache_serves_after_failure():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _ok_payload(
                {"flightNo": "3U8961", "depTime": "07:30", "arrTime": "10:20"}
            )
        return httpx.Response(500)

    svc = VariFlightFlightService(
        "k", cache_ttl_seconds=0.0, transport=httpx.MockTransport(handler)
    )
    first = _search(svc)
    # TTL=0 → 必发第二次；失败时陈旧缓存顶上（时刻表旧一点好过占位）
    second = _search(svc)
    assert [o.flight_no for o in first] == ["3U8961"]
    assert [o.flight_no for o in second] == ["3U8961"]
    assert len(calls) == 2


# --- 解析（契约字段防御性读取） ------------------------------------------------


def test_parse_rows_with_duration_and_cross_midnight():
    rows = _payload(
        {
            "flightNo": "MU1001",
            "depTime": "09:00",
            "arrTime": "12:00",
            "duration": 180,
        },
        {"flightNo": "CZ3907", "depTime": "2330", "arrTime": "0140"},  # 跨零点
        {"flightNo": "", "depTime": "09:00", "arrTime": "12:00"},  # 缺班号丢弃
        {"flightNo": "XX123", "depTime": "25:00", "arrTime": "26:00"},  # 非法时刻
        "garbage",  # 非法形状丢弃
    )
    out = VariFlightFlightService._parse(rows)
    assert [(o.flight_no, o.duration_minutes) for o in out] == [
        ("MU1001", 180),
        ("CZ3907", 130),
    ]


def test_parse_non_dict_payloads_empty():
    assert VariFlightFlightService._parse(None) == []
    assert VariFlightFlightService._parse([1, 2]) == []
    assert VariFlightFlightService._parse({"flights": None}) == []
