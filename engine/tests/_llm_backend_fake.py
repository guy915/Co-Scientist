"""The recording fake adapter for the completion backend seam.

Every engine completion is awaited through one installed backend
(``co_scientist.llm.request.backend``), so a test that needs to stand in for
the provider installs one fake there instead of assigning over
``litellm.acompletion``. ``FakeBackend`` answers each request with a
caller-supplied coroutine function, records what it was sent, and gives the
capability answer ("does this model take a native json_schema response
format") either from the test or, by default, from the real default backend.

``install_fake_backend`` installs it for one test and puts the previous
backend back when the test ends; ``restore_backend_at_teardown`` is that
restoring on its own, for helpers that install a backend some other way (the
offline router).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from co_scientist.llm.request import backend

Respond = Callable[..., Awaitable[Any]]


class FakeBackend:
    """Answers completions from a test's own coroutine function.

    Attributes:
        requests: The keyword arguments of every request, in order.
    """

    def __init__(
        self,
        respond: Respond,
        *,
        requests: list[dict[str, Any]] | None = None,
        supports_json_schema: Callable[[str], bool] | None = None,
    ) -> None:
        """Builds the fake.

        Args:
            respond: Awaited with each request's keyword arguments; what it
                returns (or raises) is the provider's answer.
            requests: A list to record into, when the test already holds one;
                otherwise a fresh one.
            supports_json_schema: The capability answer for any model; left
                out, the real default answer (profile, then litellm's
                registry) is used.
        """
        self._respond = respond
        self.requests: list[dict[str, Any]] = (
            [] if requests is None else requests
        )
        self._supports = supports_json_schema

    async def complete(self, **completion_args: Any) -> Any:
        """Records the request, then answers it."""
        self.requests.append(completion_args)
        return await self._respond(**completion_args)

    def supports_json_schema(self, model_name: str) -> bool:
        """Answers from the test when it gave an answer, else the default."""
        if self._supports is not None:
            return self._supports(model_name)
        return backend.litellm_supports_json_schema(model_name)


def restore_backend_at_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Puts back, when the test ends, whichever backend is installed now.

    Recording the current value with ``monkeypatch`` (even when set to
    itself) registers it for restoration; this is the one place a test
    reaches the registry's slot.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(backend, "_installed", backend._installed)


def install_fake_backend(
    monkeypatch: pytest.MonkeyPatch,
    respond: Respond,
    *,
    requests: list[dict[str, Any]] | None = None,
    supports_json_schema: Callable[[str], bool] | None = None,
) -> FakeBackend:
    """Installs a ``FakeBackend`` for the rest of the test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        respond: Awaited with each request's keyword arguments.
        requests: A list to record into, when the test already holds one.
        supports_json_schema: The capability answer for any model; left out,
            the real default answer is used.

    Returns:
        The installed fake, for the test to inspect.
    """
    fake = FakeBackend(
        respond, requests=requests, supports_json_schema=supports_json_schema
    )
    restore_backend_at_teardown(monkeypatch)
    backend.install_backend(fake)
    return fake
