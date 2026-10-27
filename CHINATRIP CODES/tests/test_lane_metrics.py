"""Tests for lane + TTFT metrics (design §6.12 ④ / §7)."""

from app.services.lane_metrics import (
    FAST_TTFT_TARGET_MS,
    SLOW_ACCEPT_TARGET_MS,
    LaneMetrics,
    _p95,
)


def test_p95_empty_and_single():
    assert _p95([]) is None
    assert _p95([42.0]) == 42.0


def test_p95_nearest_rank():
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert _p95(values) == 95.0


def test_record_counts_lanes_and_intents():
    metrics = LaneMetrics()
    metrics.record("fast", ttft_ms=120.0, intent="poi_hours", source="rule")
    metrics.record("fast", ttft_ms=200.0, intent="translate", source="rule")
    metrics.record("slow", ttft_ms=400.0, intent="replan", source="rule")
    metrics.record("main", ttft_ms=9000.0, intent="chat", source="flash")
    agg = metrics.aggregates()
    assert agg["total"] == 4
    assert agg["lane_counts"] == {"fast": 2, "slow": 1, "main": 1}
    assert agg["fast_share"] == 0.5
    assert agg["off_main_share"] == 0.75
    assert agg["intents"]["poi_hours"] == 1
    assert agg["p95_ms"]["fast_ttft"] == 200.0
    assert agg["p95_ms"]["main_latency"] == 9000.0


def test_targets_and_met_flags():
    metrics = LaneMetrics()
    # 全部快车道、TTFT 很小 → off-main 与 fast 口径达标，slow 无样本不达标
    for _ in range(10):
        metrics.record("fast", ttft_ms=50.0, intent="t")
    agg = metrics.aggregates()
    assert agg["targets"] == {
        "off_main_share": 0.8,
        "fast_ttft_ms": FAST_TTFT_TARGET_MS,
        "slow_accept_ms": SLOW_ACCEPT_TARGET_MS,
    }
    assert agg["met"]["off_main_share"] is True
    assert agg["met"]["fast_ttft_ms"] is True
    assert agg["met"]["slow_accept_ms"] is False  # 无样本 ≠ 达标


def test_unknown_lane_ignored():
    metrics = LaneMetrics()
    metrics.record("sideways", ttft_ms=1.0)
    assert metrics.aggregates()["total"] == 0


def test_reset_clears_everything():
    metrics = LaneMetrics()
    metrics.record("fast", ttft_ms=1.0, intent="x")
    metrics.reset()
    agg = metrics.aggregates()
    assert agg["total"] == 0
    assert agg["intents"] == {}
    assert agg["p95_ms"]["fast_ttft"] is None


def test_sample_window_bounded():
    metrics = LaneMetrics(max_samples=3)
    for i in range(10):
        metrics.record("fast", ttft_ms=float(i))
    agg = metrics.aggregates()
    assert agg["total"] == 10  # 计数不丢
    assert agg["p95_ms"]["fast_ttft"] == 9.0  # 样本窗只留最新 3 条
