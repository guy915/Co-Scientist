"""Per-run bring-your-own-key credential scoping for LLM calls.

A run may execute under a caller-supplied provider key (BYOK). The key
must override the deployment credential for that run only -- never
process-wide (no env mutation, no module global) -- and it must never
enter the checkpointed workflow state, so it cannot ride along with the
model name the way other run configuration does.

Instead the key travels two ways, resolved together at the central
completion helpers (``llm.call_llm``, ``llm.call_llm_json``,
``llm.tools.loop.call_llm_with_tools``):

- Explicitly, on ``CompletionSpec.api_key`` for a single call.
- Scoped, via ``scoped_api_key`` around a block of run work. A
  ``contextvars.ContextVar`` is task-local state, not a process global:
  ``asyncio.run``/``create_task``/``gather`` each copy the active
  context, so one scope at the run boundary reaches every parallel
  agent call inside it while concurrent runs in the same process keep
  their own keys. This mirrors the ``cache.scoped_cache_override``
  pattern the engine already uses for per-generator cache toggles.
"""

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

__all__ = [
    "current_api_key",
    "scoped_api_key",
]

_byok_api_key: ContextVar[str | None] = ContextVar("byok_api_key", default=None)


def current_api_key() -> str | None:
    """Return the BYOK key scoped to the current task, if any.

    Returns:
        The key set by an enclosing ``scoped_api_key`` block, else None.
    """
    return _byok_api_key.get()


@contextlib.contextmanager
def scoped_api_key(api_key: str | None) -> Iterator[None]:
    """Scope a BYOK key to the current asyncio task for the block.

    Args:
        api_key: The provider key every completion inside the block
            should use, or None for a no-op scope (callers can pass an
            optional credential straight through).

    Yields:
        None.
    """
    if api_key is None:
        yield
        return
    token = _byok_api_key.set(api_key)
    try:
        yield
    finally:
        _byok_api_key.reset(token)
