# -*- coding: utf-8 -*-
"""Custom username+password accounts: one identity, many devices.

Itineraries are born anonymous (``owner_device_id`` from the H5's
X-Device-ID) - switching browsers or phones orphaned them. This module
adds a local account layer on top: register/login mint a Bearer token
(only its SHA-256 hash is stored), and claiming stitches the current
device's anonymous itineraries to the account so every logged-in device
sees the same list. Stdlib only (hashlib/hmac/secrets) - no new deps.

Email layer (2026-10-19): accounts may instead register with an email
+ 6-digit verification code (``register_email``) - the account identity
then IS the email. The same code channel powers password reset
(``reset_password``), which also invalidates the active session. Codes
live in SQLite (backend): one pending code per (email, purpose), 10 min
TTL, 5 verify attempts, 60 s resend cooldown, 10 sends/hour/email.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timezone

from app.services.itinerary_store import ItineraryStore
from app.services.mailer import DevMailer, Mailer, MailerError
from app.services.state_persist import SqliteStateBackend

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

# --- email verification codes -------------------------------------------------

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_EMAIL_MAX_LEN = 254
_EMAIL_PURPOSES = ("register", "reset_password")
_CODE_LENGTH = 6
_CODE_TTL_SECONDS = 600.0
_CODE_RESEND_COOLDOWN = 60.0
_CODE_HOURLY_LIMIT = 10
_CODE_HOURLY_WINDOW = 3600.0
_CODE_MAX_ATTEMPTS = 5


class UsernameTakenError(Exception):
    """Register: the username already exists."""


class InvalidCredentialsError(Exception):
    """Login: unknown username or wrong password."""


class EmailTakenError(Exception):
    """Email-code issue (register purpose): the email is already bound."""


class EmailNotFoundError(Exception):
    """Reset flow: no account carries this email."""


class EmailCodeError(Exception):
    """Verification failed; ``detail`` is the API error code."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class EmailCodeCooldownError(Exception):
    """Resend within the cooldown window; ``retry_after`` in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(retry_after)
        self.retry_after = retry_after


class EmailCodeRateLimitError(Exception):
    """Hourly send cap reached; ``retry_after`` in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(retry_after)
        self.retry_after = retry_after


class MailSendError(Exception):
    """The mailer failed after the code was stored; route maps to 502."""


