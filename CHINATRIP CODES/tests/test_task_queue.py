"""Tests for the slow-lane task queue (design §6.12 ③).

Offline: in-memory SQLite store, stub handlers, asyncio.run wrapper
(test_gate.py style — repo has no pytest-asyncio).
"""

import asyncio

import pytest

from app.services.task_queue import (
    BULK_EXTRACT_MAX_TEXTS,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TaskStore,
    TaskWorker,
    register_default_handlers,
)


def make_worker(*, handlers: dict | None = None) -> tuple[TaskStore, TaskWorker]:
    store = TaskStore(":memory:")
    worker = TaskWorker(store, poll_seconds=0)
    for kind, handler in (handlers or {}).items():
        worker.register(kind, handler)
    return store, worker


def run(coro):
    return asyncio.run(coro)


# --- store: enqueue / get / claim / finish / fail ---


def test_enqueue_returns_queued_and_get_roundtrips():
    store = TaskStore(":memory:")
    task = store.enqueue("replan", {"session_id": "s1"}, device_id="dev-1")
    assert task.status == STATUS_QUEUED
    assert task.payload == {"session_id": "s1"}
    loaded = store.get(task.task_id)
    assert loaded is not None and loaded.kind == "replan"
    assert loaded.device_id == "dev-1"


def test_get_unknown_returns_none():
    assert TaskStore(":memory:").get("nope") is None


def test_claim_next_moves_queued_to_running_in_fifo_order():
    store = TaskStore(":memory:")
    first = store.enqueue("replan", {}, device_id="d")
    second = store.enqueue("bulk_extract", {}, device_id="d")
    claimed = store.claim_next()
    assert claimed is not None and claimed.task_id == first.task_id
    assert claimed.status == STATUS_RUNNING
    assert store.claim_next().task_id == second.task_id
    assert store.claim_next() is None  # 队列空


def test_finish_and_fail_close_out_task():
    store = TaskStore(":memory:")
    task = store.enqueue("replan", {}, device_id="d")
    store.claim_next()
    store.finish(task.task_id, {"reply": "ok"})
    done = store.get(task.task_id)
    assert done.status == STATUS_DONE
    assert done.result == {"reply": "ok"}
    assert done.finished_at is not None

    failed_task = store.enqueue("replan", {}, device_id="d")
    store.claim_next()
    store.fail(failed_task.task_id, "boom")
    failed = store.get(failed_task.task_id)
    assert failed.status == STATUS_FAILED
    assert failed.error == "boom"


def test_requeue_running_recovers_crash_leftovers():
    store = TaskStore(":memory:")
    task = store.enqueue("replan", {}, device_id="d")
    store.claim_next()
    assert store.get(task.task_id).status == STATUS_RUNNING
    assert store.requeue_running() == 1
    assert store.get(task.task_id).status == STATUS_QUEUED


def test_list_for_device_filters_owner_and_orders_recent_first():
    store = TaskStore(":memory:")
    a = store.enqueue("replan", {}, device_id="dev-a")
    b = store.enqueue("replan", {}, device_id="dev-b")
    c = store.enqueue("bulk_extract", {}, device_id="dev-a")
    listed = store.list_for_device("dev-a")
    assert [t.task_id for t in listed] == [c.task_id, a.task_id]
    assert b.task_id not in {t.task_id for t in listed}


# --- worker: handlers run, exceptions fail the task ---


def test_worker_runs_registered_handler_to_done():
    async def handler(payload, task):
        return {"echo": payload["x"]}

    store, worker = make_worker(handlers={"replan": handler})
    task = store.enqueue("replan", {"x": 1}, device_id="d")
    assert run(worker.tick()) is True
    done = store.get(task.task_id)
    assert done.status == STATUS_DONE and done.result == {"echo": 1}


def test_worker_handler_exception_fails_task_not_loop():
    async def boom(payload, task):
        raise RuntimeError("no good")

    store, worker = make_worker(handlers={"replan": boom})
    ok_task = store.enqueue("replan", {}, device_id="d")
    run(worker.tick())
    assert store.get(ok_task.task_id).status == STATUS_FAILED
    assert store.get(ok_task.task_id).error == "no good"
    # 队列空时 tick 返回 False（worker 不忙转）
    assert run(worker.tick()) is False


def test_worker_unsupported_kind_fails_task():
    store, worker = make_worker()
    task = store.enqueue("mystery", {}, device_id="d")
    run(worker.tick())
    failed = store.get(task.task_id)
    assert failed.status == STATUS_FAILED
    assert "unsupported_kind" in failed.error


def test_run_forever_requeues_crash_leftovers_then_idles():
    async def handler(payload, task):
        return {}

    store, worker = make_worker(handlers={"replan": handler})
    leftover = store.enqueue("replan", {}, device_id="d")
    store.claim_next()  # 模拟上个进程崩在 running

    async def drive():
        runner = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.05)
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass

    run(drive())
    assert store.get(leftover.task_id).status == STATUS_DONE


