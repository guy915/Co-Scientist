"""The models this deployment defaults to must be ones the engine prices.

An unpriced model is not a cosmetic gap. ``estimate_cost_usd`` returns 0.0
for a model absent from ``MODEL_PRICING``, so every run reports a cost of
zero -- and, on an OpenRouter route, ``llm.request.thinking._gateway_provider``
derives its ``max_price`` ceiling from the same table and simply omits the
cap when there is no entry, which lets a call land on the most expensive
host serving that model. Both failures are silent, which is why the
pairing is asserted rather than left to the pricing table's comment.
"""

from co_scientist.constants.pricing import MODEL_PRICING

from app.config import BYOK_PROVIDER_DEFAULT_MODELS, Settings

_MODEL_FIELDS = (
    "model_name",
    "supervisor_model_name",
    "chat_model_name",
    "semantic_safety_model",
)
_SYSTEM_DEFAULT_MODEL = "openrouter/stealth/space-bunny-alpha"


def _default_models() -> set[str]:
    """Every model name this deployment ships as a tier's default.

    Read off the field declarations rather than the live ``settings``
    object: a developer's own ``.env`` overrides those at import time, and
    a check that passes only because the local environment names a priced
    model is not checking the shipped default at all.
    """
    return {
        default
        for field in _MODEL_FIELDS
        if isinstance(default := Settings.model_fields[field].default, str)
    }


def test_all_system_default_roles_select_space_bunny() -> None:
    """Worker, supervisor, chat and semantic safety share the selected model."""
    actual = {
        field: Settings.model_fields[field].default for field in _MODEL_FIELDS
    }

    assert actual == dict.fromkeys(_MODEL_FIELDS, _SYSTEM_DEFAULT_MODEL)
    assert Settings.model_fields["claim_verifier_model"].default is None


def test_every_default_model_is_priced() -> None:
    """Each tier's default model carries a rate in the engine's table."""
    unpriced = sorted(_default_models() - set(MODEL_PRICING))

    assert not unpriced, (
        f"default models missing from MODEL_PRICING: {unpriced}"
    )


def test_every_byok_default_model_is_priced() -> None:
    """A bring-your-own-key run is priced the same way a house run is."""
    unpriced = sorted(
        set(BYOK_PROVIDER_DEFAULT_MODELS.values()) - set(MODEL_PRICING)
    )

    assert not unpriced, f"BYOK models missing from MODEL_PRICING: {unpriced}"
