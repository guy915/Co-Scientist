from __future__ import annotations

from fastapi import APIRouter

from app.config import BYOK_PROVIDER_DEFAULT_MODELS

WORKER_MODEL_HEADER = "X-LLM-Model"
SUPERVISOR_MODEL_HEADER = "X-LLM-Supervisor-Model"

_EXTRA_PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "anthropic": (
        "anthropic/claude-opus-5-5",
        "anthropic/claude-fable-5-1",
    ),
    "deepseek": ("deepseek/deepseek-v4-pro",),
    "gemini": (
        "gemini/gemini-3.1-pro-preview",
        "gemini/gemini-3.1-flash-lite",
    ),
    "openai": ("openai/gpt-6-astra", "openai/gpt-6-luna"),
    "openrouter": (
        "openrouter/deepseek/deepseek-v4-flash",
        "openrouter/deepseek/deepseek-v4-pro",
    ),
}

router = APIRouter(tags=["byok-models"])


class ByokModelError(ValueError):
    """An unoffered provider model is an invalid request, not a provider
    outage.
    """


def provider_models(provider: str) -> tuple[str, ...]:
    default = BYOK_PROVIDER_DEFAULT_MODELS.get(provider)
    if default is None:
        return ()
    return (default, *_EXTRA_PROVIDER_MODELS.get(provider, ()))


def model_catalog() -> dict[str, list[str]]:
    return {
        provider: list(provider_models(provider))
        for provider in BYOK_PROVIDER_DEFAULT_MODELS
    }


def resolve_model_choice(provider: str, requested: str | None) -> str:
    """The closed provider catalog bounds model headers; an omitted choice
    keeps the provider's default.
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
