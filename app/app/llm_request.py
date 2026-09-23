"""Shared admission for app-side streaming and plain-text completions."""

from typing import Any

from co_scientist.llm_free_policy import enforce_free_request

from app import credentials, offline_guard


async def acompletion(**kwargs: Any) -> Any:
    """Apply admission using the scoped user credential, including probes."""
    import litellm

    user_key = credentials.current_byok() is not None
    if not user_key:
        offline_guard.require_remote_chat("chat completion")
    await enforce_free_request(kwargs, byok=user_key)
    return await litellm.acompletion(**kwargs)
