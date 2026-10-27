"""慢车道异步任务队列（design §6.12 ③：结构性重排/批量解析 → 入队 +
「已受理」<3s + H5 轮询 GET /tasks/{id} 拿结果）。

设计书写 Redis 队列；本仓库 MVP 无 Redis——照 call_store / state_persist
模式落 SQLite（settings.task_db_url，默认 data/tasks.db，测试传
":memory:"），进程内 asyncio worker 轮询消化。取舍：
- 单实例 FastAPI（§2 无状态横扩之前）不引入新中间件；
- 任务状态落库、重启可见：worker 启动 requeue_running() 把上次进程
  崩溃遗留的 running 拉回 queued 继续消化（不丢任务）；
- 将来上 Redis / PG worker：TaskStore 换实现，TaskWorker 协议不变。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 批量解析上限（§6.12 慢车道「批量任务」是有界的，不是无限吞吐承诺）
BULK_EXTRACT_MAX_TEXTS = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS async_tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    device_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    payload TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_async_tasks_owner ON async_tasks(device_id);
CREATE INDEX IF NOT EXISTS idx_async_tasks_status ON async_tasks(status);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TaskRecord(BaseModel):
    task_id: str
    kind: str
    device_id: str
    status: str
    payload: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None


class TaskStore:
    """SQLite 队列状态（单连接 + threading.Lock，call_store 模式）。"""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["id"],
            kind=row["kind"],
            device_id=row["device_id"],
            status=row["status"],
            payload=json.loads(row["payload"] or "{}"),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )

    def enqueue(self, kind: str, payload: dict, *, device_id: str) -> TaskRecord:
        task_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO async_tasks (id, kind, device_id, status, payload,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    kind,
                    device_id,
                    STATUS_QUEUED,
                    json.dumps(payload),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return TaskRecord(
            task_id=task_id,
            kind=kind,
            device_id=device_id,
            status=STATUS_QUEUED,
            payload=payload,
            created_at=now,
            updated_at=now,
        )

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM async_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._to_record(row) if row is not None else None

    def list_for_device(self, device_id: str, *, limit: int = 20) -> list[TaskRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM async_tasks WHERE device_id = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (device_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def claim_next(self) -> TaskRecord | None:
        """最旧的 queued → running（原子 UPDATE，为多 worker 留余地）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM async_tasks WHERE status = ?"
                " ORDER BY created_at, rowid LIMIT 1",
                (STATUS_QUEUED,),
            ).fetchone()
            if row is None:
                return None
            cur = self._conn.execute(
                "UPDATE async_tasks SET status = ?, updated_at = ?"
                " WHERE id = ? AND status = ?",
                (STATUS_RUNNING, _now(), row["id"], STATUS_QUEUED),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
            taken = self._conn.execute(
                "SELECT * FROM async_tasks WHERE id = ?", (row["id"],)
            ).fetchone()
        return self._to_record(taken) if taken is not None else None

    def finish(self, task_id: str, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE async_tasks SET status = ?, result = ?, updated_at = ?,"
                " finished_at = ? WHERE id = ?",
                (
                    STATUS_DONE,
                    json.dumps(result, ensure_ascii=False),
                    _now(),
                    _now(),
                    task_id,
                ),
            )
            self._conn.commit()

    def fail(self, task_id: str, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE async_tasks SET status = ?, error = ?, updated_at = ?,"
                " finished_at = ? WHERE id = ?",
                (STATUS_FAILED, error[:500], _now(), _now(), task_id),
            )
            self._conn.commit()

    def requeue_running(self) -> int:
        """进程启动时的崩溃恢复：上次遗留 running 拉回 queued。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE async_tasks SET status = ?, updated_at = ? WHERE status = ?",
                (STATUS_QUEUED, _now(), STATUS_RUNNING),
            )
            self._conn.commit()
        return cur.rowcount


TaskHandler = Callable[[dict, TaskRecord], Awaitable[dict]]


class TaskWorker:
    """进程内 asyncio worker：claim 一条跑一条，空转 sleep。"""

    def __init__(self, store: TaskStore, *, poll_seconds: float = 0.5) -> None:
        self._store = store
        self._poll_seconds = poll_seconds
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, kind: str, handler: TaskHandler) -> None:
        self._handlers[kind] = handler

    @property
    def kinds(self) -> list[str]:
        return sorted(self._handlers)

    async def tick(self) -> bool:
        """处理至多一条任务；返回是否干了活（供测试与 run_forever）。"""
        task = self._store.claim_next()
        if task is None:
            return False
        handler = self._handlers.get(task.kind)
        try:
            if handler is None:
                raise ValueError(f"unsupported_kind:{task.kind}")
            result = await handler(task.payload, task)
        except Exception as exc:  # noqa: BLE001 — 单任务失败不拖垮 worker
            logger.warning(
                "slow-lane task %s (%s) failed: %s", task.task_id, task.kind, exc
            )
            self._store.fail(task.task_id, str(exc) or type(exc).__name__)
        else:
            self._store.finish(task.task_id, result or {})
            logger.info("slow-lane task %s (%s) done", task.task_id, task.kind)
        return True

    async def run_forever(self) -> None:
        self._store.requeue_running()
        while True:
            if not await self.tick():
                await asyncio.sleep(self._poll_seconds)


async def _bulk_extract_handler(payload: dict, _task: TaskRecord) -> dict:
    """批量文本/链接解析（§6.12 慢车道示例任务）：逐条走既有
    ExtractionService，聚合 POI 候选。"""
    from app.config import get_settings
    from app.services.extraction import ExtractionService
    from app.services.llm import get_llm_adapter

    texts = [
        t for t in (payload.get("texts") or []) if isinstance(t, str) and t.strip()
    ][:BULK_EXTRACT_MAX_TEXTS]
    if not texts:
        raise ValueError("no_texts")
    lang = payload.get("lang") or "zh"
    service = ExtractionService(get_llm_adapter(get_settings()))
    items: list[dict] = []
    for text in texts:
        result = await service.run(text, lang=lang)
        items.extend(
            {
                "name": cand.name,
                "city": cand.city,
                "category": cand.category,
                "confidence": cand.confidence,
            }
            for cand in result.candidates
        )
    return {"count": len(items), "items": items}


async def _replan_handler(payload: dict, _task: TaskRecord) -> dict:
    """结构性重排：后台跑完整 agent.message 管线并落库；H5 轮询任务
    结果拿 reply/change。懒加载——task_queue 被 app.api.plan 导入，
    反向 import 只能在函数体内。"""
    from app.api.plan import get_plan_sessions, get_planning_agent
    from app.services.agent.plan import current_violations

    session_id = payload.get("session_id") or ""
    device_id = payload.get("device_id") or ""
    text = payload.get("text") or ""
    if not (session_id and device_id and text):
        raise ValueError("missing_payload_fields")
    sessions = get_plan_sessions()
    session = sessions.get(session_id, device_id=device_id)
    if session is None:
        raise ValueError("session_not_found")
    agent = get_planning_agent()
    session, reply, change = await agent.message(session, text)
    sessions.save(session)
    change_payload = (
        change.model_dump() if hasattr(change, "model_dump") else (change or None)
    )
    # H5 轮询完成后用 planRenderSafe 渲染——字段与 /message 响应同构。
    # worker 落库走 json.dumps，pydantic 模型须显式 model_dump。
    result: dict = {"reply": reply, "change": change_payload, "state": session.state}
    if session.plan is not None:
        result["plan"] = session.plan.model_dump()
        result["violations"] = [v.model_dump() for v in current_violations(session)]
    return result


def register_default_handlers(worker: TaskWorker) -> None:
    worker.register("bulk_extract", _bulk_extract_handler)
    worker.register("replan", _replan_handler)


_store_singleton: TaskStore | None = None
_worker_singleton: TaskWorker | None = None


def get_task_store() -> TaskStore:
    global _store_singleton
    if _store_singleton is None:
        from app.config import get_settings
        from app.services.state_persist import db_path_from_url

        _store_singleton = TaskStore(db_path_from_url(get_settings().task_db_url))
    return _store_singleton


def get_task_worker() -> TaskWorker:
    global _worker_singleton
    if _worker_singleton is None:
        from app.config import get_settings

        settings = get_settings()
        _worker_singleton = TaskWorker(
            get_task_store(), poll_seconds=settings.task_worker_poll_seconds
        )
        register_default_handlers(_worker_singleton)
    return _worker_singleton
