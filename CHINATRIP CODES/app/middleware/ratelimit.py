"""Anonymous-phase rate limiting on the composite key device_id + client IP."""

import math
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

MINUTE_SECONDS = 60.0
HOUR_SECONDS = 3600.0


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after: int  # whole seconds, minimum 1; meaningful only when not allowed


class RateLimiter:
    """Sliding-window limiter with an injectable clock for deterministic tests."""

    def __init__(
        self,
        per_minute: int,
        per_hour: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> RateLimitResult:
        with self._lock:
            now = self.clock()
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - HOUR_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_hour:
                return RateLimitResult(
                    False, self._retry_after(hits[0], HOUR_SECONDS, now)
                )
            recent = sum(1 for ts in hits if ts > now - MINUTE_SECONDS)
            if recent >= self.per_minute:
                oldest = next(ts for ts in hits if ts > now - MINUTE_SECONDS)
                return RateLimitResult(
                    False, self._retry_after(oldest, MINUTE_SECONDS, now)
                )
            hits.append(now)
            return RateLimitResult(True, 0)

    @staticmethod
    def _retry_after(oldest: float, window: float, now: float) -> int:
        return max(1, math.ceil(oldest + window - now))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Blocks requests per device_id + client IP beyond minute/hour budgets."""

    def __init__(
        self,
        app: ASGIApp,
        per_minute: int,
        per_hour: int,
        exempt_paths: Collection[str] = ("/health", "/docs", "/redoc", "/openapi.json"),
    ) -> None:
        super().__init__(app)
        self.limiter = RateLimiter(per_minute, per_hour)
        self.exempt_paths = frozenset(exempt_paths)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        device_id = request.headers.get("X-Device-ID") or "-"
        client_ip = request.client.host if request.client else "unknown"
        result = self.limiter.check(f"{device_id}:{client_ip}")
        if not result.allowed:
            return JSONResponse(
                {"detail": "rate_limited"},
                status_code=429,
                headers={"Retry-After": str(result.retry_after)},
            )
        return await call_next(request)
