from __future__ import annotations

import contextlib
import copy
import json
import logging
import logging.handlers
import queue
import sys
import threading
from collections.abc import Generator
from contextvars import ContextVar

from app.store import logs as store
from app.store.logs import NewLogRecord

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
    """LiteLLM's own logger handlers bypass root levels; its provider banner
    is a separate print guarded by suppress_debug_info.
    """
    for name in _LITELLM_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        import litellm
    except ImportError:
        return
    litellm.suppress_debug_info = True


silence_litellm_logging()


def _byok_redaction_filter() -> logging.Filter:
    """Lazy import avoids pulling credential cryptography into logging-only
    processes; provider errors still need redaction.
    """
    from app.credentials import ByokRedactionFilter

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


_PRUNE_EVERY = 500

DEFAULT_LOG_MAX_ROWS = 20_000

_EXC_FORMATTER = logging.Formatter()


def level_to_number(name: str) -> int | None:
    """getLevelNamesMapping is Python 3.11+; getLevelName also distinguishes
    unknown names on older interpreters.
    """
    value = logging.getLevelName(name.upper())
    return value if isinstance(value, int) else None


class _CaptureQueueHandler(logging.handlers.QueueHandler):
    """Materialize message, exception and run context on the emitting thread
    before the listener crosses that boundary.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "_cosci_captured", False):
            return
        record._cosci_captured = True
        super().emit(record)

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        """Copy shared records before materialization; malformed logging
        arguments must not break capture.
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
                record.exc_text = _EXC_FORMATTER.formatException(record.exc_info)
        record.exc_info = None
        record.stack_info = None
        return record


class _StoreWriteHandler(logging.Handler):
    """Persistence failures must not enter the logging path; warn once
    rather than creating another record per failure.
    """

    def __init__(self, max_rows: int) -> None:
        super().__init__()
        self._max_rows = max_rows
        self._writes = 0
        self._warned = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            store.append_log(
                NewLogRecord(
                    level=record.levelname,
                    levelno=record.levelno,
                    logger_name=record.name,
                    message=record.getMessage(),
                    run_id=getattr(record, "run_id", None),
                    exc_text=record.exc_text,
                    created_at=record.created,
                    client_id=getattr(record, "client_id", None),
                )
            )
            self._writes += 1
            if self._writes % _PRUNE_EVERY == 0:
                store.prune_logs(max_rows=self._max_rows)
        except Exception as exc:  # must never propagate into logging
            if not self._warned:
                self._warned = True
                print(
                    f"cosci: log capture write failed ({exc}); further failures suppressed",
                    file=sys.stderr,
                )


# Attach directly to uvicorn's non-propagating loggers so access and server
# errors persist.
_EXTRA_CAPTURE_LOGGERS = ("uvicorn", "uvicorn.access")


# Discard per-call chatter before it starves SQLite's writer; read-time verbose
# filtering is separate.
UNPERSISTED_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "urllib3",
    "litellm",
    "openai",
    "mcp.client",
    # Availability warnings remain visible even when ordinary dependency chatter
    # is dropped.
    "co_scientist.mcp_client",
)


def _drop_dependency_chatter(record: logging.LogRecord) -> bool:
    """Logger names and children vary in casing, including LiteLLM and MCP
    transport modules.
    """
    if record.levelno >= logging.WARNING:
        return True
    name = record.name.lower()
    return not any(name == noise or name.startswith(f"{noise}.") for noise in UNPERSISTED_LOGGERS)


# Periodic resurfacing preserves ongoing-condition visibility without filling
# the bounded log window.
REPEAT_SUPPRESS_SECONDS = 600.0

# Bound repeat history even when messages never repeat.
_REPEAT_KEYS_MAX = 2_000


