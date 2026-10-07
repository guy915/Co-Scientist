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
    def is_offline(self) -> bool:
        """A partially configured deployment is real-backed; individual
        calls still require their own provider credential.
        """
        ...

    def credential_available(self, model: str) -> bool:
        """The shared provider table avoids drifting private copies; scoped
        BYOK also authorizes its own provider.
        """
        ...


class EnvProcessMode:
    def is_offline(self) -> bool:
        """A partially configured deployment is real-backed; individual
        calls still require their own provider credential.
        """
        if os.getenv("COSCIENTIST_FORCE_OFFLINE") == "1":
            return True
        return not any_provider_credential()

    def credential_available(self, model: str) -> bool:
        """The shared provider table avoids drifting private copies; scoped
        BYOK also authorizes its own provider.
        """
        # Import lazily so this leaf stays available from config without
        # credential-module cycles.
        from app import credentials

        return credentials.current_byok() is not None or has_provider_credential(model)


_current: ProcessMode = EnvProcessMode()


def install(mode: ProcessMode) -> ProcessMode:
    """Call-time adapter lookup lets tests state one process fact; callers
    restore the replaced adapter after use.
    """
    global _current
    previous, _current = _current, mode
    return previous


def offline_mode() -> bool:
    """Use current process mode only for new execution, never to infer
    historical backend provenance.
    """
    return _current.is_offline()


def credential_available(model: str) -> bool:
    """The shared provider table avoids drifting private copies; scoped BYOK
    also authorizes its own provider.
    """
    return _current.credential_available(model)
