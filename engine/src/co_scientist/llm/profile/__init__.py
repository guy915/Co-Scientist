"""Model capabilities, routing facts and prices.

ModelProfile combines the matching FAMILIES declared here with exact entries
in llm.profile.routes. An exact route overrides its family's defaults.
Admission, request shaping and pricing read the same profile; this lowest
LLM layer imports nothing from the rest of the LLM package.
"""

from typing import Any, Final

from co_scientist.llm.profile.routes import ROUTES
from co_scientist.llm.profile.types import (
    Family,
    ModelPrice,
    ModelProfile,
    Thinking,
)

FAMILIES: Final[tuple[Family, ...]] = (
    # DeepSeek, whichever host serves it. The whole family reasons, so
    # every member needs the token floor; honours a disabled reasoning mode;
    # and takes DeepSeek's own ``thinking`` object on its own API. Only
    # ``json_object`` is accepted there, which litellm's registry denies
    # knowing: it marks deepseek/* as supporting response schema, and the
    # DeepSeek API answers a schema'd request with an invalid-request error.
    # Every schema'd call is therefore downgraded, per call, to json_object
    # with the schema restated as prompt text, and missing required fields
    # back-filled with empty defaults (json_object mode has no server-side
    # enforcement, so nested required fields are routinely omitted).
    Family(
        contains="deepseek",
        facts={
            "reasons": True,
            "thinking": Thinking.NATIVE,
            "reasoning_can_disable": True,
            "json_schema": False,
        },
    ),
    # DeepSeek reached through OpenRouter: the gateway normalizes reasoning
    # into its own parameter (``Thinking.GATEWAY``) and spreads one model
    # across hosts that differ sharply in price, so the call carries the
    # routing block and its price ceiling even though no entry names the
    # model.
    Family(
        prefix="openrouter/",
        contains="deepseek",
        facts={"thinking": Thinking.GATEWAY, "gateway": True},
    ),
    # Gemini 3 degrades below temperature 1.0.
    Family(contains="gemini-3", facts={"min_temperature": 1.0}),
)


def model_profile(model_name: str) -> ModelProfile:
    """What the engine knows about ``model_name``.

    Built from the families the name matches, in order, and then from the
    route's own entry, which overrides all of them; a field nobody states is
    what an unknown model gets. The name is lowercased first, as every
    capability question about a model always was.

    Deliberately not cached: resolving is a handful of dict operations next
    to a network call, and an uncached read is one a test can patch the table
    under (``llm.profile.routes.ROUTES``) without a cache to clear.

    Args:
        model_name: Model name in litellm format, any case.

    Returns:
        The model's profile.
    """
    lowered = model_name.lower()
    facts: dict[str, Any] = {}
    for family in FAMILIES:
        if family.matches(lowered):
            facts.update(family.facts)
    facts.update(ROUTES.get(lowered, {}))
    return ModelProfile(**facts)


def gateway_routes() -> tuple[str, ...]:
    """Every route that is declared with gateway routing, in table order."""
    return tuple(name for name, facts in ROUTES.items() if facts.get("gateway"))


def priced_routes() -> dict[str, ModelPrice]:
    """The list price of every route that has one, by exact route name."""
    return {
        name: price
        for name, facts in ROUTES.items()
        if (price := facts.get("price")) is not None
    }


def promotional_free_route(route: str) -> bool:
    """Whether the gateway-relative id ``route`` is an admitted promotion.

    An exact, case-sensitive match on the id as OpenRouter's catalog spells
    it, unlike ``model_profile``: admission is checked against that
    catalog, whose ids are exact.

    Args:
        route: An OpenRouter model id without the ``openrouter/`` prefix.

    Returns:
        True when the route's own entry marks it promotionally free.
    """
    return bool(ROUTES.get(f"openrouter/{route}", {}).get("promotional_free"))


__all__ = [
    "ModelPrice",
    "ModelProfile",
    "Thinking",
    "gateway_routes",
    "model_profile",
    "priced_routes",
    "promotional_free_route",
]
