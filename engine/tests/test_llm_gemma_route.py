"""Regression coverage for the exact Gemma 4 26B OpenRouter route.

The route advertises ``response_format`` without the endpoint capability
needed for native JSON Schema. These tests keep that exception narrow while
covering the existing prompt shim, local validation, and free-route policy.
"""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    _supports_json_schema_response_format,
    call_llm,
    call_llm_json,
)
from tests._llm_fake import NESTED_SCHEMA as _NESTED_SCHEMA
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_free_fakes import _catalog, _mock_catalog
from tests._llm_free_fakes import _free_catalog as _free_catalog
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)
from tests._llm_wrapper_fakes import (
    patch_acompletion as _patch_acompletion,
)

_MODEL = "openrouter/google/gemma-4-26b-a4b-it:free"


@pytest.fixture(autouse=True)
def _clear_capability_cache() -> Iterator[None]:
    """Reset the memoized capability decision around each test."""
    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


def _patch_registry(monkeypatch: pytest.MonkeyPatch, supported: bool) -> None:
    """Make the registry answer deterministic for this route test."""

    def fake_supports(model: str) -> bool:
        del model
        return supported

    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema", fake_supports
    )


def _capture_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Capture completion kwargs while returning queued fake responses."""
    captured: list[dict[str, Any]] = []
    _patch_acompletion(monkeypatch, responses, captured)
    return captured


async def test_exact_route_injects_schema_at_request_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact route reuses the existing json_object request shim."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    captured = _capture_acompletion(monkeypatch, [_completion(_message("{}"))])

    await call_llm(
        "a prompt",
        CompletionSpec(
            model_name=_MODEL,
            api_key="test-byok-key",
            json_schema=_NESTED_SCHEMA,
        ),
    )

    assert captured[0]["response_format"] == {"type": "json_object"}
    content = captured[0]["messages"][0]["content"]
    assert json.dumps(_NESTED_SCHEMA["schema"], indent=2) in content


async def test_unqualified_gemma_route_keeps_native_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route exception does not broaden to unqualified Gemma models."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    captured = _capture_acompletion(monkeypatch, [_completion(_message("{}"))])

    await call_llm(
        "a prompt",
        CompletionSpec(
            model_name="google/gemma-4-26b-a4b-it",
            api_key="test-byok-key",
            json_schema=_NESTED_SCHEMA,
        ),
    )

    assert captured[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": _NESTED_SCHEMA,
    }
    assert captured[0]["messages"] == [{"role": "user", "content": "a prompt"}]


async def test_exact_route_keeps_local_schema_backfill_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shimmed route still backfills and validates locally."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    captured = _capture_acompletion(
        monkeypatch,
        [_completion(_message('{"summary": "ok", "assessment": {}}'))],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_MODEL,
            api_key="test-byok-key",
            json_schema=_NESTED_SCHEMA,
        ),
        max_attempts=2,
    )

    assert result == {
        "summary": "ok",
        "assessment": {"verdict": "holds", "notes": []},
    }
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert len(captured) == 1


async def test_exact_route_rejects_invalid_enum_then_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local validation rejects an invalid enum before accepting a retry."""
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    captured = _capture_acompletion(
        monkeypatch,
        [
            _completion(
                _message(
                    '{"summary": "ok", "assessment": '
                    '{"verdict": "invalid", "notes": []}}'
                )
            ),
            _completion(
                _message(
                    '{"summary": "ok", "assessment": '
                    '{"verdict": "holds", "notes": []}}'
                )
            ),
        ],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_MODEL,
            api_key="test-byok-key",
            json_schema=_NESTED_SCHEMA,
        ),
        max_attempts=2,
    )

    assert result == {
        "summary": "ok",
        "assessment": {"verdict": "holds", "notes": []},
    }
    assert len(captured) == 2
    assert all(
        request["response_format"] == {"type": "json_object"}
        for request in captured
    )


async def test_exact_free_route_keeps_caps_and_require_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Gemma route keeps the normal zero-price admission policy."""
    _patch_registry(monkeypatch, supported=True)
    catalog = _catalog({"prompt": "0", "completion": "0"})
    catalog["data"][0]["id"] = _MODEL.removeprefix("openrouter/")
    _mock_catalog(monkeypatch, catalog)
    requests: list[dict[str, Any]] = []
    _patch_acompletion(
        monkeypatch,
        [_completion(_message('{"answer": "ok"}'))],
        requests,
    )

    await call_llm_json(
        "probe",
        CompletionSpec(
            model_name=_MODEL,
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        options=LLMCallOptions(use_cache=False),
        max_attempts=1,
    )

    assert requests[0]["response_format"] == {"type": "json_object"}
    provider = requests[0]["extra_body"]["provider"]
    assert provider["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert provider["require_parameters"] is True
    assert requests[0]["api_base"] == "https://openrouter.ai/api/v1"
