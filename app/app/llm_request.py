from typing import Any

from co_scientist.llm import complete_request

from app import credentials, offline_guard, provider_usage
from app.llm_scope import app_call_scope, in_app_call_scope


async def acompletion(**kwargs: Any) -> Any:
    if not in_app_call_scope():
        with app_call_scope("completion"):
            return await _complete(kwargs)
    return await _complete(kwargs)


async def _complete(kwargs: dict[str, Any]) -> Any:
    user_key = credentials.current_byok() is not None
    if not user_key:
        offline_guard.require_remote_chat("chat completion")
        from app.config import settings

        kwargs.setdefault("max_tokens", settings.app_llm_max_output_tokens)
    timeout = kwargs.get("timeout")
    if kwargs.get("stream"):
        kwargs.setdefault("stream_options", {"include_usage": True})
    return await complete_request(
        kwargs,
        str(kwargs["model"]),
        byok=user_key,
        timeout_seconds=float(timeout) if timeout is not None else 600.0,
        before_dispatch=(None if user_key else lambda: provider_usage.reserve(kwargs)),
    )
