"""The engine's fake completion backend, installed for an app test.

Not a test module (underscore prefix), so pytest does not collect it. An app
test that fakes what the *engine* asks a provider (``call_llm``,
``call_llm_json`` and everything built on them) installs a backend here
instead of assigning over ``litellm.acompletion``; the recording
``FakeBackend`` itself is the engine's (``engine/tests/_llm_fake.py``).

The same backend answers the app's streaming/plain-text provider calls.
Tests install it for interviews, Q&A, titles, announcements and probes as well
as scientific calls; admission and independent accounting still run.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import pytest

# Load the engine's LLM fake by file path: it lives under engine/tests, which
# is not importable as a package from the app's own ``tests`` namespace.
_ENGINE_FAKE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "_llm_fake.py"
)


def load_engine_fake() -> Any:
    """Load ``engine/tests/_llm_fake.py`` as a module.

    Returns:
        The module, exposing ``FakeBackend``, ``install_fake_backend`` and
        ``install_fake_llm``.
    """
    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", _ENGINE_FAKE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def install_completion_backend(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[..., Any],
    *,
    requests: list[dict[str, Any]] | None = None,
    supports_json_schema: Callable[[str], bool] | None = None,
) -> Any:
    """Answer every non-offline engine completion with ``respond``.

    Installs a ``FakeBackend`` behind the offline router, the order a real
    process has: an ``offline/`` model is still answered locally and
    ``respond`` sees every other model, as a patched ``litellm.acompletion``
    used to (the router passed those through to it). The previous backend
    comes back when the test ends.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        respond: Awaited with each request's keyword arguments; what it
            returns, or raises, is the provider's answer.
        requests: A list to record every request into; a test that wants
            them passes its own, or keeps the returned fake's ``requests``.
        supports_json_schema: The capability answer for any model; left out,
            the real default answer (profile, then litellm's registry).

    Returns:
        The installed ``FakeBackend``.
    """
    from co_scientist.llm.request import backend
    from co_scientist.offline.llm import OfflineRouter

    engine_fake = load_engine_fake()
    fake = engine_fake.FakeBackend(
        respond, requests=requests, supports_json_schema=supports_json_schema
    )
    engine_fake.restore_backend_at_teardown(monkeypatch)
    backend.install_backend(OfflineRouter(fake))
    return fake
