"""车道指标端点（design §6.12 ④ / §7 双车道指标）。

GET /api/v1/metrics/lanes — 闸门统计（分类来源/快车道占比/意图缓存命中）
+ 服务车道指标（lane 计数、off-main 占比、fast TTFT p95、slow 受理 p95、
目标与达标布尔）。口径与 targets 见 app/services/lane_metrics.py。
"""

from fastapi import APIRouter, Depends

from app.api.plan import get_request_gate
from app.services.gate import RequestGate
from app.services.lane_metrics import get_lane_metrics

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/metrics/lanes")
async def lane_metrics(gate: RequestGate = Depends(get_request_gate)) -> dict:
    return {"gate": gate.stats(), "lanes": get_lane_metrics().aggregates()}
