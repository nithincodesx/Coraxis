"""Structured logging with request-scoped correlation IDs.

Uses the standard library only. Log records emitted while handling a request
automatically carry ``request_id``, ``user_id`` and ``run_id`` from
:mod:`contextvars`, so a single log line is enough to trace a run end to end.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
run_id_var: ContextVar[str] = ContextVar("run_id", default="")

#: Attributes present on every LogRecord. Anything outside this set was added
#: by the caller via ``extra=`` and should be serialised.
_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

_LEVEL_COLOURS: dict[str, str] = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
_RESET = "\033[0m"


class ContextFilter(logging.Filter):
    """Attach correlation IDs from context variables to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        record.run_id = run_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key in ("request_id", "user_id", "run_id"):
            value = getattr(record, key, "")
            if value:
                payload[key] = value

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_") and key not in payload:
                payload[key] = _coerce(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable output for local development."""

    def __init__(self, colour: bool = True) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self.colour = colour

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname
        if self.colour:
            level = f"{_LEVEL_COLOURS.get(record.levelname, '')}{level:<8}{_RESET}"
        else:
            level = f"{level:<8}"

        parts = [f"{stamp} {level} {record.name:<28} {record.getMessage()}"]

        request_id = getattr(record, "request_id", "")
        if request_id:
            parts.append(f"  request_id={request_id}")
        run_id = getattr(record, "run_id", "")
        if run_id:
            parts.append(f"  run_id={run_id}")

        for key, value in record.__dict__.items():
            if (
                key not in _RESERVED
                and not key.startswith("_")
                and key
                not in {
                    "request_id",
                    "user_id",
                    "run_id",
                }
            ):
                parts.append(f"  {key}={_coerce(value)}")

        line = "".join(parts)

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"
        return line


def _coerce(value: Any) -> Any:
    """Return something JSON-serialisable without stringifying the useful bits."""
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, list | tuple):
        return [_coerce(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = False,
    colour: bool | None = None,
) -> None:
    """Install the Coraxis log handler on the root logger.

    Idempotent: calling it twice replaces the handler rather than stacking one.
    Third-party loggers that are noisy at INFO are quietened here so the
    pipeline's own output stays legible.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        with contextlib.suppress(ValueError, OSError):  # platform dependent
            stream.reconfigure(encoding="utf-8")

    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        if colour is None:
            colour = stream.isatty()
        handler.setFormatter(ConsoleFormatter(colour=colour))

    root.addHandler(handler)

    # Uvicorn installs its own handlers; let them propagate to ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    for noisy in ("httpx", "httpcore", "urllib3", "chromadb", "sentence_transformers", "litellm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name if name.startswith("coraxis") else f"coraxis.{name}")
