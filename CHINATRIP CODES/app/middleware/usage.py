"""Intended order: usage outermost (measures all incl. 429s), ratelimit inside it."""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("chinatrip.usage")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Propagates a trace id and logs one structured JSON line per request."""

    def __init__(self, app, region: str = "CN") -> None:
        super().__init__(app)
        self._region = region

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
        device_id = request.headers.get("X-Device-ID") or "-"
        client_ip = request.client.host if request.client else "unknown"
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000)
        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "trace_id": trace_id,
                    "device_id": device_id,
                    "client_ip": client_ip,
                    "region": self._region,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
        )
        return response
