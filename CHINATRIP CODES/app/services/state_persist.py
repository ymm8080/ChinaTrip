# -*- coding: utf-8 -*-
"""SQLite write-through persistence for the in-process stores.

``PlanSessionStore``, ``InMemoryItineraryStore`` and ``TripItemService``
are plain dicts, so every uvicorn relaunch (the dev workflow restarts on
each code change) wiped in-flight planning sessions, saved itineraries
and the trip-center wishlist - surfacing as ``session_not_found`` 404s
on follow-up messages, an empty H5 行程 tab, and 心愿单 entries
vanishing overnight (2026-10-23: trip_items was the last volatile
store). This module keeps the dict as the hot path and adds: load-all on
boot, one-row upsert/delete per mutation. A corrupt row is skipped with
a warning - a poisoned row must never take the service down.

Accounts (2026-10-19): the ``accounts`` table gained an optional unique
``email`` column plus two email-code tables (``email_codes`` holds the
one pending code per (email, purpose); ``email_code_log`` counts sends
for the hourly cap). Existing databases are migrated in-place via
``ALTER TABLE`` on boot.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

from app.services.agent.plan import PlanSession, PlanSessionStore
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
)
from app.services.trip_items import TripItemService

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
CREATE TABLE IF NOT EXISTS trip_items (
    item_id  TEXT PRIMARY KEY,
    payload  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    token_hash    TEXT UNIQUE,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_codes (
    email      TEXT NOT NULL,
    purpose    TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    issued_at  REAL NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (email, purpose)
);
CREATE TABLE IF NOT EXISTS email_code_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    email     TEXT NOT NULL,
    purpose   TEXT NOT NULL,
    issued_at REAL NOT NULL
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
        self._migrate()
        self._conn.commit()
        self._lock = threading.Lock()

    def _migrate(self) -> None:
        """2026-10-19: accounts gained an optional unique email column
        (email-code register / password reset). Existing databases get
        it via ALTER TABLE; the partial unique index is created after
        the column is guaranteed to exist."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(accounts)")}
        if "email" not in cols:
            self._conn.execute("ALTER TABLE accounts ADD COLUMN email TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_email "
            "ON accounts(email) WHERE email IS NOT NULL"
        )

    def _load(self, table: str, key_col: str) -> dict[str, str]:
        rows = self._conn.execute(
            f"SELECT {key_col}, payload FROM {table}"  # noqa: S608
        ).fetchall()
        return dict(rows)

    def load_sessions(self) -> dict[str, str]:
        return self._load("plan_sessions", "session_id")

    def load_session(self, session_id: str) -> str | None:
        """单行读（读穿透用）：payload 或 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM plan_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def load_itineraries(self) -> dict[str, str]:
        return self._load("itineraries", "itinerary_id")

    def load_trip_items(self) -> dict[str, str]:
        return self._load("trip_items", "item_id")

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

    # --- trip items (trip-center wishlist/scheduled/booked/unwanted) ---------

    def save_trip_item(self, item_id: str, payload: str) -> None:
        self._upsert("trip_items", "item_id", item_id, payload)

    def delete_trip_item(self, item_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM trip_items WHERE item_id = ?", (item_id,))
            self._conn.commit()

    # --- accounts (custom username+password login) ---------------------------

    def save_account(
        self,
        username: str,
        password_hash: str,
        token_hash: str,
        created_at: str,
        email: str | None = None,
    ) -> None:
        with self._lock:
            # Plain INSERT (not OR REPLACE): the email unique index must
            # fail loudly instead of silently swallowing a conflicting
            # row; callers check existence before creating.
            self._conn.execute(
                "INSERT INTO accounts "
                "(username, password_hash, token_hash, created_at, email) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, token_hash, created_at, email),
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

    def get_account_by_email(
        self, email: str
    ) -> tuple[str, str, str | None, str] | None:
        """Row as ``(username, password_hash, token_hash, created_at)``
        or None. NULL emails never match."""
        row = self._conn.execute(
            "SELECT username, password_hash, token_hash, created_at "
            "FROM accounts WHERE email = ?",
            (email,),
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

    def update_account_password(self, username: str, password_hash: str) -> None:
        """Store the new hash and drop the session token (a password
        reset invalidates every active session of the account)."""
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET password_hash = ?, token_hash = NULL "
                "WHERE username = ?",
                (password_hash, username),
            )
            self._conn.commit()

    def clear_account_token(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET token_hash = NULL WHERE token_hash = ?",
                (token_hash,),
            )
            self._conn.commit()

    # --- email verification codes (register / password reset) ----------------

    def upsert_email_code(
        self,
        email: str,
        purpose: str,
        code_hash: str,
        issued_at: float,
        expires_at: float,
    ) -> None:
        """One pending code per (email, purpose); a resend replaces it
        and resets the attempt counter."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO email_codes "
                "(email, purpose, code_hash, attempts, issued_at, expires_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (email, purpose, code_hash, issued_at, expires_at),
            )
            self._conn.commit()

    def get_email_code(
        self, email: str, purpose: str
    ) -> tuple[str, int, float, float] | None:
        """Row as ``(code_hash, attempts, issued_at, expires_at)`` or None."""
        row = self._conn.execute(
            "SELECT code_hash, attempts, issued_at, expires_at "
            "FROM email_codes WHERE email = ? AND purpose = ?",
            (email, purpose),
        ).fetchone()
        return tuple(row) if row else None

    def bump_email_code_attempts(self, email: str, purpose: str) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE email_codes SET attempts = attempts + 1 "
                "WHERE email = ? AND purpose = ?",
                (email, purpose),
            )
            self._conn.commit()
        row = self.get_email_code(email, purpose)
        return row[1] if row else 0

    def log_email_code(self, email: str, purpose: str, issued_at: float) -> None:
        """Append to the send log (hourly-cap source) and prune entries
        older than a day so the table stays tiny."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO email_code_log (email, purpose, issued_at) "
                "VALUES (?, ?, ?)",
                (email, purpose, issued_at),
            )
            self._conn.execute(
                "DELETE FROM email_code_log WHERE issued_at < ?",
                (issued_at - 86_400.0,),
            )
            self._conn.commit()

    def count_email_code_log_since(self, email: str, since: float) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM email_code_log WHERE email = ? AND issued_at >= ?",
            (email, since),
        ).fetchone()
        return int(row[0])

    def delete_email_code(self, email: str, purpose: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM email_codes WHERE email = ? AND purpose = ?",
                (email, purpose),
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

    def get(self, session_id: str, *, device_id: str) -> PlanSession | None:
        """读穿透（2026-10-28 双进程事故重构）：SQLite 是会话权威，每次
        回库取新——旁路写入（运维脚本/另一端口进程）立即可见，save 端点
        不再吃到陈旧内存冻结错快照；库读失败/单行损坏才退内存缓存。"""
        try:
            payload = self._backend.load_session(session_id)
        except Exception:
            logger.warning("state_persist: session %s 读库失败，回退内存", session_id)
            payload = None
        if payload is not None:
            try:
                session = PlanSession.model_validate_json(payload)
            except Exception:
                logger.warning(
                    "state_persist: session %s payload 损坏，回退内存", session_id
                )
            else:
                self._sessions[session_id] = session
                if session.device_id != device_id:
                    return None
                return session
        return super().get(session_id, device_id=device_id)


class PersistentItineraryStore(InMemoryItineraryStore):
    """LEGACY（2026-10-25 起未接线）：行程活库已切 PG（pg_state.
    PgItineraryStore，见 api/itineraries.get_store），SQLite itineraries
    表只是停写的备份镜像——运维脚本勿再读写此镜像修数据，一律走
    PgItineraryStore.put（当天 12:0x 旁路 SQL 写坏 plan 列形状导致
    boot-load 跳行 404 的事故记录在此）。保留类仅为旧备份可读。
    """

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


class PersistentTripItemService(TripItemService):
    """Trip-center items survive restarts. ``mark_unwanted`` rides the
    overridden create/update, so three overrides cover every mutation."""

    def __init__(self, backend: SqliteStateBackend) -> None:
        super().__init__()
        self._backend = backend
        for item_id, payload in backend.load_trip_items().items():
            try:
                self._items[item_id] = json.loads(payload)
            except Exception:
                logger.warning(
                    "state_persist: dropping corrupt trip item %s",
                    item_id,
                    exc_info=True,
                )

    def create(self, name: str, *, source: str, **kwargs) -> dict:
        item = super().create(name, source=source, **kwargs)
        self._backend.save_trip_item(item["id"], json.dumps(item, ensure_ascii=False))
        return item

    def update(self, item_id: str, **kwargs) -> dict:
        item = super().update(item_id, **kwargs)
        self._backend.save_trip_item(item_id, json.dumps(item, ensure_ascii=False))
        return item

    def delete(self, item_id: str) -> None:
        super().delete(item_id)
        self._backend.delete_trip_item(item_id)


_backend_singleton: SqliteStateBackend | None = None


def get_state_backend(db_path: str) -> SqliteStateBackend:
    global _backend_singleton
    if _backend_singleton is None:
        _backend_singleton = SqliteStateBackend(db_path)
    return _backend_singleton


def db_path_from_url(url: str) -> str:
    return url.removeprefix("sqlite:///")
