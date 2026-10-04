"""Leaf value definitions avoid import cycles between dispatch layers."""

from dataclasses import dataclass
from typing import Any

from co_scientist.constants import DEFAULT_MAX_TOKENS, HIGH_TEMPERATURE


@dataclass(frozen=True)
class CompletionSpec:
    """Provider credentials must never enter cache keys or persisted request
    state.
    """

    model_name: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = HIGH_TEMPERATURE
    json_schema: dict[str, Any] | None = None
    force_json: bool = False
    api_key: str | None = None


@dataclass(frozen=True)
class LLMCallOptions:
    """Attempt loops own the failure log because they know retry context."""

    use_cache: bool = True
    run_id: str | None = None
    prompt_name: str | None = None
    enable_thinking: bool = True
    log_failures: bool = True


def indexed_prompt_name(stem: str, index: int | None) -> str:
    return f"{stem}_{index}" if index is not None else stem
