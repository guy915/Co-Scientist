"""Application logging: configurable format with run-id correlation.

Configures the root logger once at startup (``configure_logging``) with
either the default human-readable text format or one JSON object per
line, both on stdout. Run-scoped operations bind their run id into a
``contextvars`` context (``run_log_context``) so every record they emit
— including records from libraries they call into — carries the run id
and can be correlated with the run's persisted ``run_events`` timeline.

This module only configures the *application* process. The engine is a
library and stays handler-free (see ``engine/docs/LOGGING.md``); its
records propagate to the root handler configured here.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from collections.abc import Generator
from contextvars import ContextVar

# The run id bound to the current (async) execution context, or None
# outside run-scoped work. Async tasks inherit the value from the context
# they were created in, so one bind at the top of a workflow task covers
# every log record the run emits.
_run_id_var: ContextVar[str | None] = ContextVar("cosci_run_id", default=None)

TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def current_run_id() -> str | None:
    """Return the run id bound to the current context, if any."""
    return _run_id_var.get()


@contextlib.contextmanager
def run_log_context(run_id: str) -> Generator[None, None, None]:
    """Bind ``run_id`` to every log record emitted inside the block.

    Args:
        run_id: Identifier of the run the enclosed work belongs to.
    """
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)


class RunIdFilter(logging.Filter):
    """Stamps the context's run id onto every record as ``record.run_id``."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach the bound run id (or None) and keep the record."""
        record.run_id = _run_id_var.get()
        return True


class TextRunIdFormatter(logging.Formatter):
    """Text formatter that appends ``[run_id=...]`` for run-scoped records."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, suffixing the run id when one is bound."""
        base = super().format(record)
        run_id = getattr(record, "run_id", None)
        if run_id:
            return f"{base} [run_id={run_id}]"
        return base


class JsonFormatter(logging.Formatter):
    """Formats each record as one JSON object per line.

    Fields: ``time`` (ISO-like, from asctime), ``level``, ``logger``,
    ``message``, plus ``run_id`` when the record is run-scoped and
    ``exc_info`` when an exception was attached.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record as one JSON object."""
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
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _build_formatter(log_format: str) -> logging.Formatter:
    """Return the formatter for ``log_format`` ("json" or text default)."""
    if log_format == "json":
        return JsonFormatter()
    return TextRunIdFormatter(TEXT_FORMAT)


def configure_logging(
    log_format: str = "text", level: int = logging.INFO
) -> logging.Handler:
    """Configure root logging: one stdout handler with run-id tagging.

    Idempotent: replaces any handler this function previously installed
    instead of stacking a duplicate, so re-imports (e.g. module reloads
    in tests) do not double every log line.

    Args:
        log_format: "json" for one JSON object per line; anything else
            uses the human-readable text format.
        level: Root logger level.

    Returns:
        The installed handler (tests inspect its formatter).
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_cosci_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler._cosci_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(_build_formatter(log_format))
    handler.addFilter(RunIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
    return handler
