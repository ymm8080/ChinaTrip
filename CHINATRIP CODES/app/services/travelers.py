# -*- coding: utf-8 -*-
"""出行人资料层（DESIGN/CLIENT_DATA_REQUIREMENTS.md，2026-10-27）。

代客预订（机票/火车/酒店/景区/演出）所需的客户实名资料，个人主页录入。
隐私合规（PIPL/GDPR 惯例，详见设计文档 §2）：

* ``doc_number`` / ``phone`` 用 Fernet 对称加密落盘，密钥 ``data/.traveler_key``
  首次自动生成（不入库不入 repo）；明文永不进列表/读取响应——只返回脱敏形。
* 归属 owner_key：登录即账号名、未登录 ``device:<id>``；与 itineraries 同款。
* ``GET /travelers/export`` 是唯一明文出口，且写审计行（动作不写内容）。
* 删除 = 物理删除（被遗忘权），无回收站。

存储：内存 dict 热路径 + SQLite write-through（payments.PaymentStore 同款
单连接 + Lock 模式）。审计表只记 (时间, 主体, 动作)，不含任何字段值。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.lang_ctx import L

logger = logging.getLogger(__name__)

DOC_TYPES = frozenset(
    {"passport", "mainland_id", "hkmo_passport", "tw_passport", "foreign_perm_id"}
)
GENDERS = frozenset({"m", "f", "x"})

MAX_TRAVELERS_PER_OWNER = 20

_CONSENT_ZH = (
    "我将上述资料仅用于代客预订（机票/火车/酒店/门票/演出实名登记），"
    "证件号与手机号加密保存、页面脱敏显示，可随时在个人主页查看或删除。"
)
_CONSENT_EN = (
    "My details are used only to place bookings on my behalf (flights, "
    "trains, hotels, tickets, shows - real-name registration). ID number "
    "and phone are stored encrypted, masked on screen, and can be viewed "
    "or deleted anytime on the profile page."
)

CONSENT_NOTICE = (_CONSENT_ZH, _CONSENT_EN)


def consent_notice() -> str:
    return L(_CONSENT_ZH, _CONSENT_EN)


class TravelerError(Exception):
    """Traveler layer error. Message is safe to surface via API detail."""


class InvalidTraveler(TravelerError):
    pass


class TravelerNotFound(TravelerError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mask(value: str) -> str:
    """保留前 5 后 2，中间打星（短值全星，绝不回明文）。"""
    if len(value) <= 7:
        return "*" * len(value)
    return value[:5] + "*" * (len(value) - 7) + value[-2:]


def _load_or_create_key(db_dir: Path) -> bytes:
    """密钥文件首次自动生成；缺失即重新生成意味着旧密文不可解——
    按隐私设计这是可接受的（用户重录），绝不把密钥写进库或 env。"""
    key_path = db_dir / ".traveler_key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
        if key:
            return key
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    logger.warning("travelers: generated new data key at %s", key_path)
    return key


class TravelerRecord(BaseModel):
    id: str
    owner_key: str = ""  # 响应中不外发（内部字段，序列化前剔除）
    label: str = ""
    full_name_en: str = ""
    full_name_zh: str | None = None
    doc_type: str
    doc_number_masked: str = ""
    doc_expiry: str | None = None
    nationality: str = ""
    date_of_birth: str | None = None
    gender: str | None = None
    phone_masked: str = ""
    email: str | None = None
    consent: bool = False
    consent_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


class TravelerInput(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    full_name_en: str = Field(min_length=1, max_length=100)
    full_name_zh: str | None = Field(default=None, max_length=100)
    doc_type: str
    doc_number: str = Field(min_length=4, max_length=64)
    doc_expiry: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    nationality: str = Field(min_length=1, max_length=60)
    date_of_birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    gender: str | None = Field(default=None, max_length=1)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    consent: bool


class TravelerStore:
    """单拥有者多出行人；明文字段只活在内存 Fernet 边界内。"""

    def __init__(self, db_path: str) -> None:
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key(db_dir))
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS travelers ("
            "id TEXT PRIMARY KEY, owner_key TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS travel_data_audit ("
            "ts TEXT NOT NULL, owner_key TEXT NOT NULL, action TEXT NOT NULL)"
        )
        self._conn.commit()
        self._lock = threading.Lock()
        # 内存热路径：owner_key -> {id: (record_dict, doc_plain, phone_plain)}
        self._rows: dict[str, dict[str, tuple[dict, str, str | None]]] = {}
        self._load_all()

    # --- persistence -----------------------------------------------------

    def _load_all(self) -> None:
        try:
            rows = self._conn.execute(
                "SELECT id, owner_key, payload FROM travelers"
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("travelers load failed: %s", exc)
            return
        for tid, owner_key, payload in rows:
            try:
                record, doc_plain, phone_plain = self._decrypt_row(payload)
            except InvalidTraveler:
                logger.warning("travelers: skipping undecryptable row %s", tid)
                continue
            self._rows.setdefault(owner_key, {})[tid] = (record, doc_plain, phone_plain)

    def _encrypt_row(
        self, record: dict, doc_plain: str, phone_plain: str | None
    ) -> str:
        return self._fernet.encrypt(
            json.dumps(
                {"record": record, "doc": doc_plain, "phone": phone_plain},
                ensure_ascii=False,
            ).encode("utf-8")
        ).decode("ascii")

    def _decrypt_row(self, payload: str) -> tuple[dict, str, str | None]:
        try:
            data = json.loads(self._fernet.decrypt(payload.encode("ascii")))
        except (InvalidToken, ValueError) as exc:
            raise InvalidTraveler("undecryptable") from exc
        return data["record"], data["doc"], data.get("phone")

    def _audit(self, owner_key: str, action: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO travel_data_audit (ts, owner_key, action) "
                "VALUES (?, ?, ?)",
                (_now_iso(), owner_key, action),
            )
            self._conn.commit()

    # --- public API --------------------------------------------------------

    def list_for_owner(self, owner_key: str) -> list[dict]:
        rows = self._rows.get(owner_key, {})
        return [self._masked(rec) for rec, _, _ in rows.values()]

    def get_masked(self, owner_key: str, traveler_id: str) -> dict:
        row = self._rows.get(owner_key, {}).get(traveler_id)
        if row is None:
            raise TravelerNotFound(traveler_id)
        return self._masked(row[0])

    def create(self, owner_key: str, data: TravelerInput) -> dict:
        if not data.consent:
            raise InvalidTraveler("consent_required")
        if data.doc_type not in DOC_TYPES:
            raise InvalidTraveler("invalid_doc_type")
        if data.gender is not None and data.gender not in GENDERS:
            raise InvalidTraveler("invalid_gender")
        bucket = self._rows.setdefault(owner_key, {})
        if len(bucket) >= MAX_TRAVELERS_PER_OWNER:
            raise InvalidTraveler("too_many_travelers")
        tid = "trv_" + uuid.uuid4().hex[:12]
        now = _now_iso()
        record = {
            "id": tid,
            "label": (data.label or "").strip(),
            "full_name_en": data.full_name_en.strip(),
            "full_name_zh": (data.full_name_zh or "").strip() or None,
            "doc_type": data.doc_type,
            "doc_expiry": data.doc_expiry,
            "nationality": data.nationality.strip(),
            "date_of_birth": data.date_of_birth,
            "gender": data.gender,
            "email": (data.email or "").strip() or None,
            "consent": True,
            "consent_at": now,
            "created_at": now,
            "updated_at": now,
        }
        doc_plain = data.doc_number.strip()
        phone_plain = (data.phone or "").strip() or None
        record["doc_number_masked"] = _mask(doc_plain)
        record["phone_masked"] = _mask(phone_plain) if phone_plain else ""
        bucket[tid] = (record, doc_plain, phone_plain)
        self._persist(owner_key, tid)
        self._audit(owner_key, "create")
        return self._masked(record)

    def update(self, owner_key: str, traveler_id: str, data: TravelerInput) -> dict:
        if not data.consent:
            raise InvalidTraveler("consent_required")
        if data.doc_type not in DOC_TYPES:
            raise InvalidTraveler("invalid_doc_type")
        if data.gender is not None and data.gender not in GENDERS:
            raise InvalidTraveler("invalid_gender")
        bucket = self._rows.get(owner_key, {})
        row = bucket.get(traveler_id)
        if row is None:
            raise TravelerNotFound(traveler_id)
        record = row[0]
        record.update(
            {
                "label": (data.label or "").strip(),
                "full_name_en": data.full_name_en.strip(),
                "full_name_zh": (data.full_name_zh or "").strip() or None,
                "doc_type": data.doc_type,
                "doc_expiry": data.doc_expiry,
                "nationality": data.nationality.strip(),
                "date_of_birth": data.date_of_birth,
                "gender": data.gender,
                "email": (data.email or "").strip() or None,
                "updated_at": _now_iso(),
            }
        )
        doc_plain = data.doc_number.strip()
        phone_plain = (data.phone or "").strip() or None
        record["doc_number_masked"] = _mask(doc_plain)
        record["phone_masked"] = _mask(phone_plain) if phone_plain else ""
        bucket[traveler_id] = (record, doc_plain, phone_plain)
        self._persist(owner_key, traveler_id)
        self._audit(owner_key, "update")
        return self._masked(record)

    def delete(self, owner_key: str, traveler_id: str) -> None:
        bucket = self._rows.get(owner_key, {})
        if traveler_id not in bucket:
            raise TravelerNotFound(traveler_id)
        del bucket[traveler_id]
        with self._lock:
            self._conn.execute("DELETE FROM travelers WHERE id = ?", (traveler_id,))
            self._conn.commit()
        self._audit(owner_key, "delete")

    def delete_all(self, owner_key: str) -> int:
        n = len(self._rows.get(owner_key, {}))
        self._rows.pop(owner_key, None)
        with self._lock:
            self._conn.execute(
                "DELETE FROM travelers WHERE owner_key = ?", (owner_key,)
            )
            self._conn.commit()
        self._audit(owner_key, "delete_all")
        return n

    def export_plaintext(self, owner_key: str) -> list[dict]:
        """唯一明文出口（可携权）；调用方必须先写审计。"""
        self._audit(owner_key, "export")
        out = []
        for record, doc_plain, phone_plain in self._rows.get(owner_key, {}).values():
            item = self._masked(record)
            item["doc_number"] = doc_plain
            item["phone"] = phone_plain
            out.append(item)
        return out

    # --- internals ---------------------------------------------------------

    def _persist(self, owner_key: str, traveler_id: str) -> None:
        record, doc_plain, phone_plain = self._rows[owner_key][traveler_id]
        payload = self._encrypt_row(record, doc_plain, phone_plain)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO travelers (id, owner_key, payload) "
                "VALUES (?, ?, ?)",
                (traveler_id, owner_key, payload),
            )
            self._conn.commit()

    @staticmethod
    def _masked(record: dict) -> dict:
        out = dict(record)
        out.pop("owner_key", None)
        return out


_service_singleton: TravelerStore | None = None


def _db_path(url: str) -> str:
    """config 存的是 SQLAlchemy 风格 URL（sqlite:///data/travelers.db），
    本 store 用裸 sqlite3——剥 scheme；相对路径按 cwd 解析（payments 同款）。"""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return url[len(prefix) :]
    return url


def get_travelers_service() -> TravelerStore:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = TravelerStore(_db_path(get_settings().travelers_db_url))
    return _service_singleton
