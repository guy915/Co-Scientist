"""Application logging: configurable format, run-id correlation, capture.

Configures the root logger once at startup (``configure_logging``) with
either the default human-readable text format or one JSON object per
line, both on stdout. Run-scoped operations bind their run id into a
``contextvars`` context (``run_log_context``) so every record they emit
— including records from libraries they call into — carries the run id
and can be correlated with the run's persisted ``run_events`` timeline.

``configure_log_capture`` additionally persists every record that
reaches the root logger into the ``app_logs`` table: the hot path only
enqueues (a ``QueueHandler`` stamped with the run id on the emitting
thread), and a background ``QueueListener`` thread writes rows and
enforces retention, so logging never blocks on SQLite and a store
failure can never take down the caller.

This module only configures the *application* process. The engine is a
library and stays handler-free (see ``engine/docs/LOGGING.md``); its
records propagate to the root handler configured here.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import logging.handlers
import queue
import sys
from collections.abc import Generator
from contextvars import ContextVar

from app import store

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


# ---------------------------------------------------------------------------
# Persistent capture: root logger -> app_logs table
# ---------------------------------------------------------------------------

# How many rows the writer inserts between retention sweeps.
_PRUNE_EVERY = 500

# Default cap on persisted rows; also settable via configure_log_capture.
DEFAULT_LOG_MAX_ROWS = 20_000

_EXC_FORMATTER = logging.Formatter()


def level_to_number(name: str) -> int | None:
    """Map a level name to its number, or None when it is not a level.

    Works across Python versions (``logging.getLevelNamesMapping`` is
    3.11+): ``getLevelName`` returns the number for a known name and the
    ``"Level N"`` string for an unknown one.
    """
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else None


class _CaptureQueueHandler(logging.handlers.QueueHandler):
    """Enqueues records after resolving thread/context-bound state.

    The message, exception text, and run id are materialized on the
    emitting thread (the run id lives in a contextvar the listener thread
    cannot see), so the record crosses the thread boundary as plain data.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        """Materialize message and exception text; strip live objects.

        Works on a copy: the original record is shared with every other
        handler in the same dispatch and must not be mutated. A record
        with mismatched ``%``-args would make ``getMessage`` raise; catch
        it and keep the raw template so this handler never routes a record
        into ``handleError`` (the ``--- Logging error ---`` banner).
        """
        record = copy.copy(record)
        try:
            record.message = record.getMessage()
        except Exception:
            record.message = str(record.msg)
        record.msg = record.message
        record.args = None
        if record.exc_info and not record.exc_text:
            with contextlib.suppress(Exception):
                record.exc_text = _EXC_FORMATTER.formatException(
                    record.exc_info
                )
        record.exc_info = None
        record.stack_info = None
        return record


class _StoreWriteHandler(logging.Handler):
    """Writes queued records to ``app_logs``; runs on the listener thread.

    Store failures are swallowed after a single stderr warning: log
    persistence must never raise into the logging call path, and a broken
    database would otherwise emit one warning per record.
    """

    def __init__(self, max_rows: int) -> None:
        """Remember the retention cap and reset the failure latch."""
        super().__init__()
        self._max_rows = max_rows
        self._writes = 0
        self._warned = False

    def emit(self, record: logging.LogRecord) -> None:
        """Persist one record, pruning every ``_PRUNE_EVERY`` writes."""
        try:
            store.append_log(
                level=record.levelname,
                levelno=record.levelno,
                logger_name=record.name,
                message=record.getMessage(),
                run_id=getattr(record, "run_id", None),
                exc_text=record.exc_text,
                created_at=record.created,
            )
            self._writes += 1
            if self._writes % _PRUNE_EVERY == 0:
                store.prune_logs(max_rows=self._max_rows)
        except Exception as exc:  # must never propagate into logging
            if not self._warned:
                self._warned = True
                print(
                    f"cosci: log capture write failed ({exc}); further "
                    "failures suppressed",
                    file=sys.stderr,
                )


class LogCapture:
    """Handle for one installed capture pipeline (handler + listener)."""

    def __init__(
        self,
        handler: _CaptureQueueHandler,
        listener: logging.handlers.QueueListener,
    ) -> None:
        """Keep the pieces needed to detach and drain the pipeline."""
        self._handler = handler
        self._listener = listener

    def stop(self) -> None:
        """Detach from the root logger and drain queued records."""
        logging.getLogger().removeHandler(self._handler)
        # QueueListener.stop() enqueues a sentinel and joins the writer
        # thread, so every record enqueued before this call is persisted.
        self._listener.stop()


_capture: LogCapture | None = None


def configure_log_capture(
    level: int = logging.INFO, max_rows: int = DEFAULT_LOG_MAX_ROWS
) -> LogCapture:
    """Persist root-logger records to the store; returns the pipeline handle.

    Idempotent: an existing pipeline is stopped (and drained) before the
    new one is installed, so reconfiguration never duplicates records.
    The database path is resolved by the store per write, so environment
    changes (tests, deployments) are honored without reconfiguring.

    Args:
        level: Minimum record level to persist.
        max_rows: Retention cap for the ``app_logs`` table.

    Returns:
        The installed :class:`LogCapture`; call ``stop()`` to detach.
    """
    global _capture
    shutdown_log_capture()
    with contextlib.suppress(Exception):
        # Trim any backlog from previous processes up front; routine
        # retention afterwards happens on the writer thread.
        store.prune_logs(max_rows=max_rows)
    record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    handler = _CaptureQueueHandler(record_queue)
    handler.setLevel(level)
    handler.addFilter(RunIdFilter())
    listener = logging.handlers.QueueListener(
        record_queue, _StoreWriteHandler(max_rows)
    )
    listener.start()
    logging.getLogger().addHandler(handler)
    _capture = LogCapture(handler, listener)
    return _capture


def shutdown_log_capture() -> None:
    """Stop and drain the active capture pipeline, if one is installed."""
    global _capture
    if _capture is not None:
        _capture.stop()
        _capture = None
