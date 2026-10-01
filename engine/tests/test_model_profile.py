"""The model profile table: how a route name resolves, and its invariants.

``test_model_profile_snapshot.py`` pins what every function that reads a
profile answers for each named route. This pins the profile itself: the
resolution rules the table relies on, and the consistency of the table.
"""

import dataclasses

import pytest

from co_scientist.constants_pricing import MODEL_PRICING
from co_scientist.llm import ModelProfile, model_profile
from co_scientist.llm.profile import (
    ModelPrice,
    Thinking,
    gateway_routes,
    priced_routes,
    promotional_free_route,
)
from co_scientist.llm.profile.families import FAMILIES
from co_scientist.llm.profile.routes import ROUTES
from co_scientist.llm.profile.types import Facts

_STEALTH = "openrouter/stealth/space-bunny-alpha"


def test_a_table_entry_and_a_profile_list_the_same_fields() -> None:
    """``Facts`` is a profile's fields, each optional; none may drift."""
    assert set(Facts.__annotations__) == {
        field.name for field in dataclasses.fields(ModelProfile)
    }


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "ollama/llama3", "openrouter/x/y", "openrouter/x/y:free"],
)
def test_an_unknown_route_gets_the_defaults(model: str) -> None:
    """No reasoning knob, no routing, no price, and litellm decides schema."""
    assert model_profile(model) == ModelProfile()


def test_capabilities_resolve_without_regard_to_case() -> None:
    """Callers lowercase nothing; the profile does."""
    assert model_profile("DeepSeek/DeepSeek-V4-Flash") == model_profile(
        "deepseek/deepseek-v4-flash"
    )
    assert model_profile(_STEALTH.upper()) == model_profile(_STEALTH)


@pytest.mark.parametrize(
    ("model", "thinking", "gateway"),
    [
        ("deepseek/deepseek-v5-x", Thinking.NATIVE, False),
        ("vendor/mydeepseek-r9", Thinking.NATIVE, False),
        ("openrouter/deepseek/deepseek-v5-x", Thinking.GATEWAY, True),
        (_STEALTH, Thinking.GATEWAY, True),
        ("openrouter/vendor/gemini-3-x", Thinking.NONE, False),
    ],
)
def test_how_a_route_is_asked_to_think_follows_its_family(
    model: str, thinking: Thinking, gateway: bool
) -> None:
    """A new DeepSeek release needs no entry; an unknown gateway route none."""
    profile = model_profile(model)
    assert (profile.thinking, profile.gateway) == (thinking, gateway)


def test_a_family_can_reach_a_route_it_shares_with_another() -> None:
    """Both families apply, the later over the earlier where they differ."""
    profile = model_profile("openrouter/vendor/gemini-3-deepseek-hybrid")
    assert profile.min_temperature == 1.0
    assert profile.thinking is Thinking.GATEWAY
    assert profile.json_schema is False


def test_an_exact_entry_overrides_its_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route's own word beats the family's, field by field."""
    route = "openrouter/deepseek/pinned"
    own: Facts = {"reasons": False, "json_schema": True}
    monkeypatch.setitem(ROUTES, route, own)

    profile = model_profile(route)

    assert profile.reasons is False
    assert profile.json_schema is True
    assert profile.thinking is Thinking.GATEWAY, (
        "unstated fields stay the family's"
    )


def test_no_exact_route_overrules_a_family_on_json_schema() -> None:
    """Exact routes win now; before the table, a family answered first.

    Resolving json_schema used to check the json_object-only family ahead of
    any exact route, and every other fact the exact route first. They agree
    only while no route states a json_schema its family contradicts, so that
    is held here: lifting it would change what such a route is sent.
    """
    for route, facts in ROUTES.items():
        for family in FAMILIES:
            stated = family.facts.get("json_schema")
            if family.matches(route) and stated is not None:
                assert facts.get("json_schema", stated) == stated, route


def _resolved_profiles() -> list[tuple[str, ModelProfile]]:
    probes = ["deepseek/x", "openrouter/deepseek/x", "openrouter/a/b"]
    return [(name, model_profile(name)) for name in [*ROUTES, *probes]]


def test_the_thinking_knob_and_the_gateway_agree() -> None:
    """A gateway reasoning object needs routing; DeepSeek's own cannot."""
    for name, profile in _resolved_profiles():
        if profile.thinking is Thinking.GATEWAY:
            assert profile.gateway, name
        if profile.thinking is Thinking.NATIVE:
            assert not profile.gateway, name


def test_every_declared_gateway_route_is_priced_and_funded() -> None:
    """No price means no ceiling on a gateway call; no floor means no answer."""
    routes = gateway_routes()
    assert routes
    for name in routes:
        profile = model_profile(name)
        assert profile.price is not None, name
        assert profile.reasons, name


def test_the_price_table_is_the_profile_prices() -> None:
    """One statement of each price: ``MODEL_PRICING`` is read off the table."""
    assert priced_routes() == MODEL_PRICING
    for name, price in MODEL_PRICING.items():
        assert model_profile(name).price == price, name


def test_the_default_route_is_pinned_free_with_no_fallback() -> None:
    """The selected zero-price route stays on Stealth, free, with no chain."""
    profile = model_profile(_STEALTH)
    assert profile.provider_only == "Stealth"
    assert profile.fallbacks == ()
    assert profile.price == ModelPrice(0.0, 0.0)
    assert profile.promotional_free


def test_promotion_is_matched_exactly_as_the_catalog_spells_the_id() -> None:
    """A gateway-relative id, case-sensitive: admission checks the catalog."""
    assert promotional_free_route("stealth/space-bunny-alpha")
    assert not promotional_free_route("Stealth/Space-Bunny-Alpha")
    assert not promotional_free_route(_STEALTH)
    assert not promotional_free_route("nex-agi/nex-n2.5-pro:free")
