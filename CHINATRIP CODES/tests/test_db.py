"""Engine connect_args 单测（app/db.py）。

connect_timeout / statement_timeout 是防「同步 PG 调用冻死事件循环」的
保险丝——半开连接挂查询 15+ 分钟的事故（2026-11-11）后落档，此处锁常量。
"""

from app.db import _connect_args


def test_pg_url_gets_both_fuses():
    args = _connect_args("postgresql+psycopg://u:p@localhost:5432/db")
    assert args["connect_timeout"] == 3
    assert "statement_timeout" in args["options"]


def test_non_pg_url_gets_no_args():
    assert _connect_args("sqlite:///data/x.db") == {}


def test_get_session_factory_builds_for_sqlite():
    from app.db import get_session_factory

    factory = get_session_factory()
    session = factory()
    try:
        assert session.bind is not None
    finally:
        session.close()
