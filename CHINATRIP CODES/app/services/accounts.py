# -*- coding: utf-8 -*-
"""Custom username+password accounts: one identity, many devices.

Itineraries are born anonymous (``owner_device_id`` from the H5's
X-Device-ID) — switching browsers or phones orphaned them. This module
adds a local account layer on top: register/login mint a Bearer token
(only its SHA-256 hash is stored), and claiming stitches the current
device's anonymous itineraries to the account so every logged-in device
sees the same list. Stdlib only (hashlib/hmac/secrets) — no new deps.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from app.services.itinerary_store import ItineraryStore
from app.services.state_persist import SqliteStateBackend

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16


class UsernameTakenError(Exception):
    """Register: the username already exists."""


class InvalidCredentialsError(Exception):
    """Login: unknown username or wrong password."""


def parse_bearer_token(authorization: str | None) -> str | None:
    """``Authorization: Bearer <token>`` header value -> token; anything
    else (missing header, wrong scheme, empty value) is anonymous (None)."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token or None


def _normalize_username(raw: str) -> str | None:
    """Strip, then require 2-30 chars and no whitespace/control chars."""
    name = raw.strip()
    if not 2 <= len(name) <= 30:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in name):
        return None
    return name


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt_hex, _, hash_hex = stored.partition("$")
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        # Corrupt row must not crash the login path.
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountService:
    """Register/login/logout/me + anonymous-itinerary claiming.

    The token plaintext never touches the DB — only its SHA-256 hash.
    One active session per account: a login overwrites the previous
    token hash, silently retiring the old token.
    """

    def __init__(self, backend: SqliteStateBackend, store: ItineraryStore) -> None:
        # Same SQLite file as the itinerary store; claiming must hit the
        # same in-memory store instance the routes use.
        self._backend = backend
        self._store = store

    def register(
        self, username: str, password: str, *, device_id: str | None = None
    ) -> tuple[str, int]:
        """Create the account, mint a token, then claim the device's
        anonymous itineraries. Returns ``(token, claimed)``.

        Raises ``ValueError`` for invalid input and
        ``UsernameTakenError`` when the name exists.
        """
        name = _normalize_username(username)
        if name is None:
            raise ValueError("invalid username")
        if not 6 <= len(password) <= 128:
            raise ValueError("invalid password")
        if self._backend.get_account(name) is not None:
            raise UsernameTakenError(name)
        token = secrets.token_urlsafe(32)
        self._backend.save_account(
            name,
            _hash_password(password),
            _hash_token(token),
            datetime.now(timezone.utc).isoformat(),
        )
        claimed = self.claim_device_itineraries(device_id, name) if device_id else 0
        return token, claimed

    def login(
        self, username: str, password: str, *, device_id: str | None = None
    ) -> tuple[str, int]:
        """Verify credentials, rotate the token, claim the device's
        anonymous itineraries. Returns ``(token, claimed)``.

        Raises ``InvalidCredentialsError`` on any mismatch.
        """
        name = username.strip()
        row = self._backend.get_account(name)
        if row is None or not _verify_password(password, row[0]):
            raise InvalidCredentialsError(name)
        token = secrets.token_urlsafe(32)
        self._backend.update_account_token(name, _hash_token(token))
        claimed = self.claim_device_itineraries(device_id, name) if device_id else 0
        return token, claimed

    def verify_token(self, token: str) -> str | None:
        """Bearer token -> username, or None when the session is gone."""
        return self._backend.get_username_by_token(_hash_token(token))

    def logout(self, token: str) -> None:
        """Drop this session; unknown tokens are a no-op."""
        self._backend.clear_account_token(_hash_token(token))

    def claim_device_itineraries(self, device_id: str, username: str) -> int:
        """Attach the device's not-yet-claimed itineraries to the account
        (write-through) and return how many were claimed."""
        claimed = 0
        for record in self._store.list_by_owner(device_id):
            if record.owner_account_id is None:
                record.owner_account_id = username
                self._store.put(record)
                claimed += 1
        return claimed