def test_run_forever_survives_store_level_errors():
    """claim/finish 抛错（sqlite 锁等）不能让 worker 协程静默死亡——
    进程照常服务 HTTP 而队列停摆（2026-11-11 实探测得 queued 滞留）。"""

    class FlakyStore(TaskStore):
        def __init__(self):
            super().__init__(":memory:")
            self.failures_left = 3

        def claim_next(self):
            if self.failures_left > 0:
                self.failures_left -= 1
                raise RuntimeError("database is locked")
            return super().claim_next()

    store = FlakyStore()
    worker = TaskWorker(store, poll_seconds=0)

    async def drive():
        runner = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.05)
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass

    run(drive())
    assert store.failures_left == 0  # 三次存储层异常后循环仍在轮询


def test_watchdog_logs_stack_for_slow_handler(monkeypatch, caplog):
    import logging

    monkeypatch.setattr("app.services.task_queue._WATCHDOG_SECONDS", 0.05)

    async def slow(payload, task):
        await asyncio.sleep(0.3)
        return {"ok": True}

    store, worker = make_worker(handlers={"replan": slow})
    task = store.enqueue("replan", {}, device_id="d")
    with caplog.at_level(logging.WARNING, logger="app.services.task_queue"):
        assert run(worker.tick()) is True
    done = store.get(task.task_id)
    assert done.status == STATUS_DONE and done.result == {"ok": True}
    assert any("still running" in r.getMessage() for r in caplog.records)
    assert any(" in slow" in r.getMessage() for r in caplog.records)


def test_finish_tolerates_non_json_types_in_result(caplog):
    """plan.model_dump() 默认带 time/datetime 实例——finish 落库 json.dumps
    抛 TypeError 曾让任务永远卡在 running 并静默杀死 worker（2026-11-11
    「插入命令受理后无变化」根因）。现按 str 强制序列化并留痕。"""

    import logging
    from datetime import time

    store = TaskStore(":memory:")
    task = store.enqueue("replan", {}, device_id="d")
    store.claim_next()
    with caplog.at_level(logging.WARNING, logger="app.services.task_queue"):
        store.finish(task.task_id, {"at": time(12, 39)})
    done = store.get(task.task_id)
    assert done.status == STATUS_DONE
    assert done.result == {"at": "12:39:00"}
    assert any("非 JSON 类型" in r.getMessage() for r in caplog.records)


# --- default handlers ---


def test_bulk_extract_handler_caps_texts_and_aggregates(monkeypatch):
    # 离线铁律：.env 可能带 LLM_BACKEND=zhipu——强制 mock 适配器，
    # handler 内部 get_llm_adapter 在此替换为零网络实现。
    from app.services.llm import mock as llm_mock
    from app.services.task_queue import _bulk_extract_handler

    monkeypatch.setattr(
        "app.services.llm.get_llm_adapter", lambda settings: llm_mock.MockLLMAdapter()
    )
    texts = [f"- 景点{i}" for i in range(BULK_EXTRACT_MAX_TEXTS + 3)]
    result = run(_bulk_extract_handler({"texts": texts, "lang": "zh"}, None))
    assert result["count"] == BULK_EXTRACT_MAX_TEXTS
    assert result["items"][0]["name"] == "景点0"
    assert result["items"][0]["confidence"] == 0.9  # mock adapter 行规则


def test_bulk_extract_handler_rejects_empty():
    from app.services.task_queue import _bulk_extract_handler

    with pytest.raises(ValueError):
        run(_bulk_extract_handler({"texts": []}, None))


def test_register_default_handlers_registers_both_kinds():
    store = TaskStore(":memory:")
    worker = TaskWorker(store)
    register_default_handlers(worker)
    assert worker.kinds == ["bulk_extract", "replan"]


# --- R20③ replan baseline race (乐观锁：排队期窗口 A + 执行期窗口 B) ---


def _replan_fixture(monkeypatch, *, drift_on_call: int | None = None):
    """内存会话 store + 可控漂移的假 agent。drift_on_call=N 表示第 N 次
    agent.message 内部模拟「用户在异步窗口拖卡」：主车道 store.save 推进
    rev 并写入用户手排痕迹。返回 (sessions, agent, task, baseline)。"""
    from app.services.task_queue import TaskRecord
    from app.services.trip_orchestrator.session import PlanSession, PlanSessionStore

    sessions = PlanSessionStore()
    sess = PlanSession(session_id="s1", device_id="d")
    sessions.save(sess)  # rev: 0 -> 1
    baseline = sess.rev

    class FakeAgent:
        def __init__(self):
            self.calls = 0

        async def message(self, session, text):
            self.calls += 1
            out = session.model_copy(deep=True)
            if drift_on_call is not None and self.calls == drift_on_call:
                live = sessions.get("s1", device_id="d")
                live.preferences = "user hand-edit"
                sessions.save(live)
            return out, "reply", None

        async def refresh_legs(self, session):
            pass

    agent = FakeAgent()
    task = TaskRecord(
        task_id="t1",
        kind="replan",
        device_id="d",
        status="running",
        created_at="",
        updated_at="",
    )
    monkeypatch.setattr("app.api.plan.get_plan_sessions", lambda: sessions)
    monkeypatch.setattr("app.api.plan.get_planning_agent", lambda: agent)
    return sessions, agent, task, baseline


