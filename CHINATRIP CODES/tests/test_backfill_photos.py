"""Tests for app.jobs.backfill_photos (批量预热，只填空 + 冷却戳 + 熔断)."""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace

from app.services.amap_client import AmapQuotaExhaustedError


def make_row(**over) -> SimpleNamespace:
    base = dict(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        photos=None,
        photos_source=None,
        photos_fetched_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeSession:
    def __init__(self, row):
        self._row = row
        self.commits = 0

    def get(self, model, key):
        return self._row if self._row and self._row.id == key else None

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stats() -> dict:
    return {
        "targets": 0,
        "hits": 0,
        "no_data": 0,
        "errors": 0,
        "filled": {},
        "stop": None,
    }


# --- _write_row：只填空 + 尝试即落戳 -------------------------------------------


def test_write_row_fills_empty_photos_and_stamps_cooldown():
    from app.jobs.backfill_photos import _write_row

    row = make_row()
    session = FakeSession(row)
    photos = [{"title": "", "url": "https://img.example/x.jpg"}]
    written = _write_row(lambda: session, row.id, photos, "amap")
    assert written == ["photos", "photos_source"]
    assert row.photos == photos
    assert row.photos_source == "amap"
    assert isinstance(row.photos_fetched_at, datetime)
    assert session.commits == 1


def test_write_row_never_overwrites_existing_photos():
    from app.jobs.backfill_photos import _write_row

    existing = [{"title": "旧图", "url": "https://img.example/old.jpg"}]
    row = make_row(photos=existing, photos_source="wikimedia")
    session = FakeSession(row)
    new_photos = [{"title": "", "url": "https://img.example/new.jpg"}]
    written = _write_row(lambda: session, row.id, new_photos, "amap")
    assert written == []
    assert row.photos is existing  # 只填空铁律：不覆盖
    assert row.photos_source == "wikimedia"
    assert isinstance(row.photos_fetched_at, datetime)  # 戳照落


def test_write_row_empty_result_stamps_cooldown_fills_nothing():
    from app.jobs.backfill_photos import _write_row

    row = make_row()
    session = FakeSession(row)
    written = _write_row(lambda: session, row.id, None, None)
    assert written == []
    assert row.photos is None
    assert row.photos_source is None
    assert isinstance(row.photos_fetched_at, datetime)


# --- _process_row：拉空落戳 / 配额熔断 -----------------------------------------


def _run_process(monkeypatch, *, chain_result=None, chain_exc=None):
    import app.jobs.backfill_photos as job

    async def fake_chain(row, *, amap):
        if chain_exc is not None:
            raise chain_exc
        return chain_result

    monkeypatch.setattr(job, "fetch_photo_chain", fake_chain)
    row = make_row()
    session = FakeSession(row)
    stats = _stats()
    t = job._Target(row.id, "洪崖洞", "重庆市", "amap", "B001")
    asyncio.run(job._process_row(None, lambda: session, t, asyncio.Semaphore(1), stats))
    return stats, session, row


def test_process_row_no_data_stamps_cooldown(monkeypatch):
    stats, session, row = _run_process(monkeypatch, chain_result=(None, None))
    assert stats["no_data"] == 1
    assert stats["hits"] == 0
    assert isinstance(row.photos_fetched_at, datetime)
    assert row.photos is None


def test_process_row_quota_exhaustion_stops_run(monkeypatch):
    stats, session, row = _run_process(
        monkeypatch, chain_exc=AmapQuotaExhaustedError("quota")
    )
    assert stats["stop"] == "quota_exhausted_stop"
    assert stats["hits"] == 0
    assert row.photos_fetched_at is None  # 未落戳：熔断行不占冷却，明日续跑


def test_process_row_generic_error_counts_and_skips(monkeypatch):
    stats, _, row = _run_process(monkeypatch, chain_exc=RuntimeError("network down"))
    assert stats["errors"] == 1
    assert stats["hits"] == 0
    assert row.photos_fetched_at is None