class _RepeatSuppressor:
    """Suppress exact repeats before writes so steady warnings cannot crowd
    real records out of the bounded log window.
    """

    def __init__(self, window: float = REPEAT_SUPPRESS_SECONDS) -> None:
        self._window = window
        self._seen: dict[tuple[str, int, str | None, str], float] = {}
        self._lock = threading.Lock()

    def __call__(self, record: logging.LogRecord) -> bool:
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
        """Bound suppression history even when every key is unique and
        nothing has yet expired.
        """
        self._seen = {key: seen for key, seen in self._seen.items() if now - seen < self._window}
        if len(self._seen) >= _REPEAT_KEYS_MAX:
            self._seen.clear()


# Match both LiteLLM-worker clues so orphaned dependency tasks are filtered
# without hiding genuine application task leaks.
_ORPHANED_WORKER_MARKERS = (
    "Task was destroyed but it is pending",
    "LoggingWorker._worker_loop",
)


def _drop_orphaned_logging_worker_noise(record: logging.LogRecord) -> bool:
    """Orphaned library logging workers remain visible on stdout, without
    being attributed as scientific run errors.
    """
    if record.name != "asyncio":
        return True
    try:
        message = record.getMessage()
    except Exception:
        return True
    return not all(marker in message for marker in _ORPHANED_WORKER_MARKERS)


def _drop_self_noise(record: logging.LogRecord) -> bool:
    # Polling logs must not grow them through their own access records.
    if record.name != "uvicorn.access":
        return True
    try:
        return "/api/logs" not in record.getMessage()
    except Exception:
        return True


class LogCapture:
    def __init__(
        self,
        handler: _CaptureQueueHandler,
        listener: logging.handlers.QueueListener,
    ) -> None:
        self._handler = handler
        self._listener = listener
        self._stopped = False

    def stop(self) -> None:
        """QueueListener.stop is not idempotent, but explicit shutdown and
        reconfiguration can both stop the same pipeline.
        """
        if self._stopped:
            return
        self._stopped = True
        logging.getLogger().removeHandler(self._handler)
        for name in _EXTRA_CAPTURE_LOGGERS:
            logging.getLogger(name).removeHandler(self._handler)
        # QueueListener.stop drains queued records before joining its writer
        # thread.
        self._listener.stop()


_capture: LogCapture | None = None


def _build_capture_pipeline(
    level: int, max_rows: int
) -> tuple[_CaptureQueueHandler, logging.handlers.QueueListener]:
    record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    handler = _CaptureQueueHandler(record_queue)
    handler.setLevel(level)
    handler.addFilter(RunIdFilter())
    handler.addFilter(_byok_redaction_filter())
    handler.addFilter(_drop_self_noise)
    handler.addFilter(_drop_dependency_chatter)
    handler.addFilter(_drop_orphaned_logging_worker_noise)
    # Suppress repeats after stamping run IDs because run identity belongs in
    # the suppression key.
    handler.addFilter(_RepeatSuppressor())
    listener = logging.handlers.QueueListener(record_queue, _StoreWriteHandler(max_rows))
    return handler, listener


def _attach_capture_handler(handler: _CaptureQueueHandler) -> None:
    logging.getLogger().addHandler(handler)
    # Shared record marks prevent duplicate capture when directly attached
    # uvicorn loggers also propagate.
    for name in _EXTRA_CAPTURE_LOGGERS:
        logging.getLogger(name).addHandler(handler)


def configure_log_capture(
    level: int = logging.INFO, max_rows: int = DEFAULT_LOG_MAX_ROWS
) -> LogCapture:
    """Drain and detach the previous pipeline before replacing it; repeated
    setup must never duplicate records.
    """
    global _capture
    shutdown_log_capture()
    with contextlib.suppress(Exception):
        # Prune prior-process backlog once; routine retention runs on the writer
        # thread.
        store.prune_logs(max_rows=max_rows)
    handler, listener = _build_capture_pipeline(level, max_rows)
    listener.start()
    _attach_capture_handler(handler)
    _capture = LogCapture(handler, listener)
    return _capture


def shutdown_log_capture() -> None:
    global _capture
    if _capture is not None:
        _capture.stop()
        _capture = None


__all__ = ["run_log_context", "silence_litellm_logging"]
