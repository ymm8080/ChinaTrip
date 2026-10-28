"""真人通话咨询存储层（DESIGN/paid_call_service_design_2026-10-25 §6）。

SQLite 侧库（settings.call_db_url，默认 data/call_state.db）：单连接 +
threading.Lock + 写穿透，照 train_cache/state_persist 模式——PG 未上车的
业务 store 均走本模式，单测零 PG 可跑（构造时传 ":memory:" 即可）。

三表（设计 §6）：
- call_orders          订单（provider_ref UNIQUE = 网关回调幂等键）
- call_sessions        通话会话（服务端权威计时/状态机的唯一事实源）
- call_minutes_entries 分钟账本（只追加；余额 = SUM(delta_minutes)）

金额口径 yuan float（repo 惯例）；时间 ISO 8601 本地时区字符串。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_orders (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    username TEXT,
    package_code TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    currency TEXT NOT NULL,
    amount_yuan REAL NOT NULL,
    provider TEXT NOT NULL,
    provider_ref TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'created',
    refund_summary TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT
);
CREATE TABLE IF NOT EXISTS call_sessions (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    username TEXT,
    phone TEXT,
    mode TEXT NOT NULL DEFAULT 'direct',
    duration_minutes INTEGER NOT NULL,
    granted_minutes INTEGER NOT NULL,
    consumed_seconds INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'waiting',
    end_reason TEXT,
    agent TEXT,
    refund_minutes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS call_minutes_entries (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    username TEXT,
    delta_minutes INTEGER NOT NULL,
    kind TEXT NOT NULL,
    order_id TEXT,
    session_id TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_call_entries_owner
    ON call_minutes_entries(device_id);
CREATE INDEX IF NOT EXISTS idx_call_sessions_owner
    ON call_sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_call_sessions_status
    ON call_sessions(status);
"""

