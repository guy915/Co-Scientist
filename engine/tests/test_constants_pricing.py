"""Tests for ``co_scientist.constants_pricing.estimate_cost_usd``."""

from co_scientist.constants_pricing import MODEL_PRICING, estimate_cost_usd


def test_unlisted_model_prices_at_zero() -> None:
    """A model absent from the table is zero-cost, not a raised error."""
    assert (
        estimate_cost_usd("offline/does-not-exist", 1_000_000, 1_000_000) == 0.0
    )


def test_known_model_prices_proportional_to_tokens() -> None:
    """Cost scales linearly with prompt and completion tokens.

    Reads the rate out of the table rather than restating it. A test
    that spells the number out again pins the price rather than the
    arithmetic, and then fails on a provider's price change -- which is
    a fact to record, not a regression to catch.
    """
    model = "deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]

    million = estimate_cost_usd(model, 1_000_000, 1_000_000)
    half = estimate_cost_usd(model, 500_000, 500_000)

    assert million == (
        price.prompt_usd_per_million + price.completion_usd_per_million
    )
    assert half == million / 2


def test_zero_tokens_costs_nothing() -> None:
    """A call with no billed tokens costs 0.0 regardless of the model."""
    assert estimate_cost_usd("deepseek/deepseek-v4-pro", 0, 0) == 0.0


def test_a_cached_prefix_is_billed_at_the_cache_rate() -> None:
    """The cached share of a prompt prices below the rest of it.

    A tool loop re-sends its whole transcript every turn, so most of what
    a run sends is a prefix the provider already holds. Measured through
    OpenRouter, a concurrent fan-out re-sending one prefix reported 95% of
    its prompt tokens cached -- pricing that at the full input rate is
    what made this project's reported run cost several times the bill.
    """
    model = "openrouter/deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]
    assert price.cached_prompt_usd_per_million < price.prompt_usd_per_million

    uncached = estimate_cost_usd(model, 1_000_000, 0)
    fully_cached = estimate_cost_usd(model, 1_000_000, 0, 1_000_000)

    assert uncached == price.prompt_usd_per_million
    assert fully_cached == price.cached_prompt_usd_per_million
    assert (
        estimate_cost_usd(model, 1_000_000, 0, 500_000)
        == (uncached + fully_cached) / 2
    )


def test_a_model_with_no_measured_cache_rate_prices_as_before() -> None:
    """An unlisted cache rate means unmeasured, never free.

    Reading a cached count from a provider whose cache-read rate nobody
    has checked and billing it at zero would report a run as cheaper than
    it was, which is the one direction an estimate must never err in.
    """
    model = "openai/gpt-4o"
    assert MODEL_PRICING[model].cached_prompt_usd_per_million == 0.0

    assert estimate_cost_usd(model, 1_000_000, 0, 1_000_000) == (
        estimate_cost_usd(model, 1_000_000, 0)
    )


def test_a_cached_count_never_exceeds_the_prompt_it_slices() -> None:
    """Cached tokens are part of the prompt, never an addition to it."""
    model = "openrouter/deepseek/deepseek-v4-flash"
    price = MODEL_PRICING[model]

    assert estimate_cost_usd(model, 1_000, 0, 10_000) == (
        1_000 / 1_000_000 * price.cached_prompt_usd_per_million
    )
    assert estimate_cost_usd(model, 1_000, 0, -5) == (
        1_000 / 1_000_000 * price.prompt_usd_per_million
    )
