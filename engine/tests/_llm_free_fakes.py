"""Isolated OpenRouter catalog fixtures for free-route admission tests."""

from typing import Any

import httpx
import pytest


@pytest.fixture(autouse=True)
def _free_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)


def _catalog(pricing: Any) -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "campaign/zero:free",
                "pricing": pricing,
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        ]
    }


def _mock_catalog(monkeypatch: pytest.MonkeyPatch, data: Any) -> list[str]:
    calls: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(url)
        assert kwargs == {"timeout": 15, "trust_env": False}
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    return calls