# update_session 允许写入的列（白名单防注入拼接；created_at 仅供
# 测试/运维回拨模拟超时，API 参数永远到不了这里）
_SESSION_WRITABLE = {
    "consumed_seconds",
    "status",
    "end_reason",
    "agent",
    "refund_minutes",
    "started_at",
    "ended_at",
    "created_at",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex


class CallStore:
    """通话咨询三表存储。所有方法线程安全（单连接 + 全局锁）。

    测试可注入 `db_url=":memory:"`；文件库自动建父目录并开 WAL。
    """

    def __init__(self, db_url: str) -> None:
        if db_url.startswith("sqlite:///"):
            path = db_url[len("sqlite:///") :]
        else:
            path = db_url
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -- 内部 ---------------------------------------------------------------

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    # -- 账本（余额 = SUM(delta_minutes)，只追加） ---------------------------

    def balance(self, device_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(delta_minutes), 0) AS b "
                "FROM call_minutes_entries WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            return int(row["b"])

    def add_entry(
        self,
        device_id: str,
        username: str | None,
        delta_minutes: int,
        kind: str,
        *,
        order_id: str | None = None,
        session_id: str | None = None,
        note: str | None = None,
    ) -> dict:
        entry = {
            "id": _new_id(),
            "device_id": device_id,
            "username": username,
            "delta_minutes": delta_minutes,
            "kind": kind,
            "order_id": order_id,
            "session_id": session_id,
            "note": note,
            "created_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO call_minutes_entries"
                " (id, device_id, username, delta_minutes, kind, order_id,"
                "  session_id, note, created_at)"
                " VALUES (:id, :device_id, :username, :delta_minutes, :kind,"
                "         :order_id, :session_id, :note, :created_at)",
                entry,
            )
            self._conn.commit()
        return entry

    def try_consume(
        self, device_id: str, username: str | None, minutes: int, *, session_id: str
    ) -> bool:
        """原子扣减：余额充足才写 consume 负条目（Lock 内检查+写入）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(delta_minutes), 0) AS b"
                " FROM call_minutes_entries WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if int(row["b"]) < minutes:
                return False
            self._conn.execute(
                "INSERT INTO call_minutes_entries"
                " (id, device_id, username, delta_minutes, kind, session_id,"
                "  created_at) VALUES (?, ?, ?, ?, 'consume', ?, ?)",
                (_new_id(), device_id, username, -minutes, session_id, _now()),
            )
            self._conn.commit()
            return True

    # -- 订单 ----------------------------------------------------------------

    def create_order(
        self,
        device_id: str,
        username: str | None,
        package_code: str,
        minutes: int,
        currency: str,
        amount_yuan: float,
        provider: str,
        refund_summary: str,
    ) -> dict:
        order = {
            "id": _new_id(),
            "device_id": device_id,
            "username": username,
            "package_code": package_code,
            "minutes": minutes,
            "currency": currency,
            "amount_yuan": amount_yuan,
            "provider": provider,
            "provider_ref": None,
            "status": "created",
            "refund_summary": refund_summary,
            "created_at": _now(),
            "paid_at": None,
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO call_orders (id, device_id, username,"
                " package_code, minutes, currency, amount_yuan, provider,"
                " provider_ref, status, refund_summary, created_at, paid_at)"
                " VALUES (:id, :device_id, :username, :package_code, :minutes,"
                "          :currency, :amount_yuan, :provider, :provider_ref,"
                "          :status, :refund_summary, :created_at, :paid_at)",
                order,
            )
            self._conn.commit()
        return order

    def get_order(self, order_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM call_orders WHERE id = ?", (order_id,)
            ).fetchone()
            return self._row(row)

    def mark_order_paid(self, order_id: str, provider_ref: str) -> dict | None:
        """置 paid 并入账（幂等）：已 paid 直接返回现单，不重复写账本。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM call_orders WHERE id = ?", (order_id,)
            ).fetchone()
            order = self._row(row)
            if order is None:
                return None
            if order["status"] == "paid":
                return order  # 幂等：重复回调不重复入账
            self._conn.execute(
                "UPDATE call_orders SET status = 'paid', provider_ref = ?,"
                " paid_at = ? WHERE id = ?",
                (provider_ref, _now(), order_id),
            )
            self._conn.execute(
                "INSERT INTO call_minutes_entries"
                " (id, device_id, username, delta_minutes, kind, order_id,"
                "  created_at) VALUES (?, ?, ?, ?, 'purchase', ?, ?)",
                (
                    _new_id(),
                    order["device_id"],
                    order["username"],
                    int(order["minutes"]),
                    order_id,
                    _now(),
                ),
            )
            self._conn.commit()
            return self._row(
                self._conn.execute(
                    "SELECT * FROM call_orders WHERE id = ?", (order_id,)
                ).fetchone()
            )

    def mark_order_refunded(self, order_id: str) -> dict | None:
        with self._lock:
            self._conn.execute(
                "UPDATE call_orders SET status = 'refunded' WHERE id = ?",
                (order_id,),
            )
            self._conn.commit()
            return self._row(
                self._conn.execute(
                    "SELECT * FROM call_orders WHERE id = ?", (order_id,)
                ).fetchone()
            )

    def list_orders(self, device_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM call_orders WHERE device_id = ?"
                " ORDER BY created_at DESC, rowid DESC",
                (device_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- 会话 ----------------------------------------------------------------

    def create_session(
        self,
        device_id: str,
        username: str | None,
        phone: str | None,
        mode: str,
        duration_minutes: int,
    ) -> dict:
        session = {
            "id": _new_id(),
            "device_id": device_id,
            "username": username,
            "phone": phone,
            "mode": mode,
            "duration_minutes": duration_minutes,
            "granted_minutes": duration_minutes,
            "consumed_seconds": 0,
            "status": "waiting",
            "end_reason": None,
            "agent": None,
            "refund_minutes": 0,
            "created_at": _now(),
            "started_at": None,
            "ended_at": None,
            "updated_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO call_sessions (id, device_id, username, phone,"
                " mode, duration_minutes, granted_minutes, consumed_seconds,"
                " status, end_reason, agent, refund_minutes, created_at,"
                " started_at, ended_at, updated_at)"
                " VALUES (:id, :device_id, :username, :phone, :mode,"
                "          :duration_minutes, :granted_minutes,"
                "          :consumed_seconds, :status, :end_reason, :agent,"
                "          :refund_minutes, :created_at, :started_at,"
                "          :ended_at, :updated_at)",
                session,
            )
            self._conn.commit()
        return session

    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM call_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return self._row(row)

    def update_session(self, session_id: str, **fields) -> dict | None:
        unknown = set(fields) - _SESSION_WRITABLE
        if unknown:
            raise ValueError(f"不可写会话字段: {sorted(unknown)}")
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE call_sessions SET {sets} WHERE id = ?",
                (*fields.values(), session_id),
            )
            self._conn.commit()
            return self._row(
                self._conn.execute(
                    "SELECT * FROM call_sessions WHERE id = ?", (session_id,)
                ).fetchone()
            )

    def list_sessions(self, device_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM call_sessions WHERE device_id = ?"
                " ORDER BY created_at DESC, rowid DESC",
                (device_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_agent_queue(self) -> list[dict]:
        """坐席队列：waiting 在前（最早先接），active 随后。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM call_sessions WHERE status IN ('waiting','active')"
                " ORDER BY CASE status WHEN 'waiting' THEN 0 ELSE 1 END,"
                " created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # -- 身份认领 -------------------------------------------------------------

    def claim_device(self, device_id: str, username: str) -> int:
        """登录认领：把该设备匿名账本/会话归入当前用户名。

        余额按 device_id 聚合，认领只补 username 归属（口径不变）。
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE call_minutes_entries SET username = ?"
                " WHERE device_id = ? AND username IS NULL",
                (username, device_id),
            )
            self._conn.execute(
                "UPDATE call_sessions SET username = ?"
                " WHERE device_id = ? AND username IS NULL",
                (username, device_id),
            )
            self._conn.commit()
            return cur.rowcount
