"""X-Lang 请求头 → 请求级语言 contextvar（app/services/lang_ctx.py）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.lang_ctx import set_lang


class LangMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        set_lang(request.headers.get("X-Lang"))
        return await call_next(request)
