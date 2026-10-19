# -*- coding: utf-8 -*-
"""Email verification codes: send / email register / password reset.

Offline throughout: the mailer is a recording fake (dev flag controls
whether the API echoes the code), the clock is injectable so TTL /
cooldown / hourly-cap behave deterministically, and SMTP delivery is
covered by monkeypatched smtplib fakes. Legacy (username-only) databases
must migrate in place on boot - covered here too.
"""

import smtplib
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.itineraries import (
    get_account_service,
    get_entitlement_service,
    get_store,
)
from app.api.itineraries import router as itineraries_router
from app.services.accounts import AccountService
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary_store import InMemoryItineraryStore
from app.services.mailer import DevMailer, MailerError, SmtpMailer, get_mailer
from app.services.state_persist import SqliteStateBackend

DEV_A = {"X-Device-ID": "device-a"}
EMAIL = "User@Example.com"  # deliberately mixed case; backend normalizes


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeMailer:
    """Records sends; ``dev=True`` makes the API echo the code back."""

    def __init__(self, dev: bool = True) -> None:
        self.dev = dev
        self.sent: list[tuple[str, str, str]] = []

    def send_code(self, to_email: str, code: str, purpose: str) -> None:
        self.sent.append((to_email, code, purpose))


class BoomMailer(FakeMailer):
    def send_code(self, to_email: str, code: str, purpose: str) -> None:
        raise MailerError("smtp down")


def make_client(tmp_path, mailer=None, clock=None) -> tuple[TestClient, AccountService]:
    store = InMemoryItineraryStore()
    backend = SqliteStateBackend(str(tmp_path / "accounts.db"))
    account = AccountService(
        backend, store, mailer=mailer or FakeMailer(), clock=clock or FakeClock()
    )
    entitlement = EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": 3}
    )
    app = FastAPI()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_account_service] = lambda: account
    app.dependency_overrides[get_entitlement_service] = lambda: entitlement
    app.include_router(auth_router)
    app.include_router(itineraries_router)
    return TestClient(app), account


def send_code(client: TestClient, email=EMAIL, purpose="register"):
    return client.post(
        "/api/v1/auth/email/code", json={"email": email, "purpose": purpose}
    )


def register_email(
    client: TestClient, code, password="secret123", email=EMAIL, headers=DEV_A
):
    return client.post(
        "/api/v1/auth/email/register",
        json={"email": email, "code": code, "password": password},
        headers=headers,
    )


# --- send code ----------------------------------------------------------------


def test_send_code_dev_echoes_six_digit_code(tmp_path):
    client, account = make_client(tmp_path)
    resp = send_code(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"sent": True, "dev_code": body["dev_code"]}
    assert len(body["dev_code"]) == 6 and body["dev_code"].isdigit()
    # Email normalized (lowercase) before storage and delivery.
    to, code, purpose = account._mailer.sent[0]
    assert to == "user@example.com"
    assert code == body["dev_code"] and purpose == "register"


def test_send_code_production_mailer_does_not_echo(tmp_path):
    client, account = make_client(tmp_path, mailer=FakeMailer(dev=False))
    resp = send_code(client)
    assert resp.status_code == 200
    assert resp.json() == {"sent": True}
    assert len(account._mailer.sent[0][1]) == 6


def test_send_code_resend_cooldown_429_with_retry_after(tmp_path):
    client, _ = make_client(tmp_path)
    assert send_code(client).status_code == 200
    resp = send_code(client)
    assert resp.status_code == 429
    assert resp.json()["detail"] == "code_cooldown"
    assert int(resp.headers["Retry-After"]) >= 1


def test_send_code_hourly_cap_429(tmp_path):
    clock = FakeClock()
    client, _ = make_client(tmp_path, clock=clock)
    for _ in range(10):
        assert send_code(client).status_code == 200
        clock.advance(60)  # clear the 60s cooldown, stay inside the hour
    resp = send_code(client)
    assert resp.status_code == 429
    assert resp.json()["detail"] == "code_rate_limited"


def test_send_code_register_purpose_taken_email_400(tmp_path):
    client, _ = make_client(tmp_path)
    code = send_code(client).json()["dev_code"]
    assert register_email(client, code).status_code == 201
    # Second register-purpose send: the email is bound by now (checked
    # before the resend cooldown, so 400 - not 429).
    resp = send_code(client)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_taken"


def test_send_code_reset_unknown_email_404(tmp_path):
    client, _ = make_client(tmp_path)
    resp = send_code(client, purpose="reset_password")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "email_not_found"


