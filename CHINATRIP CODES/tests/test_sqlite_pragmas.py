# -*- coding: utf-8 -*-
"""共享 sqlite 库文件的连接 pragma 契约（2026-11-17 并发排查）。

8000/8443 双进程共享同一批库文件（h5_state.db / 任务库 / 旅客库 / 支付库）：
连接必须开 WAL（读写不互斥、跨进程写不等文件锁）+ busy_timeout（撞锁等锁
而非立刻 SQLITE_BUSY）。call_store.py 早有先例，本文件把其余四个补齐并锚死
契约——防止后人删掉 pragma 让双进程写退化回文件锁长等待。
"""

from app.services.payments import PaymentStore
from app.services.state_persist import SqliteStateBackend
from app.services.task_queue import TaskStore
from app.services.travelers import TravelerStore


def _assert_pragmas(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(busy) > 0


def test_state_backend_wal(tmp_path):
    backend = SqliteStateBackend(str(tmp_path / "h5_state.db"))
    _assert_pragmas(backend._conn)


def test_task_store_wal(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    _assert_pragmas(store._conn)


def test_task_store_memory_skips_wal():
    """:memory: 无跨进程锁竞争，journal_mode 守卫跳过（照 call_store 先例）。"""
    store = TaskStore(":memory:")
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "memory"


def test_traveler_store_wal(tmp_path):
    store = TravelerStore(str(tmp_path / "travelers.db"))
    _assert_pragmas(store._conn)


def test_payment_store_wal(tmp_path):
    store = PaymentStore(str(tmp_path / "payments.db"))
    _assert_pragmas(store._conn)
