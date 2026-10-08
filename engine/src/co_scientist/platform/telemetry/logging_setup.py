from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import sys
from collections.abc import Generator
from contextvars import ContextVar

from co_scientist.platform.telemetry.tracing import current_trace_id

# Child tasks inherit run context, allowing one workflow binding to correlate
# every emitted record.
_run_id_var: ContextVar[str | None] = ContextVar("cosci_run_id", default=None)


def current_run_id() -> str | None:
    return _run_id_var.get()


@contextlib.contextmanager
def run_log_context(run_id: str) -> Generator[None, None, None]:
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()
        record.trace_id = current_trace_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        run_id = getattr(record, "run_id", None)
        if run_id:
            payload["run_id"] = run_id
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            payload["trace_id"] = trace_id
        if record.exc_info:
            payload["exc_info"] = record.exc_text or self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# LiteLLM installs its own handler; root levels and LITELLM_LOG do not stop
# duplicate propagation, so set logger levels directly.
_LITELLM_LOGGER_NAMES: tuple[str, ...] = (
    "LiteLLM",
    "LiteLLM Router",
    "LiteLLM Proxy",
)


def silence_litellm_logging() -> None:
    """LiteLLM's own logger handlers bypass root levels."""
    for name in _LITELLM_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)


silence_litellm_logging()


# Uvicorn's own config writes lifecycle lines and ASGI tracebacks to stderr as
# plain text, which the host files at error severity line by line. Only the
# parents carry handlers; "uvicorn.error" propagates to "uvicorn".
_UVICORN_HANDLER_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.access")


def _route_uvicorn_logging(handler: logging.Handler) -> None:
    """Replace only stream handlers: log capture attaches its own queue
    handler to these loggers and must survive a reconfiguration.
    """
    for name in _UVICORN_HANDLER_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        for existing in list(uvicorn_logger.handlers):
            if isinstance(existing, logging.StreamHandler):
                uvicorn_logger.removeHandler(existing)
        uvicorn_logger.addHandler(handler)
        uvicorn_logger.propagate = False


def _byok_redaction_filter() -> logging.Filter:
    """Lazy import avoids pulling credential cryptography into logging-only
    processes; provider errors still need redaction.
    """
    from co_scientist.core.byok_scope import ByokRedactionFilter

    return ByokRedactionFilter()


def configure_logging(level: int = logging.INFO) -> logging.Handler:
    """Replace the previously installed handler so reloads cannot duplicate
    every record.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_cosci_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler._cosci_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RunIdFilter())
    handler.addFilter(_byok_redaction_filter())
    root.addHandler(handler)
    root.setLevel(level)
    _route_uvicorn_logging(handler)
    silence_litellm_logging()
    return handler


def level_to_number(name: str) -> int | None:
    """getLevelNamesMapping is Python 3.11+; getLevelName also distinguishes
    unknown names on older interpreters.
    """
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else None


__all__ = ["run_log_context", "silence_litellm_logging"]
