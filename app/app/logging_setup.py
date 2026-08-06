"""Application logging: configurable format, run-id correlation, capture.

Configures the root logger once at startup (``configure_logging``) with
either the default human-readable text format or one JSON object per
line, both on stdout. Run-id correlation and the record formatters live
in ``app.logging_format`` (re-exported here, so this module stays the
stable import surface).

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
import logging
import logging.handlers
import queue
import sys
import threading

from app import store
from app.logging_format import (
    TEXT_FORMAT as TEXT_FORMAT,
)
from app.logging_format import (
    JsonFormatter as JsonFormatter,
)
from app.logging_format import (
    RunIdFilter as RunIdFilter,
)
from app.logging_format import (
    TextRunIdFormatter as TextRunIdFormatter,
)
from app.logging_format import (
    _build_formatter as _build_formatter,
)
from app.logging_format import (
    current_run_id as current_run_id,
)
from app.logging_format import (
    run_log_context as run_log_context,
)


def _byok_redaction_filter() -> logging.Filter:
    """Return the filter that scrubs a scoped BYOK key from records.

    Defense in depth for bring-your-own-key runs: no code path logs the
    key deliberately, but a provider error message could embed it. Kept
    behind a lazy import so this module never drags credentials (and its
    cryptography imports) into processes that only configure logging.
    """
    from app.credentials import ByokRedactionFilter

    return ByokRedactionFilter()


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
    handler.addFilter(_byok_redaction_filter())
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

    def emit(self, record: logging.LogRecord) -> None:
        """Enqueue the record once, even when attached at several loggers.

        The handler is attached to root *and* uvicorn's loggers; when a
        record propagates through the hierarchy (dev/test setups where
        uvicorn's production logging config is absent), every attachment
        point would enqueue it. Mark the shared record object so only the
        first attachment wins.
        """
        if getattr(record, "_cosci_captured", False):
            return
        record._cosci_captured = True
        super().emit(record)

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
                store.NewLogRecord(
                    level=record.levelname,
                    levelno=record.levelno,
                    logger_name=record.name,
                    message=record.getMessage(),
                    run_id=getattr(record, "run_id", None),
                    exc_text=record.exc_text,
                    created_at=record.created,
                )
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


# Loggers uvicorn configures with propagate=False in production; the
# capture handler is attached to them directly so HTTP access/error logs
# persist too. "uvicorn.error" propagates to "uvicorn", so listing it is
# unnecessary.
_EXTRA_CAPTURE_LOGGERS = ("uvicorn", "uvicorn.access")


# Third-party libraries whose INFO output is per-call chatter and is never
# read: two lines per LLM call, one per MCP request, one per HTTP call.
# Persisting them is not free -- in production they were 72% of the table
# (LiteLLM alone 9,928 of 20,021 rows), each an open-write-close against a
# database with a single writer and no fair queuing, and that stream
# starved ordinary API writes until creating a run failed with "database
# is locked".
#
# Deliberately narrower than the read path's NOISE_LOGGERS: uvicorn.access
# and the ui.* loggers are merely *hidden* by default and stay persisted,
# because `cosci logs --all` is documented as the way to debug request- and
# interaction-level behaviour. This drops only records nothing can ask for.
# WARNING and above always persists -- that is a dependency in trouble.
UNPERSISTED_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "urllib3",
    "litellm",
    "openai",
    "mcp.client",
    # Availability probes repeat on every /status poll; their WARNINGs
    # (e.g. "MCP server unavailable") still surface.
    "co_scientist.mcp_client",
)


def _drop_dependency_chatter(record: logging.LogRecord) -> bool:
    """Keep per-call dependency records out of the database.

    Matches a logger and its children, case-insensitively: the LiteLLM
    logger names itself "LiteLLM", and MCP's client logs under
    "mcp.client.streamable_http".
    """
    if record.levelno >= logging.WARNING:
        return True
    name = record.name.lower()
    return not any(
        name == noise or name.startswith(f"{noise}.")
        for noise in UNPERSISTED_LOGGERS
    )


# How long a verbatim repeat stays suppressed. Long enough that a
# steady-state condition is a footnote rather than the whole log, short
# enough that "this is still true" resurfaces within a working session.
REPEAT_SUPPRESS_SECONDS = 600.0

# Cap on remembered (logger, level, run, message) keys, so a process
# emitting endlessly varied messages cannot grow this without bound.
_REPEAT_KEYS_MAX = 2_000


class _RepeatSuppressor:
    """Persists the first of a repeating record and drops its echoes.

    A condition that is both expected and unchanging -- an availability
    probe reporting the same unreachable server on every poll -- would
    otherwise write a row per probe forever. Because the level filters
    deliberately exempt WARNING and above, that stream is never dropped,
    and on an idle app it is the only thing that grows: the Logs panel
    shows a fixed newest-N window, so the repeated message eventually
    crowds out every real record and the log reads as empty.

    Suppression is by exact ``(logger, level, run id, message)``: the
    first occurrence always persists, a *different* message from the same
    logger is its own condition, and two runs emitting the same line stay
    separately visible. This is the standard "last message repeated"
    behaviour, applied at capture so the database never takes the write.
    """

    def __init__(self, window: float = REPEAT_SUPPRESS_SECONDS) -> None:
        """Start with an empty history over a ``window``-second memory."""
        self._window = window
        self._seen: dict[tuple[str, int, str | None, str], float] = {}
        self._lock = threading.Lock()

    def __call__(self, record: logging.LogRecord) -> bool:
        """Keep the record unless an identical one is still in the window."""
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        key = (
            record.name,
            record.levelno,
            getattr(record, "run_id", None),
            message,
        )
        now = record.created
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < self._window:
                return False
            if len(self._seen) >= _REPEAT_KEYS_MAX:
                self._prune(now)
            self._seen[key] = now
        return True

    def _prune(self, now: float) -> None:
        """Forget keys past the window; clear outright if none have aged.

        Called with the lock held. The fallback matters: a burst of
        unique messages inside one window would leave nothing to expire,
        and an unbounded dict is worse than a forgotten history.
        """
        self._seen = {
            key: seen
            for key, seen in self._seen.items()
            if now - seen < self._window
        }
        if len(self._seen) >= _REPEAT_KEYS_MAX:
            self._seen.clear()


def _drop_self_noise(record: logging.LogRecord) -> bool:
    """Filter out access records for the log-polling endpoint itself.

    The UI and ``cosci logs --follow`` poll ``/api/logs``; persisting each
    poll's access line would make the log grow by being looked at.
    """
    if record.name != "uvicorn.access":
        return True
    try:
        return "/api/logs" not in record.getMessage()
    except Exception:
        return True


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
        self._stopped = False

    def stop(self) -> None:
        """Detach from every attached logger and drain queued records.

        Idempotent: ``QueueListener.stop`` drops its thread reference and
        raises if called twice, and a pipeline can legitimately be stopped
        both explicitly and again by ``shutdown_log_capture``.
        """
        if self._stopped:
            return
        self._stopped = True
        logging.getLogger().removeHandler(self._handler)
        for name in _EXTRA_CAPTURE_LOGGERS:
            logging.getLogger(name).removeHandler(self._handler)
        # QueueListener.stop() enqueues a sentinel and joins the writer
        # thread, so every record enqueued before this call is persisted.
        self._listener.stop()


_capture: LogCapture | None = None


def _build_capture_pipeline(
    level: int, max_rows: int
) -> tuple[_CaptureQueueHandler, logging.handlers.QueueListener]:
    """Build the capture queue handler and its background writer listener."""
    record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    handler = _CaptureQueueHandler(record_queue)
    handler.setLevel(level)
    handler.addFilter(RunIdFilter())
    handler.addFilter(_byok_redaction_filter())
    handler.addFilter(_drop_self_noise)
    handler.addFilter(_drop_dependency_chatter)
    # Last in the chain, and after RunIdFilter: the key it builds includes
    # the run id that filter stamps on.
    handler.addFilter(_RepeatSuppressor())
    listener = logging.handlers.QueueListener(
        record_queue, _StoreWriteHandler(max_rows)
    )
    return handler, listener


def _attach_capture_handler(handler: _CaptureQueueHandler) -> None:
    """Attach the capture handler to the root logger and extra loggers."""
    logging.getLogger().addHandler(handler)
    # Also attach to uvicorn's non-propagating loggers so HTTP access and
    # server-error records persist. Where those loggers DO propagate
    # (dev/test without uvicorn's logging config), the handler's per-record
    # dedupe mark keeps each record captured exactly once.
    for name in _EXTRA_CAPTURE_LOGGERS:
        logging.getLogger(name).addHandler(handler)


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
    handler, listener = _build_capture_pipeline(level, max_rows)
    listener.start()
    _attach_capture_handler(handler)
    _capture = LogCapture(handler, listener)
    return _capture


def shutdown_log_capture() -> None:
    """Stop and drain the active capture pipeline, if one is installed."""
    global _capture
    if _capture is not None:
        _capture.stop()
        _capture = None
