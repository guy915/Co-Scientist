"""Empty results can mean a failed source or no matches; per-call logging
distinguishes them.
"""

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Bound logged query text without dropping the clue explaining empty results.
_MAX_ARG_CHARS = 160


def _describe_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
    rendered = ", ".join(parts)
    if len(rendered) > _MAX_ARG_CHARS:
        return rendered[:_MAX_ARG_CHARS] + "..."
    return rendered


def _describe_result(result: Any) -> str:
    parsed: Any = result
    size = None
    if isinstance(result, str):
        size = len(result)
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return f"{size} chars"
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
        return f"failed ({parsed['error'].get('kind')})"
    if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
        parsed = parsed["records"]
    if isinstance(parsed, (dict, list)):
        count = len(parsed)
        detail = f"{count} item{'' if count == 1 else 's'}"
        if not count:
            detail = "empty"
        return detail if size is None else f"{detail}, {size} chars"
    return f"{parsed!r}"


def _log_success(name: str, described: str, result: Any, started: float) -> None:
    logger.info(
        "tool %s(%s) -> %s in %dms",
        name,
        described,
        _describe_result(result),
        int((time.monotonic() - started) * 1000),
    )


def _log_failure(name: str, described: str, exc: BaseException, started: float) -> None:
    """Tools normally degrade; unexpected exceptions retain their diagnostic
    traceback.
    """
    logger.exception(
        "tool %s(%s) raised %s after %dms",
        name,
        described,
        type(exc).__name__,
        int((time.monotonic() - started) * 1000),
    )


def _wrap_async(fn: Callable[..., Any], name: str) -> Callable[..., Any]:

    @functools.wraps(fn)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        described = _describe_args(args, kwargs)
        try:
            result = await fn(*args, **kwargs)
        except BaseException as exc:
            _log_failure(name, described, exc, started)
            raise
        _log_success(name, described, result, started)
        return result

    signature = inspect.signature(fn)
    async_wrapper.__signature__ = signature  # type: ignore[attr-defined]
    return async_wrapper


def _wrap_sync(fn: Callable[..., Any], name: str) -> Callable[..., Any]:

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        described = _describe_args(args, kwargs)
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            _log_failure(name, described, exc, started)
            raise
        _log_success(name, described, result, started)
        return result

    signature = inspect.signature(fn)
    sync_wrapper.__signature__ = signature  # type: ignore[attr-defined]
    return sync_wrapper


def with_call_logging(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    """FastMCP reads wrapped docs and signatures; losing metadata erases tool
    descriptions and parameters.
    """
    if inspect.iscoroutinefunction(fn):
        return _wrap_async(fn, name)
    return _wrap_sync(fn, name)
