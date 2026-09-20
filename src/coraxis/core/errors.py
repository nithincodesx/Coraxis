"""Typed error hierarchy and RFC 7807 error responses.

Handlers raise these; :func:`register_exception_handlers` converts them into a
consistent ``application/problem+json`` body. Unexpected exceptions are logged
with a full traceback but never leak internals to the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from coraxis.core.logging import get_logger, request_id_var

logger = get_logger("errors")

PROBLEM_BASE_URI = "https://github.com/nithincodesx/Coraxis/blob/main/docs/errors.md"

#: Starlette renamed this constant; read whichever the installed version has so
#: the module does not emit a deprecation warning on newer releases.
UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class CoraxisError(Exception):
    """Base class for every error this application raises deliberately."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str = "",
        *,
        code: str | None = None,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or self.title
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.extra = extra or {}
        super().__init__(self.detail)

    def to_problem(self, instance: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{PROBLEM_BASE_URI}#{self.code}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "code": self.code,
        }
        if instance:
            body["instance"] = instance
        request_id = request_id_var.get()
        if request_id:
            body["request_id"] = request_id
        body.update(self.extra)
        return body


class ValidationError(CoraxisError):
    status_code = UNPROCESSABLE
    code = "validation_error"
    title = "Validation Error"


class AuthenticationError(CoraxisError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    title = "Authentication Required"


class AuthorizationError(CoraxisError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    title = "Forbidden"


class NotFoundError(CoraxisError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    title = "Not Found"


class ConflictError(CoraxisError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    title = "Conflict"


class RateLimitError(CoraxisError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    title = "Too Many Requests"

    def __init__(self, detail: str = "", *, retry_after: int = 60, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(detail, **kwargs)


class QuotaExceededError(CoraxisError):
    """A per-user limit was hit — distinct from transport-level rate limiting."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "quota_exceeded"
    title = "Quota Exceeded"


class ConfigurationError(CoraxisError):
    """The request cannot proceed because required configuration is missing.

    The classic case: the user has not supplied a provider API key yet.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "configuration_error"
    title = "Configuration Required"


class UpstreamError(CoraxisError):
    """A third-party dependency (LLM provider, search engine) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"
    title = "Upstream Provider Error"


def problem_response(
    body: dict[str, Any], status_code: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Build an RFC 7807 ``application/problem+json`` response.

    Public because middleware needs it: an error raised before the route runs
    never reaches an exception handler.
    """
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
        headers=headers or {},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that normalise every error response."""

    @app.exception_handler(CoraxisError)
    async def _coraxis_error(request: Request, exc: CoraxisError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
            exc.extra.setdefault("retry_after", exc.retry_after)
        if isinstance(exc, AuthenticationError):
            headers["WWW-Authenticate"] = "Bearer"

        if exc.status_code >= 500:
            logger.error("request failed: %s", exc.detail, exc_info=exc)
        else:
            logger.info("request rejected [%s]: %s", exc.code, exc.detail)

        return problem_response(exc.to_problem(str(request.url.path)), exc.status_code, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        body = {
            "type": f"{PROBLEM_BASE_URI}#validation_error",
            "title": "Validation Error",
            "status": UNPROCESSABLE,
            "detail": f"{len(fields)} field(s) failed validation.",
            "code": "validation_error",
            "instance": str(request.url.path),
            "errors": fields,
        }
        if request_id := request_id_var.get():
            body["request_id"] = request_id
        return problem_response(body, UNPROCESSABLE, {})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = {
            "type": f"{PROBLEM_BASE_URI}#http_{exc.status_code}",
            "title": str(exc.detail),
            "status": exc.status_code,
            "detail": str(exc.detail),
            "code": f"http_{exc.status_code}",
            "instance": str(request.url.path),
        }
        if request_id := request_id_var.get():
            body["request_id"] = request_id
        return problem_response(body, exc.status_code, dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log everything, disclose nothing. The request id is the link between
        # what the user saw and what is in the logs.
        logger.exception("unhandled exception on %s %s", request.method, request.url.path)
        body = {
            "type": f"{PROBLEM_BASE_URI}#internal_error",
            "title": "Internal Server Error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "detail": "An unexpected error occurred. Quote the request_id when reporting this.",
            "code": "internal_error",
            "instance": str(request.url.path),
        }
        if request_id := request_id_var.get():
            body["request_id"] = request_id
        return problem_response(body, status.HTTP_500_INTERNAL_SERVER_ERROR, {})
