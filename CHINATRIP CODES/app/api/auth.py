"""Custom username+password auth: register / login / logout / me.

Multi-device itinerary ownership: at register/login the calling device
(optional X-Device-ID) claims its anonymous itineraries into the
account; from then on a valid ``Authorization: Bearer <token>`` reaches
the same itinerary list from any device. Tokens are opaque 32-byte
urlsafe values — only their SHA-256 hash is stored.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.api.itineraries import get_account_service
from app.services.accounts import (
    AccountService,
    InvalidCredentialsError,
    UsernameTakenError,
    parse_bearer_token,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


class AuthCredentials(BaseModel):
    # Validation lives in AccountService so bad input maps to the
    # contract's 400 detail, not FastAPI's default 422.
    username: str
    password: str


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


@router.post("/auth/login")
async def login(
    request: AuthCredentials,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: AccountService = Depends(get_account_service),
) -> dict:
    try:
        token, claimed = service.login(
            request.username, request.password, device_id=x_device_id
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc
    return {
        "token": token,
        "username": request.username.strip(),
        "claimed": claimed,
    }


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
