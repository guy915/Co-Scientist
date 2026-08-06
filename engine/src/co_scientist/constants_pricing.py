"""Per-model USD pricing for LLM cost estimation.

Split out of ``constants.py`` (size cap; see ``constants_cache.py`` for the
same pattern) rather than grown into it. Deliberately a plain, obviously
editable table rather than a live pricing lookup or third-party dependency:
this is an estimate, not a billing record, and every field is named for
what it is.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ModelPrice:
    """USD price per million tokens for one model.

    Attributes:
        prompt_usd_per_million: Cost per million prompt (input) tokens.
        completion_usd_per_million: Cost per million completion (output)
            tokens. Reasoning tokens are billed at this same rate: most
            providers do not price them separately, and this table has no
            third rate to place them under.
    """

    prompt_usd_per_million: float = 0.0
    completion_usd_per_million: float = 0.0


# Approximate list prices at time of writing, in USD per million tokens.
# A model absent from this table prices at zero (see estimate_cost_usd)
# rather than raising or guessing -- a new or renamed model then degrades
# to "no cost tracked" instead of breaking telemetry for every call site
# that names it. Keep in sync with the deployed defaults in
# app/app/config.py when those change; nothing enforces that automatically.
MODEL_PRICING: Final[dict[str, ModelPrice]] = {
    "deepseek/deepseek-v4-flash": ModelPrice(0.28, 0.42),
    "deepseek/deepseek-v4-pro": ModelPrice(0.56, 1.68),
    "deepseek/deepseek-chat": ModelPrice(0.28, 0.42),
    "deepseek/deepseek-reasoner": ModelPrice(0.56, 1.68),
    "gemini/gemini-2.5-flash": ModelPrice(0.30, 2.50),
    "gemini/gemini-2.5-pro": ModelPrice(1.25, 10.00),
    "openai/gpt-4o": ModelPrice(2.50, 10.00),
    "openai/gpt-4o-mini": ModelPrice(0.15, 0.60),
    "anthropic/claude-sonnet-4-5": ModelPrice(3.00, 15.00),
}


def estimate_cost_usd(
    model_name: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Estimates one call's USD cost from its token counts.

    Args:
        model_name: Model name in litellm format.
        prompt_tokens: Prompt (input) tokens billed for the call.
        completion_tokens: Completion (output) tokens billed for the call,
            including any reasoning tokens the provider bills alongside it.

    Returns:
        The estimated cost in USD, or 0.0 for a model absent from
        ``MODEL_PRICING`` (an offline or unlisted model is zero-cost
        rather than an unpriced guess).
    """
    price = MODEL_PRICING.get(model_name)
    if price is None:
        return 0.0
    return (
        prompt_tokens / 1_000_000 * price.prompt_usd_per_million
        + completion_tokens / 1_000_000 * price.completion_usd_per_million
    )
