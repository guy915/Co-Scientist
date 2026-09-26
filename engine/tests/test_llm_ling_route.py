"""Provisional exact-route coverage for Ling Sante's Novita endpoint."""

import json
from typing import Any

import pytest

from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from tests._llm_fake import disable_llm_cache
from tests._llm_free_fakes import _catalog, _mock_catalog
from tests._llm_free_fakes import _free_catalog as _free_catalog
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    patch_acompletion,
)

MODEL = "openrouter/inclusionai/ling-3.0-flash-sante:free"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


async def test_ling_schema_request_uses_prompt_and_local_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer":"ok"}'))],
        requests,
    )

    result = await call_llm_json(
        "Return the observed answer.",
        CompletionSpec(
            model_name=MODEL, api_key="test-byok-key", json_schema=SCHEMA
        ),
        max_attempts=1,
        options=LLMCallOptions(use_cache=False),
    )

    assert result == {"answer": "ok"}
    assert "response_format" not in requests[0]
    assert json.dumps(SCHEMA, indent=2) in requests[0]["messages"][0]["content"]


async def test_ling_free_request_pins_zero_price_and_novita(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog({"prompt": "0", "completion": "0"})
    catalog["data"][0]["id"] = MODEL.removeprefix("openrouter/")
    _mock_catalog(monkeypatch, catalog)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer":"ok"}'))],
        requests,
    )

    await call_llm_json(
        "Public synthetic probe.",
        CompletionSpec(model_name=MODEL, json_schema=SCHEMA),
        max_attempts=1,
        options=LLMCallOptions(use_cache=False),
    )

    provider = requests[0]["extra_body"]["provider"]
    assert provider["only"] == ["novita"]
    assert provider["zdr"] is True
    assert provider["data_collection"] == "deny"
    assert provider["require_parameters"] is True
    assert provider["max_price"] == {"prompt": 0, "completion": 0, "request": 0}


async def test_ling_unschemaed_json_request_omits_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer":"ok"}'))],
        requests,
    )

    result = await call_llm_json(
        "Summarize the synthetic observation.",
        CompletionSpec(model_name=MODEL, api_key="test-byok-key"),
        max_attempts=1,
        options=LLMCallOptions(use_cache=False),
    )

    assert result == {"answer": "ok"}
    assert "response_format" not in requests[0]
    assert "valid JSON" in requests[0]["messages"][0]["content"]


async def test_ling_prompt_only_reply_still_fails_local_schema_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [
            make_completion(make_message('{"answer":17}')),
            make_completion(make_message('{"answer":"ok"}')),
        ],
        requests,
    )

    result = await call_llm_json(
        "Return the observed answer.",
        CompletionSpec(
            model_name=MODEL, api_key="test-byok-key", json_schema=SCHEMA
        ),
        max_attempts=2,
        options=LLMCallOptions(use_cache=False),
    )

    assert result == {"answer": "ok"}
    assert len(requests) == 2
    assert all("response_format" not in request for request in requests)
