"""Uniform per-call logging for every registered MCP tool.

Before this, the server's only record of a tool call was uvicorn's access
line -- `POST /mcp 200 OK` -- which says a request arrived and nothing about
what it did. A run that called a tool ten times and a run that called ten
different tools once each produced identical logs, so the questions you
actually ask of this service could not be answered: which tool did the agent
choose, what did it search for, did it find anything, and how long did it
take.

The gap mattered most for empty results. Every tool here degrades to an empty
result rather than raising -- a failed HTTP call, a missing API key, and a
query that genuinely matched nothing all return `{}` -- so from the outside
they are indistinguishable. Logging the outcome separates them.

Wrapping happens once, in the registration loop, so the behaviour cannot
drift between tools or be forgotten when a tool is added.
"""

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Arguments are logged to explain why a call returned what it did, so a long
# query is truncated rather than dropped.
_MAX_ARG_CHARS = 160


def _describe_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Render call arguments compactly for one log line."""
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
    rendered = ", ".join(parts)
    if len(rendered) > _MAX_ARG_CHARS:
        return rendered[:_MAX_ARG_CHARS] + "..."
    return rendered


def _describe_result(result: Any) -> str:
    """Summarise a tool result as a count plus a size.

    Tools return either a JSON string or a dict, and callers care about how
    many items came back rather than their content. An explicit "empty" is
    the point of the exercise: it is the signature of a degraded call.
    """
    parsed: Any = result
    size = None
    if isinstance(result, str):
        size = len(result)
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return f"{size} chars"
    if isinstance(parsed, (dict, list)):
        count = len(parsed)
        detail = f"{count} item{'' if count == 1 else 's'}"
        if not count:
            detail = "empty"
        return detail if size is None else f"{detail}, {size} chars"
    return f"{parsed!r}"


def _log_success(
    name: str, described: str, result: Any, started: float
) -> None:
    """Emit the one-line record of a completed call."""
    logger.info(
        "tool %s(%s) -> %s in %dms",
        name,
        described,
        _describe_result(result),
        int((time.monotonic() - started) * 1000),
    )


def _log_failure(
    name: str, described: str, exc: BaseException, started: float
) -> None:
    """Emit the one-line record of a call that raised.

    Logged at exception level so the traceback survives: a tool raising is
    unexpected here, since these tools are written to degrade instead.
    """
    logger.exception(
        "tool %s(%s) raised %s after %dms",
        name,
        described,
        type(exc).__name__,
        int((time.monotonic() - started) * 1000),
    )


def _wrap_async(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    """Build the logging wrapper for an asynchronous tool.

    Args:
        fn: The asynchronous tool function.
        name: The name the tool is registered under.

    Returns:
        An async wrapper carrying the wrapped function's signature.
    """

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

    async_wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return async_wrapper


def _wrap_sync(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    """Build the logging wrapper for a synchronous tool.

    Args:
        fn: The synchronous tool function.
        name: The name the tool is registered under.

    Returns:
        A sync wrapper carrying the wrapped function's signature.
    """

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

    sync_wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return sync_wrapper


def with_call_logging(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    """Wrap one tool so every call logs its name, arguments, and outcome.

    The wrapper preserves the wrapped function's signature and annotations,
    which FastMCP reads to build the tool's advertised parameter schema --
    a bare `*args, **kwargs` wrapper would erase every parameter from the
    schema the agent sees.

    Args:
        fn: The tool function, synchronous or asynchronous.
        name: The name the tool is registered under.

    Returns:
        A wrapper of the same kind (async for async, sync for sync).
    """
    if inspect.iscoroutinefunction(fn):
        return _wrap_async(fn, name)
    return _wrap_sync(fn, name)
