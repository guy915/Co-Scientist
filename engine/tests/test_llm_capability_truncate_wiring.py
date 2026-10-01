"""End-to-end wiring for the array-truncation shim, through ``call_llm_json``.

Split from ``test_llm_capability_shim.py`` on size (that file's own
back-fill and prune wiring sections were already split into their pure
counterparts for the same reason): reuses its network-fake helpers rather
than a second implementation. The pure-function behavior of
``_truncate_oversized_arrays`` itself lives in
``test_llm_capability_truncate.py``; these tests only pin that
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


_MAX_ITEMS_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_max_items",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            }
        },
        "required": ["steps"],
    },
}

_SIX_STEPS = json.dumps({"steps": ["a", "b", "c", "d", "e", "f"]})


async def test_call_llm_json_truncates_oversized_array_on_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the downgrade path, an over-long array is trimmed to its cap.

    The exact production failure (run 44e848fb): six perfectly good
    experiment-plan steps against a ``maxItems: 5`` schema. Without the
    truncation, the closed cap rejects the response and every retry
    rejects the same six steps again; with it, the first attempt validates.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=False)
    captured = _capture_acompletion(monkeypatch, [_completion(_SIX_STEPS)])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_MAX_ITEMS_SCHEMA),
        max_attempts=2,
    )

    assert result == {"steps": ["a", "b", "c", "d", "e"]}
    assert len(captured) == 1  # validated on the first attempt, no retry


async def test_call_llm_json_no_truncate_for_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema-enforcing provider is trusted: the same over-long array fails.

    Proves the truncation is keyed on the downgrade condition rather than
    applied globally -- where the provider enforces ``maxItems`` itself, an
    over-long array is a real anomaly and stays a validation failure.
    """
    _disable_cache(monkeypatch)
    _patch_registry(monkeypatch, supported=True)
    six_steps = _completion(_SIX_STEPS)
    _capture_acompletion(monkeypatch, [six_steps, six_steps])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model", json_schema=_MAX_ITEMS_SCHEMA
            ),
            max_attempts=2,
        )
