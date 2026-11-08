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
