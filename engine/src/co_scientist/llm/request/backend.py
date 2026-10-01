"""The provider call, behind one named seam.

Every engine completion is awaited through
``llm.request.completion._acompletion_within_timeout``: admission, the call
budget, the timeout ceiling and telemetry wrap exactly one
``CompletionBackend.complete``. What answers that call -- and what the
backend says about a model's native-schema support, which decides how the
request was built in the first place -- is chosen here, once, rather than by
assigning over ``litellm.acompletion`` from outside.

Three adapters exist:

* ``LitellmBackend``, the default: the live ``litellm.acompletion`` module
  attribute, looked up on every call. Reading it late is deliberate: the
  string path ``"co_scientist.llm.litellm.acompletion"`` resolves to that
  same attribute, so a test (or any caller) that patches it still steers a
  call that is already built.
* ``co_scientist.offline.llm.OfflineRouter``, which answers ``offline/``
  models locally and hands every other model to the backend it replaced.
* the recording fake in ``tests/_llm_fake.py``.

The registry is one module global, not a ``ContextVar``. The offline router is
installed once, at process start, for every caller, and the worker cohorts run
on their own threads and event loops (``docs/OPERATIONS.md``), where a context
set elsewhere is only as visible as the way each thread was started. It holds
no asyncio primitive either, since those cannot be shared between the cohorts'
loops. A test that wants the opposite, a backend for its own duration, uses
``using_backend``.

The capability answer reaches the call in two places and they are not the
same place. ``llm.request.schema`` asks the *active backend* at call time, so
an installed backend steers which response format a call is built with.
``llm.attempts.json_attempt`` binds ``litellm_supports_json_schema`` -- the
default answer -- at import, so the validation shim that repairs a downgraded
response never sees an installed backend. Both behaviours predate this
module and ``tests/test_llm_completion_routing.py`` pins them.
"""

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import litellm

from co_scientist.llm.profile import model_profile


class CompletionBackend(Protocol):
    """Whatever answers one built completion request.

    Both operations are about the same provider, which is why they travel
    together: a backend that answers a model's calls is the one that knows
    whether that model takes a native ``json_schema`` response format.
    """

    async def complete(self, **completion_args: Any) -> Any:
        """Answers one request.

        Args:
            **completion_args: The keyword arguments ``litellm.acompletion``
                takes (model, messages, response_format, ...).

        Returns:
            A litellm-shaped response.
        """
        ...

    def supports_json_schema(self, model_name: str) -> bool:
        """Says whether a model accepts the ``json_schema`` response format.

        Args:
            model_name: Model name in litellm format.

        Returns:
            True when requests to it may carry a native schema.
        """
        ...


@functools.cache
def litellm_supports_json_schema(model_name: str) -> bool:
    """Checks whether a model accepts the json_schema response format.

    The result is a process-static property of the model, so it is cached to
    avoid re-running litellm's registry lookup on every LLM call and retry.
    A profile that states the answer (``ModelProfile.json_schema``) decides
    before the registry does; see that field for why the registry cannot be
    trusted for the models that state one.

    Args:
        model_name: Model name in litellm format.

    Returns:
        The profile's stated answer when it has one -- False for a
        json_object-only family or a declared OpenRouter gateway model
        without a proven native-schema endpoint, True for an exact route
        with one -- else whether litellm's capability registry reports
        json_schema support. True when the registry lookup itself raises,
        so the default json_schema path is preserved for unknown models.
    """
    stated = model_profile(model_name).json_schema
    if stated is not None:
        return stated
    try:
        return bool(litellm.supports_response_schema(model=model_name))
    except Exception:
        return True


class LitellmBackend:
    """The real provider, through whatever ``litellm.acompletion`` is now."""

    async def complete(self, **completion_args: Any) -> Any:
        """Awaits ``litellm.acompletion``, read from the module at call time."""
        return await litellm.acompletion(**completion_args)

    def supports_json_schema(self, model_name: str) -> bool:
        """Answers from the profile, then litellm's registry (cached)."""
        return litellm_supports_json_schema(model_name)


_LITELLM = LitellmBackend()

# ``None`` means the default. Kept as an override rather than a pre-filled slot
# so that "nothing installed" stays distinguishable, and restorable, from
# "something that behaves like the default is installed".
_installed: CompletionBackend | None = None


def active_backend() -> CompletionBackend:
    """Returns the backend that answers completions right now.

    Returns:
        The installed backend, or the litellm default when none is.
    """
    return _LITELLM if _installed is None else _installed


def install_backend(
    backend: CompletionBackend | None,
) -> CompletionBackend | None:
    """Makes a backend answer every completion, process-wide.

    Args:
        backend: The backend to install, or None to go back to the default.

    Returns:
        What was installed before (None for the default), to hand back to
        this function to restore it.
    """
    global _installed
    previous, _installed = _installed, backend
    return previous


@contextmanager
def using_backend(backend: CompletionBackend) -> Iterator[CompletionBackend]:
    """Installs a backend for the duration of a ``with`` block.

    Args:
        backend: The backend to install.

    Yields:
        The backend, for the caller to inspect.
    """
    previous = install_backend(backend)
    try:
        yield backend
    finally:
        install_backend(previous)
