"""One gate over the app's own direct-to-provider chat completions.

The engine's deterministic router intercepts ``litellm.acompletion`` only for
``offline/``-prefixed models, so it covers engine runs and nothing else. The
three app-side calls that reach litellm with a *deployment* model -- the goal
interview, run Q&A, and run titling -- pass straight through it, which is why
``COSCIENTIST_FORCE_OFFLINE=1`` on a host that also has a provider key set
used to send the scientist's research goal to that provider anyway.

The switch means "this process makes no external model request", so the check
belongs at each call site, immediately before the request, rather than at one
caller that happens to remember it. A refusal is raised, not returned: every
one of the three sites already has a failure branch that degrades to its own
deterministic answer, so raising reuses the path that was built for an absent
provider instead of adding a second one.

A scoped bring-your-own-key credential is exempt. It is the scientist's own
validated key and their explicit instruction to bill it; the engine path
already exempts it (``engine_adapter.resolve_offline_backend``), and the two
must not disagree about what forced offline withholds -- it withholds the
deployment's credential, not the caller's.
"""

from __future__ import annotations

from app import credentials, engine_adapter

__all__ = ["OfflineModeError", "remote_chat_allowed", "require_remote_chat"]


class OfflineModeError(RuntimeError):
    """Raised when a chat completion is refused by forced offline mode."""


def remote_chat_allowed() -> bool:
    """Return whether an app-side chat completion may leave the process.

    Returns:
        True when a bring-your-own-key credential is scoped, or when the
        process is not running offline; False otherwise.
    """
    if credentials.current_byok() is not None:
        return True
    return not engine_adapter.offline_mode()


def require_remote_chat(caller: str) -> None:
    """Refuse an outbound chat completion when offline mode is in force.

    Args:
        caller: Short name of the call site, for the refusal message.

    Raises:
        OfflineModeError: When no request may be made from this process.
    """
    if remote_chat_allowed():
        return
    raise OfflineModeError(
        f"{caller} is not calling a provider: this process runs offline "
        f"(COSCIENTIST_FORCE_OFFLINE, or no provider credential)"
    )
