"""The selected zero-price promotion must stay free at the LLM boundary."""

from typing import Any

import pytest

from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from tests._llm_free_fakes import _catalog, _mock_catalog
from tests._llm_free_fakes import _free_catalog as _free_catalog
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    patch_acompletion,
)

MODEL = "openrouter/stealth/space-bunny-alpha"
OPTIONS = LLMCallOptions(use_cache=False)


def _promotion(pricing: dict[str, str]) -> dict[str, Any]:
    catalog = _catalog(pricing)
    catalog["data"][0]["id"] = MODEL.removeprefix("openrouter/")
    return catalog


async def test_current_free_promotion_pins_provider_and_zero_token_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "0")
    _mock_catalog(monkeypatch, _promotion({"prompt": "0", "completion": "0"}))
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer": "ready"}'))],
        requests,
    )

    result = await call_llm_json(
        "Return ready as JSON", CompletionSpec(MODEL), options=OPTIONS
    )

    assert result == {"answer": "ready"}
    assert len(requests) == 1
    assert requests[0]["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert requests[0]["extra_body"]["provider"]["only"] == ["Stealth"]
    assert requests[0]["extra_body"]["provider"]["allow_fallbacks"] is False


async def test_promotion_price_change_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_catalog(
        monkeypatch, _promotion({"prompt": "0.01", "completion": "0"})
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(monkeypatch, [], requests)

    with pytest.raises(RuntimeError, match="zero-cost"):
        await call_llm_json(
            "Return ready as JSON", CompletionSpec(MODEL), options=OPTIONS
        )
    assert requests == []
