import os

import pytest
from fastapi.testclient import TestClient

# 火车远程源（12306 等）默认关闭：现有测试断言的是确定性 mock 班次，
# 离线跑必须全绿；RemoteTrainService 的行为由 tests/test_trains.py 用
# httpx.MockTransport 离线覆盖。
os.environ.setdefault("TRAIN_REMOTE_ENABLED", "false")

# handoff PG 写穿钩子在测试进程默认关闭：单测不得写真库账本
# （写穿行为由 tests/test_backfill.py 用注入钩子/假 session 直接覆盖）。
from app.api.backfill import get_handoff_store  # noqa: E402
from app.main import create_app  # noqa: E402

get_handoff_store().attach_persistence(lambda record: None)


# 2026-11-08 屏蔽期（先屏蔽不删）：偏好问答轮默认下线
# （app/services/agent/plan.py::_PREF_ROUND_ENABLED=False，待补充信息后
# 解封）。大量用例以偏好轮为状态脚手架（start → clarify → ready），
# 这里 autouse 全局临时开闸按历史口径跑；屏蔽期默认行为由
# tests/test_plan_agent.py::test_pref_round_blocked_by_default 在用例内
# 单独翻回默认验收。解封后本 fixture 与该开关用例都是无害冗余，可一并撤掉。
@pytest.fixture(autouse=True)
def _pref_round_enabled_for_tests(monkeypatch):
    import app.services.agent.plan as _plan_mod

    monkeypatch.setattr(_plan_mod, "_PREF_ROUND_ENABLED", True)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


# 2026-11-26 R53：plan 的车道单例是进程级的，第一次谁构造它就永远用谁的
# adapter/settings。全量跑时若前面的用例先构造了真 Flash adapter（3.3s 网络
# 分类把「把外滩挪到第二天」判成 slow → 延后后台重排），后面明明 override
# 成 mock 的用例仍继承这个单例，用例从「编辑落地」漂移成「重排中」，单跑
# 却全绿（test_time_slot_integrity 反复被 triage 判为 load flake）。
# 每个用例重置一次，恢复到「谁用自己的 settings 谁负责」的语义；同一用例
# 内的多次调用仍是同一个单例，生产行为不受影响。
@pytest.fixture(autouse=True)
def _reset_plan_lane_singletons(monkeypatch):
    import app.api.plan as _plan_api

    monkeypatch.setattr(_plan_api, "_gate_singleton", None)
    monkeypatch.setattr(_plan_api, "_fast_lane_singleton", None)


@pytest.fixture(autouse=True)
def _default_engine_legacy_for_tests(monkeypatch):
    """R29（2026-11-24 用户令「ALWAYS USE CP-SAT」）：产品缺省引擎改为 CP-SAT；
    老回归用例多数是按 legacy 服务形状写的断言，这里显式钉 legacy 作测试基线——
    要引擎的用例自己 setenv(TRIP_SOLVER, cpsat)，代码缺省（cpsat）由
    tests/test_trip_solver_entry.py 的 flag 测覆盖。"""
    monkeypatch.setenv("TRIP_SOLVER", "legacy")