def test_replan_no_drift_saves_normally(monkeypatch):
    from app.services.task_queue import _replan_handler

    sessions, agent, task, baseline = _replan_fixture(monkeypatch)
    result = run(
        _replan_handler(
            {
                "session_id": "s1",
                "device_id": "d",
                "text": "重排",
                "baseline_rev": baseline,
            },
            task,
        )
    )
    assert result["reply"] == "reply"
    assert agent.calls == 1
    assert sessions.get("s1", device_id="d").rev == baseline + 1


def test_replan_baseline_drift_during_execution_reruns_on_latest(monkeypatch):
    """窗口 B：agent.message 异步期间用户拖卡 → 丢弃过期快照，按最新基线
    重跑，用户手排痕迹必须保留在落盘结果里（07:23 vs 06:30 漂移根因）。"""
    from app.services.task_queue import _replan_handler

    sessions, agent, task, baseline = _replan_fixture(monkeypatch, drift_on_call=1)
    result = run(
        _replan_handler(
            {
                "session_id": "s1",
                "device_id": "d",
                "text": "重排",
                "baseline_rev": baseline,
            },
            task,
        )
    )
    assert result["reply"] == "reply"
    assert agent.calls == 2  # 第一次结果被丢弃，重跑一次
    saved = sessions.get("s1", device_id="d")
    assert saved.preferences == "user hand-edit"  # 用户手排未被后台盖掉
    assert saved.rev == baseline + 2  # 用户拖卡 +1，重跑落盘 +1


def test_replan_baseline_drift_before_start_reruns_without_burning_quota(monkeypatch):
    """窗口 A：排队期用户已操作 → 就地对齐最新基线，仍只跑一次 agent。"""
    from app.services.task_queue import _replan_handler

    sessions, agent, task, baseline = _replan_fixture(monkeypatch)
    # 排队期间用户在主车道改了盘面
    live = sessions.get("s1", device_id="d")
    live.preferences = "user queued edit"
    sessions.save(live)
    queued_rev = live.rev

    result = run(
        _replan_handler(
            {
                "session_id": "s1",
                "device_id": "d",
                "text": "重排",
                "baseline_rev": baseline,
            },
            task,
        )
    )
    assert result["reply"] == "reply"
    assert agent.calls == 1  # 窗口 A 对齐不消耗重跑额度
    saved = sessions.get("s1", device_id="d")
    assert saved.preferences == "user queued edit"
    assert saved.rev == queued_rev + 1


def test_replan_baseline_legacy_payload_skips_checks(monkeypatch):
    """无 baseline_rev 的旧 payload 跳过校验，保持向后兼容。"""
    from app.services.task_queue import _replan_handler

    sessions, agent, task, _ = _replan_fixture(monkeypatch, drift_on_call=1)
    result = run(
        _replan_handler(
            {"session_id": "s1", "device_id": "d", "text": "重排"},
            task,
        )
    )
    assert result["reply"] == "reply"
    assert agent.calls == 1  # 无基线 → 不重跑
    assert sessions.get("s1", device_id="d").preferences == ""  # 旧行为：覆盖


def test_replan_rebase_exhausted_when_session_keeps_changing(monkeypatch):
    """用户持续拖卡导致每次落盘前都漂移 → 重跑次数封顶，明确 fail，
    不无限重投（防任务风暴）。"""
    from app.services.task_queue import TaskRecord, _replan_handler
    from app.services.trip_orchestrator.session import PlanSession, PlanSessionStore

    sessions = PlanSessionStore()
    sess = PlanSession(session_id="s1", device_id="d")
    sessions.save(sess)

    class AlwaysDriftAgent:
        def __init__(self):
            self.calls = 0

        async def message(self, session, text):
            self.calls += 1
            out = session.model_copy(deep=True)
            live = sessions.get("s1", device_id="d")
            live.preferences = f"drag-{self.calls}"
            sessions.save(live)
            return out, "reply", None

        async def refresh_legs(self, session):
            pass

    agent = AlwaysDriftAgent()
    task = TaskRecord(
        task_id="t1",
        kind="replan",
        device_id="d",
        status="running",
        created_at="",
        updated_at="",
    )
    monkeypatch.setattr("app.api.plan.get_plan_sessions", lambda: sessions)
    monkeypatch.setattr("app.api.plan.get_planning_agent", lambda: agent)

    with pytest.raises(ValueError, match="replan_rebase_exhausted"):
        run(
            _replan_handler(
                {
                    "session_id": "s1",
                    "device_id": "d",
                    "text": "重排",
                    "baseline_rev": sess.rev,
                },
                task,
            )
        )
    assert agent.calls == 4  # _REPLAN_MAX_REBASE(3) + 1 次尝试
