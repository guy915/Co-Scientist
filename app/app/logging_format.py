"""Run-id correlation and record formatting for application logging.

The format/context half of ``app.logging_setup``, split out so that
module stays focused on handler wiring and persistent capture. Every
name is re-exported from ``app.logging_setup``, which remains the stable
import and monkeypatch surface.

Run-scoped operations bind their run id into a ``contextvars`` context
(``run_log_context``) so every record they emit -- including records
from libraries they call into -- carries the run id and can be
correlated with the run's persisted ``run_events`` timeline.
"""

from __future__ import annotations

import contextlib
import json
import logging
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
            payload["exc_info"] = record.exc_text or self.formatException(
                record.exc_info
            )
        return json.dumps(payload, default=str)


def _build_formatter(log_format: str) -> logging.Formatter:
    """Return the formatter for ``log_format`` ("json" or text default)."""
    if log_format == "json":
        return JsonFormatter()
    return TextRunIdFormatter(TEXT_FORMAT)
