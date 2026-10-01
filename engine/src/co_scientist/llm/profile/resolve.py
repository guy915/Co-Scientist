"""Resolving a route name to its profile."""

from typing import Any

from co_scientist.llm.profile.families import FAMILIES
from co_scientist.llm.profile.routes import ROUTES
from co_scientist.llm.profile.types import ModelPrice, ModelProfile


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
