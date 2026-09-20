"""HTTP middleware: request correlation, access logging, and rate limiting."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from coraxis.core.config import get_settings
from coraxis.core.errors import RateLimitError, problem_response
from coraxis.core.logging import get_logger, request_id_var
from coraxis.core.ratelimit import limiter

logger = get_logger("http")

#: Paths exempt from request rate limiting — probes and docs must always answer.
_EXEMPT_PREFIXES = ("/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json")

#: Cap on the client-supplied request id. Prevents a hostile header from
#: bloating every log line.
_MAX_REQUEST_ID = 64


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, time the request, and log one line per request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming[:_MAX_REQUEST_ID] if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception("%s %s failed after %.1fms", request.method, request.url.path, elapsed)
            raise
        finally:
            request_id_var.reset(token)

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed:.1f}"

        # Health probes are noisy and uninteresting; log everything else.
        if not request.url.path.startswith(_EXEMPT_PREFIXES):
            logger.info(
                "%s %s -> %d in %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client request rate limiting.

    Keyed on the bearer token when present, otherwise the client IP, so a
    logged-in user is not penalised for sharing an address with a busy network.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        settings = get_settings()

        if not settings.rate_limit_enabled or request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            # Never key on the raw token — that would put a credential in memory
            # as a map key and in any heap dump.
            client_key = f"token:{hash(authorization) & 0xFFFFFFFF:08x}"
        else:
            client_key = f"ip:{request.client.host if request.client else 'unknown'}"

        result = await limiter.hit(
            f"http:{client_key}",
            settings.rate_limit_requests_per_minute,
            window_seconds=60,
        )

        if not result.allowed:
            error = RateLimitError(
                "Too many requests. Slow down and retry shortly.",
                retry_after=max(1, int(result.reset_after)),
            )
            return problem_response(
                error.to_problem(str(request.url.path)),
                error.status_code,
                {"Retry-After": str(error.retry_after), **result.as_headers()},
            )

        response = await call_next(request)
        for header, value in result.as_headers().items():
            response.headers[header] = value
        return response
