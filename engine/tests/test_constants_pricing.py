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
