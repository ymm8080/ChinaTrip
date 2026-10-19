# -*- coding: utf-8 -*-
"""SQLite write-through persistence for the two in-process stores.

``PlanSessionStore`` and ``InMemoryItineraryStore`` are plain dicts, so
every uvicorn relaunch (the dev workflow restarts on each code change)
wiped in-flight planning sessions and saved itineraries — surfacing as
``session_not_found`` 404s on follow-up messages and an empty H5 行程
tab. This module keeps the dict as the hot path and adds: load-all on
boot, one-row upsert/delete per mutation. A corrupt row is skipped with
a warning — a poisoned row must never take the service down.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from app.services.agent.plan import PlanSession, PlanSessionStore
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_sessions (
    session_id TEXT PRIMARY KEY,
    payload    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS itineraries (
    itinerary_id TEXT PRIMARY KEY,
    payload      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    token_hash    TEXT UNIQUE,
    created_at    TEXT NOT NULL
);
"""


class SqliteStateBackend:
    """Two-table JSON store; one connection, one lock (server is a
    single event loop, TestClient threads differ -> check_same_thread
    off, lock guards the rare concurrent write)."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def _load(self, table: str, key_col: str) -> dict[str, str]:
        rows = self._conn.execute(
            f"SELECT {key_col}, payload FROM {table}"  # noqa: S608
        ).fetchall()
        return dict(rows)

    def load_sessions(self) -> dict[str, str]:
        return self._load("plan_sessions", "session_id")

    def load_itineraries(self) -> dict[str, str]:
        return self._load("itineraries", "itinerary_id")

    def _upsert(self, table: str, key_col: str, key: str, payload: str) -> None:
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {table} ({key_col}, payload) "  # noqa: S608
                "VALUES (?, ?)",
                (key, payload),
            )
            self._conn.commit()

    def save_session(self, session_id: str, payload: str) -> None:
        self._upsert("plan_sessions", "session_id", session_id, payload)

    def save_itinerary(self, itinerary_id: str, payload: str) -> None:
        self._upsert("itineraries", "itinerary_id", itinerary_id, payload)

    def delete_itinerary(self, itinerary_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM itineraries WHERE itinerary_id = ?", (itinerary_id,)
            )
            self._conn.commit()

    # --- accounts (custom username+password login) ---------------------------

    def save_account(
        self, username: str, password_hash: str, token_hash: str, created_at: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO accounts "
                "(username, password_hash, token_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (username, password_hash, token_hash, created_at),
            )
            self._conn.commit()

    def get_account(self, username: str) -> tuple[str, str | None, str] | None:
        """Row as ``(password_hash, token_hash, created_at)`` or None."""
        row = self._conn.execute(
            "SELECT password_hash, token_hash, created_at FROM accounts "
            "WHERE username = ?",
            (username,),
        ).fetchone()
        return tuple(row) if row else None

    def get_username_by_token(self, token_hash: str) -> str | None:
        row = self._conn.execute(
            "SELECT username FROM accounts WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return row[0] if row else None

    def update_account_token(self, username: str, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET token_hash = ? WHERE username = ?",
                (token_hash, username),
            )
            self._conn.commit()

    def clear_account_token(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET token_hash = NULL WHERE token_hash = ?",
                (token_hash,),
            )
            self._conn.commit()


class PersistentPlanSessionStore(PlanSessionStore):
    """Sessions survive restarts; boot reload is best-effort."""

    def __init__(self, backend: SqliteStateBackend) -> None:
        super().__init__()
        self._backend = backend
        for session_id, payload in backend.load_sessions().items():
            try:
                self._sessions[session_id] = PlanSession.model_validate_json(payload)
            except Exception:
                logger.warning(
                    "state_persist: dropping corrupt session %s",
                    session_id,
                    exc_info=True,
                )

    def save(self, session: PlanSession) -> None:
        super().save(session)
        self._backend.save_session(session.session_id, session.model_dump_json())


class PersistentItineraryStore(InMemoryItineraryStore):
    """Itinerary records survive restarts; delete is honored on disk."""

    def __init__(self, backend: SqliteStateBackend) -> None:
        super().__init__()
        self._backend = backend
        for itinerary_id, payload in backend.load_itineraries().items():
            try:
                self._records[itinerary_id] = ItineraryRecord.model_validate_json(
                    payload
                )
            except Exception:
                logger.warning(
                    "state_persist: dropping corrupt itinerary %s",
                    itinerary_id,
                    exc_info=True,
                )

    def put(self, record: ItineraryRecord) -> None:
        super().put(record)
        self._backend.save_itinerary(record.itinerary_id, record.model_dump_json())

    def delete(self, itinerary_id: str) -> bool:
        existed = super().delete(itinerary_id)
        if existed:
            self._backend.delete_itinerary(itinerary_id)
        return existed


_backend_singleton: SqliteStateBackend | None = None


def get_state_backend(db_path: str) -> SqliteStateBackend:
    global _backend_singleton
    if _backend_singleton is None:
        _backend_singleton = SqliteStateBackend(db_path)
    return _backend_singleton


def db_path_from_url(url: str) -> str:
    return url.removeprefix("sqlite:///")
