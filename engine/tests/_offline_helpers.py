"""Shared helpers for the offline LLM router test suites.

Leading underscore so pytest does not collect this module.
"""

import pytest

from co_scientist import offline_llm
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)
from tests._llm_backend_fake import restore_backend_at_teardown


def isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time.

    ``install_offline_router`` installs a backend process-wide, so a permanent
    install in one test would otherwise leak into every later test in the
    process. Registering the installed backend for restoration at teardown,
    and resetting the module's own idempotency flag, guarantees a fresh
    install every test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    restore_backend_at_teardown(monkeypatch)
    monkeypatch.setattr(offline_llm, "_installed", False)


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