def parse_bearer_token(authorization: str | None) -> str | None:
    """``Authorization=[redacted] header value -> token; anything
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


def _normalize_email(raw: str | None) -> str | None:
    """Strip + lowercase; None unless it looks like an RFC-ish address."""
    if raw is None:
        return None
    addr = raw.strip().lower()
    if not 3 <= len(addr) <= _EMAIL_MAX_LEN:
        return None
    if any(ch.isspace() for ch in addr):
        return None
    return addr if _EMAIL_RE.match(addr) else None


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

    The token plaintext never touches the DB - only its SHA-256 hash.
    One active session per account: a login overwrites the previous
    token hash, silently retiring the old token.
    """

    def __init__(
        self,
        backend: SqliteStateBackend,
        store: ItineraryStore,
        *,
        mailer: Mailer | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        # Same SQLite file as the itinerary store; claiming must hit the
        # same in-memory store instance the routes use.
        self._backend = backend
        self._store = store
        # None = caller did not care (tests) -> offline dev mailer.
        self._mailer: Mailer = mailer if mailer is not None else DevMailer()
        self._clock = clock

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

    def register_email(
        self,
        email: str,
        code: str,
        password: str,
        *,
        device_id: str | None = None,
    ) -> tuple[str, int]:
        """Email+code registration: the account identity IS the email.

        Returns ``(token, claimed)``. Raises ``ValueError`` for invalid
        email/password, ``EmailCodeError`` for a bad code and
        ``UsernameTakenError`` when the identity already exists (the
        issued code may predate a racing registration).
        """
        addr = _normalize_email(email)
        if addr is None:
            raise ValueError("invalid email")
        if not 6 <= len(password) <= 128:
            raise ValueError("invalid password")
        if not (code or "").strip():
            raise EmailCodeError("email_code_required")
        self.verify_email_code(addr, "register", code)
        if self._backend.get_account(addr) is not None:
            raise UsernameTakenError(addr)
        token = secrets.token_urlsafe(32)
        self._backend.save_account(
            addr,
            _hash_password(password),
            _hash_token(token),
            datetime.now(timezone.utc).isoformat(),
            email=addr,
        )
        claimed = self.claim_device_itineraries(device_id, addr) if device_id else 0
        return token, claimed

    def login(
        self,
        username: str | None,
        password: str,
        *,
        email: str | None = None,
        device_id: str | None = None,
    ) -> tuple[str, int]:
        """Verify credentials (username OR email), rotate the token,
        claim the device's anonymous itineraries. Returns
        ``(token, claimed)``.

        Raises ``InvalidCredentialsError`` on any mismatch and
        ``ValueError`` when the identifier combination is invalid.
        """
        if (username is None) == (email is None):
            # Both given or both missing - never a valid login body.
            raise ValueError("username_or_email_required")
        if email is not None:
            addr = _normalize_email(email)
            if addr is None:
                raise ValueError("invalid email")
            row = self._backend.get_account_by_email(addr)
            if row is None:
                raise InvalidCredentialsError(addr)
            name, stored = row[0], row[1]
        else:
            name = username.strip()
            row = self._backend.get_account(name)
            if row is None:
                raise InvalidCredentialsError(name)
            stored = row[0]
        if not _verify_password(password, stored):
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

    # --- email verification codes ---------------------------------------------

    def issue_email_code(self, email: str, purpose: str) -> str | None:
        """Generate + store + (try to) send a 6-digit code.

        Returns the plaintext code only when the mailer runs in dev
        mode (``mailer.dev``) so the local H5 flow works without SMTP;
        production returns ``None``. Raises ``ValueError`` for invalid
        input, ``EmailTakenError`` / ``EmailNotFoundError`` per purpose,
        ``EmailCodeCooldownError`` / ``EmailCodeRateLimitError`` for the
        send caps and ``MailSendError`` when SMTP fails.
        """
        addr = _normalize_email(email)
        if addr is None:
            raise ValueError("invalid email")
        if purpose not in _EMAIL_PURPOSES:
            raise ValueError("invalid purpose")
        if purpose == "register":
            if self._backend.get_account_by_email(addr) is not None:
                raise EmailTakenError(addr)
        else:  # reset_password: the email must belong to an account
            if self._backend.get_account_by_email(addr) is None:
                raise EmailNotFoundError(addr)
        now = self._clock()
        latest = self._backend.get_email_code(addr, purpose)
        if latest is not None and now - latest[2] < _CODE_RESEND_COOLDOWN:
            raise EmailCodeCooldownError(
                max(1, math.ceil(latest[2] + _CODE_RESEND_COOLDOWN - now))
            )
        if (
            self._backend.count_email_code_log_since(addr, now - _CODE_HOURLY_WINDOW)
            >= _CODE_HOURLY_LIMIT
        ):
            raise EmailCodeRateLimitError(_CODE_HOURLY_WINDOW)
        code = f"{secrets.randbelow(10**_CODE_LENGTH):0{_CODE_LENGTH}d}"
        self._backend.upsert_email_code(
            addr, purpose, _hash_token(code), now, now + _CODE_TTL_SECONDS
        )
        self._backend.log_email_code(addr, purpose, now)
        try:
            self._mailer.send_code(addr, code, purpose)
        except MailerError as exc:
            raise MailSendError(addr) from exc
        return code if self._mailer.dev else None

    def verify_email_code(self, email: str, purpose: str, code: str) -> None:
        """Check the pending code for ``(email, purpose)``; consume it on
        success. Raises ``EmailCodeError`` with the API detail code.

        Checks run expiry -> attempts -> hash so a stale code reports
        ``email_code_expired`` rather than a generic mismatch. Five
        wrong tries invalidate the code outright.
        """
        addr = _normalize_email(email)
        if addr is None:
            raise EmailCodeError("email_code_invalid")
        row = self._backend.get_email_code(addr, purpose)
        if row is None:
            raise EmailCodeError("email_code_invalid")
        code_hash, attempts, _issued_at, expires_at = row
        now = self._clock()
        if now >= expires_at:
            self._backend.delete_email_code(addr, purpose)
            raise EmailCodeError("email_code_expired")
        if attempts >= _CODE_MAX_ATTEMPTS:
            self._backend.delete_email_code(addr, purpose)
            raise EmailCodeError("email_code_invalid")
        if not hmac.compare_digest(code_hash, _hash_token((code or "").strip())):
            attempts = self._backend.bump_email_code_attempts(addr, purpose)
            if attempts >= _CODE_MAX_ATTEMPTS:
                self._backend.delete_email_code(addr, purpose)
            raise EmailCodeError("email_code_invalid")
        self._backend.delete_email_code(addr, purpose)

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        """Email+code password reset; the active session is invalidated.

        Raises ``ValueError`` for invalid email/password,
        ``EmailNotFoundError`` when no account carries the email and
        ``EmailCodeError`` for a bad code.
        """
        addr = _normalize_email(email)
        if addr is None:
            raise ValueError("invalid email")
        if not 6 <= len(new_password) <= 128:
            raise ValueError("invalid password")
        row = self._backend.get_account_by_email(addr)
        if row is None:
            raise EmailNotFoundError(addr)
        self.verify_email_code(addr, "reset_password", code)
        self._backend.update_account_password(row[0], _hash_password(new_password))
