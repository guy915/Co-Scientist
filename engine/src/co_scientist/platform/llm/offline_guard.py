from __future__ import annotations

from co_scientist.core import byok_scope
from co_scientist.orchestration import engine_adapter

__all__ = ["OfflineModeError", "remote_chat_allowed", "require_remote_chat"]


class OfflineModeError(RuntimeError):
    """An app-side provider request was refused by forced offline admission."""


def remote_chat_allowed() -> bool:
    """Forced offline withholds deployment credentials; explicitly scoped
    validated BYOK credentials remain caller-authorized.
    """
    if byok_scope.current_byok() is not None:
        return True
    return not engine_adapter.offline_mode()


def require_remote_chat(caller: str) -> None:
    if remote_chat_allowed():
        return
    raise OfflineModeError(
        f"{caller} is not calling a provider: this process runs offline "
        f"(COSCIENTIST_FORCE_OFFLINE, or no provider credential)"
    )