def test_send_code_invalid_email_400(tmp_path):
    client, _ = make_client(tmp_path)
    resp = send_code(client, email="not-an-email")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_email"


def test_send_code_invalid_purpose_400(tmp_path):
    client, _ = make_client(tmp_path)
    resp = send_code(client, purpose="login")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_purpose"


def test_send_code_mailer_failure_502(tmp_path):
    client, _ = make_client(tmp_path, mailer=BoomMailer())
    resp = send_code(client)
    assert resp.status_code == 502
    assert resp.json()["detail"] == "mail_send_failed"


# --- email registration ---------------------------------------------------------


def test_register_email_ok_and_login_by_email(tmp_path):
    client, _ = make_client(tmp_path)
    code = send_code(client).json()["dev_code"]
    resp = register_email(client, code)
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "user@example.com"
    assert body["claimed"] == 0
    # /me recognizes the registration token right away.
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert me.status_code == 200
    assert me.json() == {"username": "user@example.com"}
    # Login with the email identifier + password mints a fresh token.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": "secret123"},
        headers=DEV_A,
    )
    assert login.status_code == 200
    assert login.json()["username"] == "user@example.com"
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        ).status_code
        == 200
    )


def test_register_email_claims_device_itineraries(tmp_path):
    client, _ = make_client(tmp_path)
    create = client.post(
        "/api/v1/itineraries",
        json={"cities": ["北京"], "days": 2},
        headers=DEV_A,
    )
    assert create.status_code == 201
    code = send_code(client).json()["dev_code"]
    body = register_email(client, code).json()
    assert body["claimed"] == 1


def test_register_email_missing_code_400(tmp_path):
    client, _ = make_client(tmp_path)
    resp = register_email(client, "")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_code_required"


def test_register_email_wrong_code_400(tmp_path):
    client, _ = make_client(tmp_path)
    send_code(client)
    resp = register_email(client, "000000")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_code_invalid"


def test_register_email_expired_code_400(tmp_path):
    clock = FakeClock()
    client, _ = make_client(tmp_path, clock=clock)
    send_code(client)
    clock.advance(601)  # TTL is 600s
    resp = register_email(client, "000000")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_code_expired"


def test_register_email_code_dies_after_five_wrong_tries(tmp_path):
    client, _ = make_client(tmp_path)
    real = send_code(client).json()["dev_code"]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        resp = register_email(client, wrong)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "email_code_invalid"
    # The sixth attempt - even with the correct code - is rejected.
    resp = register_email(client, real)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_code_invalid"


def test_register_email_weak_password_400(tmp_path):
    client, _ = make_client(tmp_path)
    send_code(client)
    resp = register_email(client, "123456", password="12345")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_email_or_password"


def test_register_email_bad_email_400(tmp_path):
    client, _ = make_client(tmp_path)
    resp = register_email(client, "123456", email="foo@bar")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_email_or_password"


def test_register_email_rejects_identity_taken_by_legacy_account(tmp_path):
    # A legacy account whose username string happens to be an email is
    # not "email-bound" (its email column is NULL), so code issuing
    # passes - but the registration itself must refuse the identity.
    client, _ = make_client(tmp_path)
    legacy = client.post(
        "/api/v1/auth/register",
        json={"username": "user@example.com", "password": "secret123"},
    )
    assert legacy.status_code == 201
    code = send_code(client).json()["dev_code"]
    resp = register_email(client, code)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_taken"


# --- password reset -------------------------------------------------------------


def seed_email_account(tmp_path):
    client, _ = make_client(tmp_path)
    code = send_code(client).json()["dev_code"]
    register_email(client, code)
    return client


def test_reset_password_flow_invalidates_old_session(tmp_path):
    client = seed_email_account(tmp_path)
    old_token = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "secret123"}
    ).json()["token"]
    code = send_code(client, purpose="reset_password").json()["dev_code"]
    resp = client.post(
        "/api/v1/auth/password/reset",
        json={"email": EMAIL, "code": code, "new_password": "brand-new-6"},
    )
    assert resp.status_code == 204
    # Old session token is dead.
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
        ).status_code
        == 401
    )
    # New password works, old one does not.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": "brand-new-6"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": "secret123"}
        ).status_code
        == 401
    )


