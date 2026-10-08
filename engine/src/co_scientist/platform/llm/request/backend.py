"""Worker threads share the process-global backend, without asyncio primitives.
Credentials remain task-local.
"""

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import litellm

from co_scientist.platform.llm.profile import model_profile


class CompletionBackend(Protocol):
    """The answering backend also determines the native response format."""

    async def complete(self, **completion_args: Any) -> Any: ...

    def supports_json_schema(self, model_name: str) -> bool: ...


def is_authentication_error(error: BaseException) -> bool:
    return isinstance(error, litellm.exceptions.AuthenticationError)


def litellm_supports_json_schema(model_name: str) -> bool:
    """Model capability is process-static; explicit profiles override
    unreliable registry answers.
    """
    stated = model_profile(model_name).json_schema
    if stated is not None:
        return stated
    return _registry_supports_json_schema(model_name)


@functools.cache
def _registry_supports_json_schema(model_name: str) -> bool:
    try:
        return bool(litellm.supports_response_schema(model=model_name))
    except Exception:
        return True


class LitellmBackend:
    async def complete(self, **completion_args: Any) -> Any:
        """Read the live LiteLLM attribute so existing patch paths still
        steer built requests.
        """
        return await litellm.acompletion(**completion_args)

    def supports_json_schema(self, model_name: str) -> bool:
        return litellm_supports_json_schema(model_name)


_LITELLM = LitellmBackend()

# None distinguishes no installed backend from an installed default-like
# backend.
_installed: CompletionBackend | None = None


def active_backend() -> CompletionBackend:
    return _LITELLM if _installed is None else _installed


def install_backend(
    backend: CompletionBackend | None,
) -> CompletionBackend | None:
    global _installed
    previous, _installed = _installed, backend
    return previous


@contextmanager
def using_backend(backend: CompletionBackend) -> Iterator[CompletionBackend]:
    previous = install_backend(backend)
    try:
        yield backend
    finally:
        install_backend(previous)
