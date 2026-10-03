"""Run-id correlation, record formatting and dependency logging policy.

Run-scoped operations bind a ContextVar so records from their dependencies
carry the same id. LiteLLM noise is suppressed at import for standalone
workers and reapplied when application logging is configured.
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


# LiteLLM attaches its own handler directly to these loggers at import
# (litellm/_logging.py): a colored StreamHandler defaulting to stderr,
# independent of the root handler ``logging_setup`` configures. Root's own
# level does nothing to it -- an ordinary INFO line comes back as two
# records, a colored one on stderr (Railway reads stderr as
# `severity: error`, and this doubled a stdout call-count taken earlier)
# and a plain one on stdout via propagation to root. ``LITELLM_LOG``
# (litellm's own env var) does not stop either: read once at import, it
# sets only that handler's level, never the logger's own, so propagation
# is unaffected. Setting the level directly on the logger does stop both
# -- a logger's effective level gates whether a record is created at all,
# before any handler runs and before propagation. Verified live: with
# root at INFO, an unpatched ``getLogger("LiteLLM").info(...)`` produced
# both copies regardless of ``LITELLM_LOG``; after ``setLevel(WARNING)``
# it produced neither, and ``.warning()`` still came through on both.
_LITELLM_LOGGER_NAMES: tuple[str, ...] = (
    "LiteLLM",
    "LiteLLM Router",
    "LiteLLM Proxy",
)


def silence_litellm_logging() -> None:
    """Raise LiteLLM's own loggers to WARNING; drop its debug print banner.

    Two unrelated mechanisms. The logger levels (module comment above)
    stop the duplicated per-call INFO lines. ``litellm.suppress_debug_info``
    is unrelated to logging entirely -- the repeated "Provider List"
    banner is a plain ``print()`` in litellm's provider-resolution code,
    guarded only by that flag.

    Called at import of this module, so a durable worker process (which
    never calls ``configure_logging``) inherits this merely by importing
    ``app.logging_setup`` for ``run_log_context``, and again from
    ``configure_logging`` itself so reconfiguring cannot leave it unset.
    """
    for name in _LITELLM_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        import litellm
    except ImportError:
        return
    litellm.suppress_debug_info = True


silence_litellm_logging()
