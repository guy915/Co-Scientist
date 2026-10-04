"""Shared public value objects for the LLM entry points.

Defined in this leaf module (it imports only ``constants``) so every layer
of the package can name them without an import cycle. Outside the package they
are imported from ``co_scientist.llm``.
"""

from dataclasses import dataclass
from typing import Any

from co_scientist.constants import DEFAULT_MAX_TOKENS, HIGH_TEMPERATURE


@dataclass(frozen=True)
class CompletionSpec:
    """How to run one completion: which model, sampling, and output shape.

    Attributes:
        model_name: LLM model in litellm format.
        max_tokens: Completion token ceiling.
        temperature: Sampling temperature.
        json_schema: JSON schema the response must satisfy, if any.
        force_json: Request raw JSON output without a schema. Ignored by
            ``call_llm_json`` (which always parses JSON) and by the
            tool-calling path.
        api_key: Provider credential for this call only (bring-your-own-
            key), passed to litellm as ``api_key`` so it overrides the
            deployment's environment credential without touching it.
            None defers to a key scoped via
            ``llm.admission.credentials.scoped_api_key``, then to the
            environment. Never stored on ``LLMCacheRequest``, so it cannot enter
            a cache key or any persisted state.
    """

    model_name: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = HIGH_TEMPERATURE
    json_schema: dict[str, Any] | None = None
    force_json: bool = False
    api_key: str | None = None


@dataclass(frozen=True)
class LLMCallOptions:
    """Attempt loops log failures once with retry context; raw calls defer."""

    use_cache: bool = True
    run_id: str | None = None
    prompt_name: str | None = None
    enable_thinking: bool = True
    log_failures: bool = True


def indexed_prompt_name(stem: str, index: int | None) -> str:
    return f"{stem}_{index}" if index is not None else stem
