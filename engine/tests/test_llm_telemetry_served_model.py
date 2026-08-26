"""Tests that cost is attributed to the model that actually served a call.

A gateway may answer with a different model than the one requested: that is
what a fallback chain is for. Pricing the *requested* name then reports a
run's cost as whatever the configured model would have cost, which is not
what the provider billed -- and the gap is widest exactly when it matters,
because a chain is walked precisely when the primary is unavailable.

Observed live: a run configured for a free primary reported ``$0.00`` for
226 calls while the gateway was serving a fallback at $1.25/$4.25 per
million. The account was billed $5.23; the run's own telemetry said zero.
"""

from typing import Any

from co_scientist.llm_telemetry import record_completion_response


class _Usage:
    prompt_tokens = 1_000_000
    completion_tokens = 1_000_000
    cached_tokens = 0
    reasoning_tokens = 0
    completion_tokens_details = None
    prompt_tokens_details = None


class _Response:
    """A completion answered by a different model than was requested."""

    def __init__(self, served: str | None) -> None:
        self.model = served
        self.usage = _Usage()
        self.choices: list[Any] = []


def test_cost_follows_the_model_that_answered(monkeypatch: Any) -> None:
    """A fallback's price is charged to the fallback, not to the primary.

    The free primary here costs nothing; the model that actually answered
    is priced. Attributing to the requested name reports zero for a call
    that was billed, which is the failure this pins. The fallback keeps
    the route it was reached by, since a call served through a gateway is
    billed as a gateway call whichever rung answered it.
    """
    from co_scientist import llm_telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        llm_telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/minimax/minimax-m3:free",
        _Response("deepseek/deepseek-v4-pro"),
        1.0,
    )

    assert seen["model"] == "openrouter/deepseek/deepseek-v4-pro"
    assert seen["stats"].cost_usd > 0


def test_a_response_naming_no_model_keeps_the_requested_name(
    monkeypatch: Any,
) -> None:
    """The requested name stays the fallback when the provider omits one.

    Not every provider echoes the served model, and a missing field must
    not blank out a run's whole cost attribution.
    """
    from co_scientist import llm_telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        llm_telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response("openai/gpt-4o", _Response(None), 1.0)

    assert seen["model"] == "openai/gpt-4o"


def test_the_served_name_keeps_the_route_that_billed_it(
    monkeypatch: Any,
) -> None:
    """A gateway names the model without the route prefix it was reached by.

    ``openrouter/z-ai/glm-5.3-flash`` comes back as ``z-ai/glm-5.3-flash``,
    which matches no key in ``MODEL_PRICING`` -- so reading the served name
    naively prices every call at zero, reproducing the exact failure that
    reading the requested name caused. Measured on a live run: 53 calls,
    every one of them $0.0000.

    The route is a property of how the call was billed, so it is carried
    over from the request; only the model part comes from the response.
    """
    from co_scientist import llm_telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        llm_telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/z-ai/glm-5.3-flash",
        _Response("z-ai/glm-5.3-flash"),
        1.0,
    )

    assert seen["model"] == "openrouter/z-ai/glm-5.3-flash"
    assert seen["stats"].cost_usd > 0


def test_a_fallback_is_still_named_as_itself(monkeypatch: Any) -> None:
    """Carrying the route must not collapse a fallback onto its primary.

    The whole point of reading the served model is telling them apart, so
    re-prefixing has to keep the model half the response reported.
    """
    from co_scientist import llm_telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        llm_telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/z-ai/glm-5.3-flash",
        _Response("minimax/minimax-m3:free"),
        1.0,
    )

    assert seen["model"] == "openrouter/minimax/minimax-m3:free"
