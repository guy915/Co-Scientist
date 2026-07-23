"""Shared public value objects for the LLM entry points.

Defined in this leaf module (it imports only ``constants``) so both
``llm`` and ``llm_tool_loop`` can use them without an import cycle:
``llm`` imports helpers from ``llm_tool_loop``, so ``llm_tool_loop`` cannot
import back from ``llm``. Both are re-exported from ``co_scientist.llm`` for
the public import path.
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
    """

    model_name: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = HIGH_TEMPERATURE
    json_schema: dict[str, Any] | None = None
    force_json: bool = False


@dataclass(frozen=True)
class LLMCallOptions:
    """Cache, telemetry, and thinking behavior for one LLM call.

    Every field defaults to the historical default, so ``LLMCallOptions()``
    reproduces the old all-defaults tail of the LLM entry points.

    Attributes:
        use_cache: Whether a cached response may satisfy the call.
        run_id: Owning run id, for per-run cache scoping and logging.
        prompt_name: Name under which to save the rendered prompt, if any.
        prompt_metadata: Extra metadata saved alongside the prompt.
        enable_thinking: Whether to request provider thinking/reasoning.
            Unused by the tool-calling path.
    """

    use_cache: bool = True
    run_id: str | None = None
    prompt_name: str | None = None
    prompt_metadata: dict[str, Any] | None = None
    enable_thinking: bool = True
