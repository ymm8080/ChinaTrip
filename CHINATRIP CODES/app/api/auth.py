"""Custom username+password auth: register / login / logout / me.

Multi-device itinerary ownership: at register/login the calling device
(optional X-Device-ID) claims its anonymous itineraries into the
account; from then on a valid ``Authorization: Bearer`` reaches
the same itinerary list from any device. Tokens are opaque 32-byte
urlsafe values - only their SHA-256 hash is stored.

Email layer (2026-10-19): ``POST /auth/email/code`` issues a 6-digit
verification code (purposes: register / reset_password);
``POST /auth/email/register`` creates an email-identity account;
``POST /auth/password/reset`` runs the forgot-password flow; login
accepts either ``email`` or the legacy ``username``. With SMTP
unconfigured the dev mailer echoes the code (WARNING log + response)
so the whole flow works offline.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.api.itineraries import get_account_service
from app.services.accounts import (
    AccountService,
    EmailCodeCooldownError,
    EmailCodeError,
    EmailCodeRateLimitError,
    EmailNotFoundError,
    EmailTakenError,
    InvalidCredentialsError,
    MailSendError,
    UsernameTakenError,
    parse_bearer_token,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])

_EMAIL_PURPOSES = ("register", "reset_password")


class AuthCredentials(BaseModel):
    # Validation lives in AccountService so bad input maps to the
    # contract's 400 detail, not FastAPI's default 422.
    username: str
    password: str


class LoginRequest(BaseModel):
    # Exactly one identifier - enforced in the route -> contract detail.
    username: str | None = None
    email: str | None = None
    password: str


class EmailCodeRequest(BaseModel):
    email: str
    purpose: str  # "register" | "reset_password"


class EmailRegisterRequest(BaseModel):
    email: str
    code: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str
    code: str
    new_password: str


def _valid_token_or_401(
    authorization: str | None, service: AccountService
) -> tuple[str, str]:
    """``(username, token)`` for a live Bearer session, else 401."""
    token = parse_bearer_token(authorization)
    if token is not None:
        username = service.verify_token(token)
        if username is not None:
            return username, token
    raise HTTPException(status_code=401, detail="invalid_token")


@router.post("/auth/register", status_code=201)
async def register(
    request: AuthCredentials,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: AccountService = Depends(get_account_service),
) -> dict:
    try:
        token, claimed = service.register(
            request.username, request.password, device_id=x_device_id
        )
    except UsernameTakenError as exc:
        raise HTTPException(status_code=400, detail="username_taken") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid_username_or_password"
        ) from exc
    return {
        "token": token,
        "username": request.username.strip(),
        "claimed": claimed,
    }


@router.post("/auth/email/register", status_code=201)
async def register_email(
    request: EmailRegisterRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: AccountService = Depends(get_account_service),
) -> dict:
    identity = request.email.strip().lower()
    try:
        token, claimed = service.register_email(
            request.email, request.code, request.password, device_id=x_device_id
        )
    except EmailTakenError as exc:
        raise HTTPException(status_code=400, detail="email_taken") from exc
    except UsernameTakenError as exc:
        # The code was issued before a racing registration took the email.
        raise HTTPException(status_code=400, detail="email_taken") from exc
    except EmailCodeError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid_email_or_password"
        ) from exc
    return {"token": token, "username": identity, "claimed": claimed}


@router.post("/auth/email/code")
async def send_email_code(
    request: EmailCodeRequest,
    service: AccountService = Depends(get_account_service),
) -> dict:
    if request.purpose not in _EMAIL_PURPOSES:
        raise HTTPException(status_code=400, detail="invalid_purpose")
    try:
        dev_code = await run_in_threadpool(
            service.issue_email_code, request.email, request.purpose
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_email") from exc
    except EmailTakenError as exc:
        raise HTTPException(status_code=400, detail="email_taken") from exc
    except EmailNotFoundError as exc:
        raise HTTPException(status_code=404, detail="email_not_found") from exc
    except EmailCodeCooldownError as exc:
        raise HTTPException(
            status_code=429,
            detail="code_cooldown",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except EmailCodeRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="code_rate_limited",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except MailSendError as exc:
        raise HTTPException(status_code=502, detail="mail_send_failed") from exc
    body: dict = {"sent": True}
    if dev_code:
        # Dev mailer only (smtp_host empty) - never leaks codes in prod.
        body["dev_code"] = dev_code
    return body


@router.post("/auth/login")
async def login(
    request: LoginRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: AccountService = Depends(get_account_service),
) -> dict:
    if (request.username is None) == (request.email is None):
        raise HTTPException(status_code=400, detail="username_or_email_required")
    try:
        token, claimed = service.login(
            request.username,
            request.password,
            email=request.email,
            device_id=x_device_id,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="username_or_email_required"
        ) from exc
    identity = (
        request.username.strip() if request.username else request.email.strip().lower()
    )
    return {"token": token, "username": identity, "claimed": claimed}


@router.post("/auth/password/reset", status_code=204)
async def reset_password(
    request: PasswordResetRequest,
    service: AccountService = Depends(get_account_service),
) -> None:
    try:
        await run_in_threadpool(
            service.reset_password, request.email, request.code, request.new_password
        )
    except EmailNotFoundError as exc:
        raise HTTPException(status_code=404, detail="email_not_found") from exc
    except EmailCodeError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid_email_or_password"
        ) from exc


@router.post("/auth/logout", status_code=204)
async def logout(
    authorization: str | None = Header(default=None),
    service: AccountService = Depends(get_account_service),
) -> None:
    _, token = _valid_token_or_401(authorization, service)
    service.logout(token)


@router.get("/auth/me")
async def me(
    authorization: str | None = Header(default=None),
    service: AccountService = Depends(get_account_service),
) -> dict:
    username, _ = _valid_token_or_401(authorization, service)
    return {"username": username}
