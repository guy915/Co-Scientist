from __future__ import annotations

import time
from typing import Any

import httpx

_TIMEOUT = 15.0

_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
}


class ModelCatalogError(ValueError):
    pass


class ModelCatalogTimeoutError(ModelCatalogError):
    pass


def read_provider_models(provider: str, api_key: str) -> list[dict[str, Any]]:
    if provider not in _ENDPOINTS:
        raise ModelCatalogError("Unsupported provider")
    try:
        return _read_provider_models(provider, api_key)
    except ModelCatalogTimeoutError:
        raise
    except httpx.TimeoutException:
        raise ModelCatalogTimeoutError("The provider timed out") from None
    except Exception:
        # Provider errors can include request headers or echo credentials.
        raise ModelCatalogError("The provider could not return a model list") from None


def _read_provider_models(provider: str, api_key: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if provider == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    elif provider == "gemini":
        headers = {"x-goog-api-key": api_key}
    deadline = time.monotonic() + 30.0
    models: list[dict[str, Any]] = []
    params: dict[str, str] = {}
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        for _ in range(20):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelCatalogTimeoutError("The provider timed out")
            response = client.get(
                _ENDPOINTS[provider],
                headers=headers,
                params=params,
                timeout=min(_TIMEOUT, remaining),
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("models" if provider == "gemini" else "data")
            if not isinstance(rows, list):
                raise ModelCatalogError("The provider returned an invalid model list")
            models.extend(row for row in rows if isinstance(row, dict))
            if provider == "gemini" and payload.get("nextPageToken"):
                params = {"pageToken": str(payload["nextPageToken"])}
            elif provider == "anthropic" and payload.get("has_more") and payload.get("last_id"):
                params = {"after_id": str(payload["last_id"])}
            else:
                return models
    raise ModelCatalogError("The provider model list exceeded the validation limit")
