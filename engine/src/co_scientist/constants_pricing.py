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
        cached_prompt_usd_per_million: Cost per million prompt tokens the
            provider served from its prompt cache. Zero means *not
            measured for this model*, not free: ``estimate_cost_usd`` then
            prices every prompt token at the full input rate, which is
            what this table did before caching was read at all. Set it
            only for a model whose cache-read rate has been checked
            against the provider's own quote.
    """

    prompt_usd_per_million: float = 0.0
    completion_usd_per_million: float = 0.0
    cached_prompt_usd_per_million: float = 0.0


# Published list prices, in USD per million tokens, verified against each
# provider's own pricing page in August 2026. A model absent from this
# table prices at zero (see estimate_cost_usd) rather than raising or
# guessing -- a new or renamed model then degrades to "no cost tracked"
# instead of breaking telemetry for every call site that names it. Keep in
# sync with the deployed defaults in app/app/config.py when those change;
# nothing enforces that automatically.
#
# Two ways a figure here is deliberately the pessimistic one, because an
# estimate that flatters the bill is worse than no estimate:
#
# * **Peak rate for DeepSeek.** DeepSeek bills at half these rates outside
#   01:00-04:00 and 06:00-10:00 UTC. One rate per model is all this table
#   has room for, and the clock is not a property of the model, so the
#   higher one is listed and an off-peak run simply comes in under
#   estimate. The previous entries were neither rate -- they predated the
#   V4 price rise and understated output by more than half.
# * **Cache-miss input for any model without a measured cache rate.**
#   ``extract_token_usage`` now reads the cached share of each prompt, so
#   a model carrying ``cached_prompt_usd_per_million`` prices that share
#   at the cheaper rate. A model without one keeps pricing every prompt
#   token at the full input rate, which over-states rather than flatters.
#   Measured on ``deepseek-v4-flash`` through OpenRouter: an 11k-token
#   prefix re-sent cost $0.00090 cold and $0.00020 once cached, and a
#   concurrent fan-out of eight re-sending the same prefix reported 95%
#   of its prompt tokens cached -- so the un-cached estimate this table
#   produced was several times the real bill on any tool loop.
MODEL_PRICING: Final[dict[str, ModelPrice]] = {
    "deepseek/deepseek-v4-flash": ModelPrice(0.44, 1.32),
    "deepseek/deepseek-v4-pro": ModelPrice(1.32, 3.96),
    "deepseek/deepseek-chat": ModelPrice(0.44, 1.32),
    "deepseek/deepseek-reasoner": ModelPrice(1.32, 3.96),
    "gemini/gemini-2.5-flash": ModelPrice(0.30, 2.50),
    "gemini/gemini-2.5-flash-lite": ModelPrice(0.10, 0.40),
    "gemini/gemini-2.5-pro": ModelPrice(1.25, 10.00),
    "gemini/gemini-3.1-flash-lite": ModelPrice(0.25, 1.50),
    # The same DeepSeek weights reached through OpenRouter, which routes
    # across seventeen hosts spanning 6.5x on input and 7.9x on output.
    # Which one a call lands on is a routing decision, not a property of
    # the model (see ``llm_thinking._GATEWAY_PROVIDER``), so these are the
    # rates a price-capped route can actually be held to rather than an
    # average over hosts the cap excludes.
    # Listed separately because they are a different bill, not a different
    # model: the worker tier costs roughly a fifth of first-party peak.
    # Rates move as hosts come and go -- these were OpenRouter's quoted
    # prices in August 2026, and OpenRouter reports the exact cost of each
    # call in its own dashboard, which is the billing record this only
    # estimates.
    "openrouter/deepseek/deepseek-v4-flash": ModelPrice(0.083, 0.165, 0.017),
    # The deployed default on every tier (``app.config``). Priced off the
    # fp8 hosts rather than the cheapest row on the board: the headline
    # rate for this model belongs to an fp4 host at 95% uptime, and
    # ``_MAX_PRICE_MULTIPLE`` doubles whatever is written here into the
    # routing ceiling, so a rate copied from the cheapest quantized host
    # would cap the route below every full-precision one. At 2x this,
    # twenty of the model's twenty-nine hosts stay eligible, and the tail
    # charging up to 3.4x this on input and 4.7x on output -- DeepSeek's
    # own first-party endpoint among them, at 0.22/0.66 -- is excluded.
    "openrouter/deepseek/deepseek-v4-flash-0731": ModelPrice(0.13, 0.28, 0.028),
    # Static zero-token-price entries arm zero prompt/completion/request
    # ceilings in the shared gateway builder. This table is an estimate,
    # not proof of current availability or of every applicable charge.
    "openrouter/z-ai/glm-5.2:free": ModelPrice(0.0, 0.0),
    "openrouter/minimax/minimax-m3:free": ModelPrice(0.0, 0.0),
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": ModelPrice(0.0, 0.0),
    "openrouter/google/gemma-4-31b-it:free": ModelPrice(0.0, 0.0),
    "openrouter/minimax/minimax-m2.7:free": ModelPrice(0.0, 0.0),
    "openrouter/dots-studio/dots-3-note-preview:free": ModelPrice(0.0, 0.0),
    "openrouter/nvidia/nemotron-3.5-lightning:free": ModelPrice(0.0, 0.0),
    # Historical promotional rate for the paid alternative chain head;
    # its routing ceiling uses the same configured price multiple as other
    # paid entries. Revalidate current pricing before choosing this route.
    "openrouter/z-ai/glm-5.3-flash": ModelPrice(0.075, 0.25, 0.015),
    # The paid last resort, and the only rung that can spend anything. At
    # twenty times the rate of the DeepSeek route this replaced, a run that
    # falls all the way through costs materially more than one that does
    # not -- so a bill appearing here is a signal that both free rungs were
    # unavailable, not that the model was chosen.
    "openrouter/deepseek/deepseek-v4-pro": ModelPrice(1.60, 3.20, 0.13),
    "openai/gpt-4o": ModelPrice(2.50, 10.00),
    # Azure resells OpenAI's models at OpenAI's list price. Present
    # because ``BYOK_PROVIDER_DEFAULT_MODELS`` names it, and an unpriced
    # model reports every run as costing nothing.
    "azure/gpt-4o": ModelPrice(2.50, 10.00),
    "openai/gpt-4o-mini": ModelPrice(0.15, 0.60),
    "anthropic/claude-sonnet-4-5": ModelPrice(3.00, 15.00),
}


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
