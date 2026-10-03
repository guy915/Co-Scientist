"""One answer to "is this process offline, and can this model be called".

Two process facts decide whether the app may talk to a model provider at all:
whether the process is pinned to the deterministic offline backend, and whether
a credential exists for the model about to be called. They used to be read
through per-module wrappers whose only job was to be monkeypatched, so every
consumer re-stated the fact and the readers drifted apart (the offline probe
and the semantic safety screen answered "is this provider usable" from two
hand-kept provider tables until they disagreed). Here the question has one
interface and two adapters:

- :class:`EnvProcessMode`, the production adapter, derives both facts from the
  environment at call time.
- A test adapter, installed with :func:`install`, states them outright (see
  ``tests/conftest.py``'s ``fake_process_mode``).

The module is a leaf (``os`` and ``app.config`` only) so ``app.safety`` and
``app.engine_adapter`` can both import it eagerly; the engine-adapter package
cannot be imported from ``app.safety`` without a cycle.
"""

from __future__ import annotations

import os
from typing import Protocol

from app.config import any_provider_credential, has_provider_credential

__all__ = [
    "EnvProcessMode",
    "ProcessMode",
    "credential_available",
    "install",
    "offline_mode",
]


class ProcessMode(Protocol):
    """The process facts the app consults before reaching a model provider."""

    def is_offline(self) -> bool:
        """Return whether every model call is pinned to the offline backend."""
        ...

    def credential_available(self, model: str) -> bool:
        """Return whether a call to ``model`` has a credential to use."""
        ...


class EnvProcessMode:
    """Production adapter: both facts are read from the environment per call."""

    def is_offline(self) -> bool:
        """Return whether this process runs against the offline LLM backend.

        True when offline execution is forced (``COSCIENTIST_FORCE_OFFLINE=1``,
        or its deprecated alias ``COSCIENTIST_FORCE_MOCK=1``) or when no
        provider credential is configured. Any single credential is enough to
        attempt a real run; which model is used is a separate question
        (``settings.model_name`` and friends). A forced-offline or keyless
        process is a deployment mode, not a control that failed. A *partially*
        configured one -- holding a credential for some provider but not a
        given model's -- is not offline, so ``credential_available`` is what
        makes its callers refuse.
        """
        if os.getenv("COSCIENTIST_FORCE_OFFLINE") == "1":
            return True
        if os.getenv("COSCIENTIST_FORCE_MOCK") == "1":
            return True  # deprecated alias, retained for backward compatibility
        return not any_provider_credential()

    def credential_available(self, model: str) -> bool:
        """Return whether ``model``'s provider has a usable credential.

        Answers from ``config.PROVIDER_CREDENTIAL_ENV`` rather than carrying a
        provider table of its own: a provider missing from a private copy does
        not raise, it reads as a screen that was configured and never won. A
        scoped bring-your-own-key credential also counts, so a BYOK run
        screens on its own key even when the deployment has none.
        """
        # Imported on use so this module stays importable from config alone.
        from app import credentials

        return (
            credentials.current_byok() is not None
            or has_provider_credential(model)
        )


_current: ProcessMode = EnvProcessMode()


def install(mode: ProcessMode) -> ProcessMode:
    """Make ``mode`` the active adapter and return the one it replaced.

    The single place the active adapter is looked up at call time, so a test
    states a process fact once instead of patching each consumer module.
    Callers restore the returned adapter when they are done.
    """
    global _current
    previous, _current = _current, mode
    return previous


def offline_mode() -> bool:
    """Return whether this process runs against the offline LLM backend.

    A process-level, request-time predicate: use it to decide a *new* run's
    backend, never to infer a *past* run's backend (use
    ``store.run_used_offline`` for that -- see the note in
    ``engine_adapter.select_provider``).
    """
    return _current.is_offline()


def credential_available(model: str) -> bool:
    """Return whether a call to ``model`` has a credential to use."""
    return _current.credential_available(model)
