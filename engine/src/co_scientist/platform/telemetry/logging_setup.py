from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import sys
from collections.abc import Generator
from contextvars import ContextVar

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
    silence_litellm_logging()
    return handler


def level_to_number(name: str) -> int | None:
    """getLevelNamesMapping is Python 3.11+; getLevelName also distinguishes
    unknown names on older interpreters.
    """
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else None


__all__ = ["run_log_context", "silence_litellm_logging"]
