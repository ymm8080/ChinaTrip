from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def _engine_and_factory() -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def get_engine():
    engine, _ = _engine_and_factory()
    return engine


def get_db() -> Iterator[Session]:
    _, factory = _engine_and_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
