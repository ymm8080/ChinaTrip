"""火车班次日缓存层测试（全离线：tmp_path sqlite + 可编程 inner 桩）。"""

import asyncio
from datetime import date as date_cls
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.services.train_cache as train_cache_module
from app.config import Settings
from app.models import Base
from app.services.train_cache import (
    CachedTrainService,
    TrainScheduleRecord,
    _resolve_query_date,
    refresh_train_cache,
)
from app.services.trains import (
    CtripTrainSource,
    MeituanTrainSource,
    MockTrainService,
    RemoteTrainService,
    TrainOption,
)

DATE = "2026-11-03"
BASE_NOW = datetime(2026, 10, 18, 8, 0, 0)


def _option(train_no: str, dep: time = time(8, 0), arr: time = time(12, 0)):
    return TrainOption(
        train_no=train_no,
        dep_time=dep,
        arr_time=arr,
        duration_minutes=(arr.hour * 60 + arr.minute)
        - (dep.hour * 60 + dep.minute),
        from_station="北京南",
        to_station="上海虹桥",
        from_city="北京",
        to_city="上海",
        date=DATE,
    )


class ScriptedInner:
    """可编程 inner：按 results 队列逐次返回班次/抛错，并计数调用。"""

    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.calls = 0
        self.last_source = "stub"

    async def search(self, from_city: str, to_city: str, date: str):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return list(result)


class _Clock:
    """可拨动的时钟（TTL 测试不依赖真实时间流逝）。"""

    def __init__(self) -> None:
        self.now = BASE_NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/cache.db")
    Base.metadata.create_all(engine, tables=[TrainScheduleRecord.__table__])
    yield sessionmaker(bind=engine)
    engine.dispose()


def _row_count(session_factory) -> int:
    with session_factory() as session:
        return session.execute(
            select(func.count()).select_from(TrainScheduleRecord)
        ).scalar_one()


def test_miss_then_hit_avoids_inner(session_factory):
    inner = ScriptedInner([[_option("G1"), _option("G3")]])
    service = CachedTrainService(session_factory=session_factory, inner=inner)

    first = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in first] == ["G1", "G3"]
    assert inner.calls == 1  # miss -> 打 inner -> 落库
    assert _row_count(session_factory) == 2

    second = asyncio.run(service.search("北京", "上海", DATE))
    assert second == first  # 命中缓存，结果一致
    assert inner.calls == 1  # 零网络


def test_ttl_expiry_repulls_and_keeps_history(session_factory):
    clock = _Clock()
    inner = ScriptedInner([[_option("G1")], [_option("G1"), _option("G9")]])
    service = CachedTrainService(
        session_factory=session_factory, inner=inner, ttl_hours=24.0, clock=clock
    )
    first = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in first] == ["G1"]

    clock.now = BASE_NOW + timedelta(hours=25)  # 过 TTL -> 重拉
    second = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in second] == ["G1", "G9"]  # 读取只取最新批次
    assert inner.calls == 2
    # 留史只追加：旧批次行保留在库，不被改写/删除。
    assert _row_count(session_factory) == 3


def test_empty_result_not_cached(session_factory):
    inner = ScriptedInner([[], [_option("G1")]])
    service = CachedTrainService(session_factory=session_factory, inner=inner)

    assert asyncio.run(service.search("北京", "上海", DATE)) == []
    assert _row_count(session_factory) == 0  # 空批次不落库

    again = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in again] == ["G1"]  # 下次仍会打 inner
    assert inner.calls == 2


def test_inner_error_falls_back_to_stale_batch(session_factory):
    clock = _Clock()
    inner = ScriptedInner([[_option("G1")], RuntimeError("源全挂")])
    service = CachedTrainService(
        session_factory=session_factory, inner=inner, clock=clock
    )
    assert asyncio.run(service.search("北京", "上海", DATE))[0].train_no == "G1"

    clock.now = BASE_NOW + timedelta(hours=25)  # 过期 + inner 抛错
    fallback = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in fallback] == ["G1"]  # 过期旧批也好过没班次
    assert inner.calls == 2


def test_inner_error_with_empty_cache_reraises(session_factory):
    inner = ScriptedInner([RuntimeError("boom")])
    service = CachedTrainService(session_factory=session_factory, inner=inner)
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(service.search("北京", "上海", DATE))


def test_same_city_short_circuits_without_io(session_factory):
    inner = ScriptedInner([[_option("G1")]])
    service = CachedTrainService(session_factory=session_factory, inner=inner)
    assert asyncio.run(service.search("北京", "北京", DATE)) == []
    assert inner.calls == 0  # 零网络
    assert _row_count(session_factory) == 0  # 零 DB 写


def test_resolve_query_date_blank_defaults_to_today_plus3():
    assert _resolve_query_date(DATE) == DATE
    assert _resolve_query_date(f"  {DATE} ") == DATE
    expected = (date_cls.today() + timedelta(days=3)).isoformat()
    assert _resolve_query_date("") == expected


def test_refresh_default_pairs_mock_inner_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/refresh.db")
    Base.metadata.create_all(engine, tables=[TrainScheduleRecord.__table__])
    monkeypatch.setattr(train_cache_module, "_train_cache_engine", engine)
    try:
        settings = Settings()  # conftest: TRAIN_REMOTE_ENABLED=false -> mock inner
        first = refresh_train_cache(settings)
        assert first["errors"] == {}
        assert first["refreshed"] == 8  # mock 核心 8 对（空库默认范围）
        assert first["rows_written"] == 24  # 8 对 x 3 班
        assert len(first["pairs"]) == 8
        factory = sessionmaker(bind=engine)
        assert _row_count(factory) == 24

        second = refresh_train_cache(settings)  # TTL 内 -> 幂等
        assert second["errors"] == {}
        assert second["rows_written"] == 24  # 读回同批，行数不变
        assert _row_count(factory) == 24  # 无重复行
    finally:
        engine.dispose()


class _OkSource:
    name = "ok"

    async def fetch(self, from_city, to_city, date):
        return [_option("G7")]


def test_remote_chain_last_source_marks_fallback_as_mock():
    service = RemoteTrainService(
        MockTrainService(), sources=[CtripTrainSource(), MeituanTrainSource()]
    )
    assert service.last_source is None  # 未搜索前不设
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert options  # 占位源全抛 -> mock 兜底非空
    assert service.last_source == "mock"


def test_remote_chain_last_source_marks_hitting_source():
    service = RemoteTrainService(
        MockTrainService(), sources=[CtripTrainSource(), _OkSource()]
    )
    options = asyncio.run(service.search("北京", "上海", DATE))
    assert [o.train_no for o in options] == ["G7"]
    assert service.last_source == "ok"
