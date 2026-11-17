from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _connect_args(url: str) -> dict:
    if not url.startswith("postgresql"):
        return {}
    # connect_timeout: DB 不在（如未起 docker db）时 3s 内失败走降级，
    # 否则 psycopg 会无限等待，卡死调用方（2026-10-19 服务器僵死事故）。
    # statement_timeout: connect_timeout 只管建连——连接半开（WSL PG
    # 空闲闪断/残留端口霸住 5432）时查询照样挂死，同步调用会把整个
    # asyncio 事件循环冻住、慢车道任务永远 running（2026-11-11 实测
    # 冻 15+ 分钟）。给每条语句封顶，让上层熔断按设计秒级触发。
    return {"connect_timeout": 3, "options": "-c statement_timeout=30000"}


@lru_cache
def _engine_and_factory() -> tuple[object, sessionmaker[Session]]:
    url = get_settings().database_url
    engine = create_engine(url, pool_pre_ping=True, connect_args=_connect_args(url))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def get_engine():
    engine, _ = _engine_and_factory()
    return engine


def get_session_factory() -> sessionmaker[Session]:
    _, factory = _engine_and_factory()
    return factory


def get_db() -> Iterator[Session]:
    _, factory = _engine_and_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
