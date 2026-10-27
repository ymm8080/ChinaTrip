import os

import pytest
from fastapi.testclient import TestClient

# 火车远程源（12306 等）默认关闭：现有测试断言的是确定性 mock 班次，
# 离线跑必须全绿；RemoteTrainService 的行为由 tests/test_trains.py 用
# httpx.MockTransport 离线覆盖。
os.environ.setdefault("TRAIN_REMOTE_ENABLED", "false")

from app.main import create_app  # noqa: E402

# handoff PG 写穿钩子在测试进程默认关闭：单测不得写真库账本
# （写穿行为由 tests/test_backfill.py 用注入钩子/假 session 直接覆盖）。
from app.api.backfill import get_handoff_store  # noqa: E402

get_handoff_store().attach_persistence(lambda record: None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())
