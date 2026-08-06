"""Tests for ``co_scientist.constants_pricing.estimate_cost_usd``."""

from co_scientist.constants_pricing import ModelPrice, estimate_cost_usd


def test_unlisted_model_prices_at_zero() -> None:
    """A model absent from the table is zero-cost, not a raised error."""
    assert (
        estimate_cost_usd("offline/does-not-exist", 1_000_000, 1_000_000) == 0.0
    )


def test_known_model_prices_proportional_to_tokens() -> None:
    """Cost scales linearly with prompt and completion tokens."""
    cost = estimate_cost_usd(
        "deepseek/deepseek-v4-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    price = ModelPrice(0.28, 0.42)
    assert (
        cost == price.prompt_usd_per_million + price.completion_usd_per_million
    )


def test_zero_tokens_costs_nothing() -> None:
    """A call with no billed tokens costs 0.0 regardless of the model."""
    assert estimate_cost_usd("deepseek/deepseek-v4-pro", 0, 0) == 0.0
