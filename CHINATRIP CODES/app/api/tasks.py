"""慢车道任务 API（design §6.12 ③）。

POST /api/v1/tasks        — 入队即回 202（「已受理」<3s 口径 = 本端点耗时）
GET  /api/v1/tasks/{id}   — H5 轮询任务状态；done 带 result，failed 带 error
GET  /api/v1/tasks        — 本设备任务列表（通知入口的兜底形态）

replan 任务常规入口是 POST /plan/{sid}/message 的慢车道分流；本端点是
通用入队口（bulk_extract 等）与 H5 恢复轮询的锚点。跨归属任务 404 防枚举
（itineraries 同款）。
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.task_queue import (
    TaskStore,
    TaskWorker,
    get_task_store,
    get_task_worker,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])
logger = logging.getLogger(__name__)


class TaskCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)


@router.post("/tasks", status_code=202)
async def create_task(
    request: TaskCreateRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    worker: TaskWorker = Depends(get_task_worker),
    store: TaskStore = Depends(get_task_store),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    if request.kind not in worker.kinds:
        raise HTTPException(status_code=422, detail="unknown_task_kind")
    task = store.enqueue(request.kind, request.payload, device_id=x_device_id)
    logger.info("slow-lane task %s (%s) queued", task.task_id, task.kind)
    return {"task_id": task.task_id, "kind": task.kind, "status": task.status}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: TaskStore = Depends(get_task_store),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    task = store.get(task_id)
    if task is None or task.device_id != x_device_id:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task.model_dump()


@router.get("/tasks")
async def list_tasks(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    limit: int = 20,
    store: TaskStore = Depends(get_task_store),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    tasks = store.list_for_device(x_device_id, limit=limit)
    return {"tasks": [t.model_dump() for t in tasks]}
