"""Per-model USD pricing for LLM cost estimation.

Split out of ``constants.py`` (size cap; see ``constants_cache.py`` for the
same pattern) rather than grown into it. Deliberately a plain lookup rather
than a live pricing service or third-party dependency: this is an estimate,
not a billing record, and every field is named for what it is.

The prices themselves are stated, with their provenance, in the model
profile table (``co_scientist.llm.profile.routes``); ``MODEL_PRICING`` is that
table's priced routes, so a price lives in exactly one place.
"""

from typing import Final

from co_scientist.llm.profile import ModelPrice, priced_routes

# Keyed by exact route name, so this lookup is case-sensitive, unlike a
# profile's capabilities. A model absent from it prices at zero (see
# ``estimate_cost_usd``) rather than raising or guessing -- a new or renamed
# model then degrades to "no cost tracked" instead of breaking telemetry for
# every call site that names it.
MODEL_PRICING: Final[dict[str, ModelPrice]] = priced_routes()

__all__ = ["MODEL_PRICING", "ModelPrice", "estimate_cost_usd"]


def estimate_cost_usd(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int = 0,
) -> float:
    """Estimates one call's USD cost from its token counts.

    Args:
        model_name: Model name in litellm format.
        prompt_tokens: Prompt (input) tokens billed for the call.
        completion_tokens: Completion (output) tokens billed for the call,
            including any reasoning tokens the provider bills alongside it.
        cached_prompt_tokens: The share of ``prompt_tokens`` served from
            the provider's prompt cache. Priced at the model's cache-read
            rate and the remainder at the full input rate. Ignored for a
            model whose cache rate is unlisted, so an unmeasured model
            keeps costing exactly what it did before.

    Returns:
        The estimated cost in USD, or 0.0 for a model absent from
        ``MODEL_PRICING`` (an offline or unlisted model is zero-cost
        rather than an unpriced guess).
    """
    price = MODEL_PRICING.get(model_name)
    if price is None:
        return 0.0
    cached = 0
    if price.cached_prompt_usd_per_million:
        cached = max(0, min(cached_prompt_tokens, prompt_tokens))
    return (
        (prompt_tokens - cached) / 1_000_000 * price.prompt_usd_per_million
        + cached / 1_000_000 * price.cached_prompt_usd_per_million
        + completion_tokens / 1_000_000 * price.completion_usd_per_million
    )