def test_reset_password_wrong_code_400(tmp_path):
    client = seed_email_account(tmp_path)
    send_code(client, purpose="reset_password")
    resp = client.post(
        "/api/v1/auth/password/reset",
        json={"email": EMAIL, "code": "999999", "new_password": "brand-new-6"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_code_invalid"


def test_reset_password_weak_password_400(tmp_path):
    client = seed_email_account(tmp_path)
    code = send_code(client, purpose="reset_password").json()["dev_code"]
    resp = client.post(
        "/api/v1/auth/password/reset",
        json={"email": EMAIL, "code": code, "new_password": "12345"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_email_or_password"


def test_reset_password_unknown_email_404(tmp_path):
    client, _ = make_client(tmp_path)
    resp = client.post(
        "/api/v1/auth/password/reset",
        json={"email": EMAIL, "code": "123456", "new_password": "brand-new-6"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "email_not_found"


# --- login identifier rules -------------------------------------------------------


def test_login_requires_exactly_one_identifier(tmp_path):
    client, _ = make_client(tmp_path)
    neither = client.post("/api/v1/auth/login", json={"password": "secret123"})
    assert neither.status_code == 400
    assert neither.json()["detail"] == "username_or_email_required"
    both = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "email": EMAIL, "password": "secret123"},
    )
    assert both.status_code == 400
    assert both.json()["detail"] == "username_or_email_required"


def test_login_by_email_unknown_for_legacy_username_account(tmp_path):
    client, _ = make_client(tmp_path)
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"username": "alice", "password": "secret123"},
        ).status_code
        == 201
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "secret123"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_credentials"
    # Legacy username login still works.
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "secret123"},
        ).status_code
        == 200
    )


# --- persistence: legacy database migration ---------------------------------------


def test_legacy_db_gains_email_column_on_boot(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE accounts ("
        "username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, "
        "token_hash TEXT UNIQUE, created_at TEXT NOT NULL);"
    )
    conn.execute("INSERT INTO accounts VALUES ('alice', 'hash', NULL, '2026-01-01')")
    conn.commit()
    conn.close()
    backend = SqliteStateBackend(str(db))
    backend.save_account("bob", "h2", None, "2026-01-02", email="bob@example.com")
    row = backend.get_account_by_email("bob@example.com")
    assert row is not None and row[0] == "bob"
    # Legacy row is untouched and still findable by username.
    assert backend.get_account("alice") is not None
    # The partial unique index rejects a second account with the same
    # email instead of silently swallowing it (plain INSERT).
    try:
        backend.save_account("carol", "h3", None, "2026-01-03", email="bob@example.com")
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised


# --- SMTP mailer (offline via fakes) ----------------------------------------------


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.logged_in = False
        self.sent = []
        self.started_tls = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def login(self, user, password):
        self.logged_in = True

    def starttls(self, context=None):
        self.started_tls = True

    def sendmail(self, frm, to, body):
        self.sent.append((frm, to, body))


def smtp_settings(**overrides):
    from app.config import Settings

    kwargs = {
        "smtp_host": "smtp.test",
        "smtp_port": 465,
        "smtp_user": "u@test",
        "smtp_pass": "pw",
        "smtp_from": "no-reply@test",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def test_smtp_message_carries_code_and_addresses():
    msg = SmtpMailer(smtp_settings())._message("to@example.com", "123456", "register")
    text = msg.get_payload(decode=True).decode("utf-8")
    assert "123456" in text
    assert msg["To"] == "to@example.com"
    assert "no-reply@test" in msg["From"]


def test_smtp_mailer_implicit_ssl_on_465(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    SmtpMailer(smtp_settings()).send_code("to@example.com", "123456", "register")
    inst = FakeSMTP.instances[0]
    assert inst.port == 465 and inst.logged_in
    frm, to, _body = inst.sent[0]
    assert frm == "no-reply@test" and to == ["to@example.com"]


def test_smtp_mailer_starttls_on_587(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    SmtpMailer(smtp_settings(smtp_port=587)).send_code(
        "to@example.com", "654321", "reset_password"
    )
    inst = FakeSMTP.instances[0]
    assert inst.started_tls and inst.logged_in
    assert inst.sent[0][1] == ["to@example.com"]


def test_smtp_mailer_wraps_errors(monkeypatch):
    class ExplodingSMTP(FakeSMTP):
        def sendmail(self, frm, to, body):
            raise smtplib.SMTPException("relay refused")

    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", ExplodingSMTP)
    try:
        SmtpMailer(smtp_settings()).send_code("to@example.com", "123456", "register")
        raised = False
    except MailerError:
        raised = True
    assert raised


def test_get_mailer_dev_fallback_without_smtp(monkeypatch):
    import app.services.mailer as mod

    monkeypatch.setattr(mod, "_mailer_singleton", None)
    assert isinstance(get_mailer(), DevMailer)


def test_mailer_dev_flags():
    assert DevMailer.dev is True
    assert SmtpMailer(smtp_settings()).dev is False
