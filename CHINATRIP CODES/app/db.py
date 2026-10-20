from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def _engine_and_factory() -> tuple[object, sessionmaker[Session]]:
    url = get_settings().database_url
    # connect_timeout: DB 不在（如未起 docker db）时 3s 内失败走降级，
    # 否则 psycopg 会无限等待，卡死调用方（2026-10-19 服务器僵死事故）。
    connect_args = {"connect_timeout": 3} if url.startswith("postgresql") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
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
