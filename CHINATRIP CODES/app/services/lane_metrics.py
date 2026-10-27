"""车道 + TTFT 指标（design §6.12 ④ / §7 双车道指标）。

进程内计数 + 每车道有界样本窗（无持久化——指标是运维遥测不是业务数据，
每请求一行的 usage log 才是持久记录）。

口径（与 DESIGN/fast_slow_lane_PROGRESS.md 同步）：
- fast TTFT    = 快车道从收到请求到答案返回的全程（答案短，全程≈首字）
- slow accept  = 慢车道从收到请求到「已受理」返回（铁律 8 预算内 <3s）
- main latency = 主车道整轮 agent.message 总时长（非流式，近似口径——
  真流式 TTFT 要等 v0 生成流式化，§6.12 ④ 的已登记悬案）
- off_main_share = (fast + slow) / total：请求路径上不阻塞主力模型的比例
  （目标 ≥80%；slow 的重活异步跑，不计入「同步触达」）
"""

from __future__ import annotations

import math
from collections import deque

FAST_TTFT_TARGET_MS = 1_000.0
SLOW_ACCEPT_TARGET_MS = 3_000.0
OFF_MAIN_SHARE_TARGET = 0.8

_LANES = ("fast", "slow", "main")


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]


class LaneMetrics:
    """record() 每请求一次；aggregates() 供指标端点。线程安全免锁：
    FastAPI 单事件循环内写，读端点也在同循环（与 gate 缓存同哲学）。"""

    def __init__(self, *, max_samples: int = 5_000) -> None:
        self._max_samples = max_samples
        self._counts: dict[str, int] = {lane: 0 for lane in _LANES}
        self._ttfts: dict[str, deque[float]] = {
            lane: deque(maxlen=max_samples) for lane in _LANES
        }
        self._intents: dict[str, int] = {}

    def record(
        self, lane: str, *, ttft_ms: float, intent: str = "", source: str = ""
    ) -> None:
        if lane not in self._counts:
            return
        self._counts[lane] += 1
        self._ttfts[lane].append(max(0.0, float(ttft_ms)))
        if intent:
            self._intents[intent] = self._intents.get(intent, 0) + 1

    def aggregates(self) -> dict:
        total = sum(self._counts.values())
        fast = self._counts["fast"]
        slow = self._counts["slow"]
        off_main = (fast + slow) / total if total else 0.0
        fast_p95 = _p95(list(self._ttfts["fast"]))
        slow_p95 = _p95(list(self._ttfts["slow"]))
        main_p95 = _p95(list(self._ttfts["main"]))
        return {
            "total": total,
            "lane_counts": dict(self._counts),
            "fast_share": fast / total if total else 0.0,
            "off_main_share": off_main,
            "intents": dict(self._intents),
            "p95_ms": {
                "fast_ttft": fast_p95,
                "slow_accept": slow_p95,
                "main_latency": main_p95,
            },
            "targets": {
                "off_main_share": OFF_MAIN_SHARE_TARGET,
                "fast_ttft_ms": FAST_TTFT_TARGET_MS,
                "slow_accept_ms": SLOW_ACCEPT_TARGET_MS,
            },
            "met": {
                "off_main_share": total > 0 and off_main >= OFF_MAIN_SHARE_TARGET,
                "fast_ttft_ms": fast_p95 is not None
                and fast_p95 <= FAST_TTFT_TARGET_MS,
                "slow_accept_ms": slow_p95 is not None
                and slow_p95 <= SLOW_ACCEPT_TARGET_MS,
            },
            "window_samples": self._max_samples,
        }

    def reset(self) -> None:
        """测试与运维复位。"""
        self._counts = {lane: 0 for lane in _LANES}
        self._ttfts = {lane: deque(maxlen=self._max_samples) for lane in _LANES}
        self._intents = {}


_metrics_singleton: LaneMetrics | None = None


def get_lane_metrics() -> LaneMetrics:
    global _metrics_singleton
    if _metrics_singleton is None:
        _metrics_singleton = LaneMetrics()
    return _metrics_singleton
