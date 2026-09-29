"""Models a bring-your-own-key run may choose for each tier.

A scientist who brings a key picks two models in Settings > Model: a
worker model (generation, review, ranking, evolution, and every app-side
call) and a supervisor model (research planning, meta-review, and the
final overview). Both ride the create-run request as headers next to the
key (``X-LLM-Model`` / ``X-LLM-Supervisor-Model``).

The choice is closed to this catalog rather than free text: a model
outside it would reach litellm untested, and the header would otherwise
be an open channel for arbitrary strings into the run config. Each list
starts with the provider's default (``config.BYOK_PROVIDER_DEFAULT_MODELS``)
so an omitted header resolves exactly as it did before selection existed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import BYOK_PROVIDER_DEFAULT_MODELS

WORKER_MODEL_HEADER = "X-LLM-Model"
SUPERVISOR_MODEL_HEADER = "X-LLM-Supervisor-Model"

_EXTRA_PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "anthropic": (
        "anthropic/claude-opus-4-5",
        "anthropic/claude-haiku-4-5",
    ),
    "azure": (),
    "deepseek": ("deepseek/deepseek-v4-pro",),
    "gemini": (
        "gemini/gemini-2.5-pro",
        "gemini/gemini-2.5-flash-lite",
    ),
    "openai": ("openai/gpt-4o-mini",),
    "openrouter": (
        "openrouter/deepseek/deepseek-v4-flash",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/anthropic/claude-sonnet-4.5",
        "openrouter/openai/gpt-4o",
    ),
}

router = APIRouter(tags=["byok-models"])


class ByokModelError(ValueError):
    """A requested model is not offered for the provider. Maps to 400."""


def provider_models(provider: str) -> tuple[str, ...]:
    """Return the models offered for ``provider``, default first.

    Args:
        provider: Provider id, as sent on the X-LLM-Provider header.

    Returns:
        The offered models, or an empty tuple for an unknown provider.
    """
    default = BYOK_PROVIDER_DEFAULT_MODELS.get(provider)
    if default is None:
        return ()
    return (default, *_EXTRA_PROVIDER_MODELS.get(provider, ()))


def model_catalog() -> dict[str, list[str]]:
    """Return every provider's offered models, for the Settings UI."""
    return {
        provider: list(provider_models(provider))
        for provider in BYOK_PROVIDER_DEFAULT_MODELS
    }


def resolve_model_choice(provider: str, requested: str | None) -> str:
    """Resolve one tier's model choice against the provider's catalog.

    Args:
        provider: Provider id the key belongs to.
        requested: The model sent on the tier's header, or None/blank.

    Returns:
        The requested model, or the provider's default when none was sent.

    Raises:
        ByokModelError: The model is not offered for this provider.
    """
    offered = provider_models(provider)
    choice = (requested or "").strip()
    if not choice:
        return offered[0]
    if choice not in offered:
        raise ByokModelError(
            f"model {choice!r} is not offered for provider {provider}"
        )
    return choice


@router.get("/api/byok-models")
async def get_byok_models() -> dict[str, dict[str, list[str]]]:
    """Return the models each BYOK provider offers, default first."""
    return {"providers": model_catalog()}
