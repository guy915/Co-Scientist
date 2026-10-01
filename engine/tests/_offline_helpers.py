"""Shared helpers for the offline LLM router test suites.

Leading underscore so pytest does not collect this module.
"""

import litellm
import pytest

from co_scientist import offline_llm
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)
from co_scientist.llm.request import completion


def isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time.

    ``install_offline_router`` mutates real module attributes directly
    (not through ``monkeypatch``), so a permanent install in one test
    would otherwise leak into every later test in the process. Recording
    the current value of each patched attribute with ``monkeypatch``
    (even when re-set to itself) registers it for automatic restoration
    at teardown, and resetting the module's own idempotency bookkeeping
    guarantees a fresh install every test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(litellm, "acompletion", litellm.acompletion)
    monkeypatch.setattr(
        completion,
        "_supports_json_schema_response_format",
        completion._supports_json_schema_response_format,
    )
    monkeypatch.setattr(offline_llm, "_installed", False)
    monkeypatch.setattr(offline_llm, "_original_acompletion", None)
    monkeypatch.setattr(offline_llm, "_original_supports_json_schema", None)


def make_offline_generator() -> HypothesisGenerator:
    """Builds the small single-iteration generator offline runs use."""
    return HypothesisGenerator(
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
        ),
    )
