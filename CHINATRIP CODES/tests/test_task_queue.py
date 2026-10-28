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
