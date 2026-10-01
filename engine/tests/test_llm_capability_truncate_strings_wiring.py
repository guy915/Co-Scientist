"""End-to-end wiring for the string-truncation shim, through ``call_llm_json``.

Mirrors ``test_llm_capability_truncate_wiring.py`` (the array-truncation
sibling): reuses its network-fake helpers rather than a second
implementation. The pure-function behavior of
``_truncate_oversized_strings`` itself lives in
``test_llm_capability_truncate_strings.py``; these tests only pin that
``call_llm_json`` actually applies it, and only on the downgrade path.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests.test_llm_capability_shim import (
    _capture_acompletion,
    _completion,
    _patch_registry,
)


@pytest.fixture(autouse=True)
def _clear_capability_cache() -> Iterator[None]:
    """Reset the memoized capability probe around each test.

    The shim test module has an identically-named fixture, but an autouse
    fixture does not apply across modules, so this file needs its own.
    """
    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


_MAX_LENGTH_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_max_length",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 20},
        },
        "required": ["title"],
    },
}

_LONG_TITLE = json.dumps({"title": "this title runs well past the cap"})


async def test_call_llm_json_truncates_oversized_string_on_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the downgrade path, an over-long string is trimmed to its cap.

    Mirrors the production failure (run b82f9162): a title a few
    characters over ``maxLength`` discarded a whole response. Without the
    truncation, the closed cap rejects the response and every retry
    rejects the same title again; with it, the first attempt validates.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(monkeypatch, [_completion(_LONG_TITLE)])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_MAX_LENGTH_SCHEMA),
        max_attempts=2,
    )

    assert len(result["title"]) <= 20
    assert len(captured) == 1  # validated on the first attempt, no retry


async def test_call_llm_json_no_truncate_for_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema-enforcing provider is trusted: the same over-long string fails.

    Proves the truncation is keyed on the downgrade condition rather than
    applied globally -- where the provider enforces ``maxLength`` itself,
    an over-long string is a real anomaly and stays a validation failure.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    long_title = _completion(_LONG_TITLE)
    _capture_acompletion(monkeypatch, [long_title, long_title])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model", json_schema=_MAX_LENGTH_SCHEMA
            ),
            max_attempts=2,
        )
