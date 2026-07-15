"""Tests for the literature_tools package entry point (``__init__.py``).

Covers the warm-start diagnostic helpers, the MCP-client resolution wrapper,
the per-hypothesis debug logger, and the ``generate_with_tools`` two-phase
orchestration itself. The two phase functions (``draft_hypotheses`` /
``validate_hypotheses``) are stubbed on the module namespace so this file
exercises only the orchestration in ``__init__.py``, not the phases
themselves (those are covered by ``test_literature_tools.py``).
"""

from typing import Any

import pytest

from co_scientist.agents.generation import (
    literature_tools as lit_tools_mod,
)
from co_scientist.models import GenerationMethod, Hypothesis
from tests._state import make_article, make_hypothesis, make_state

# -----------------------------------------------------------------------------
# _count_used_articles / _count_used_articles_with_pdfs
# -----------------------------------------------------------------------------


def test_count_used_articles_counts_only_flagged() -> None:
    """Only articles with used_in_analysis=True are counted."""
    articles = [
        make_article(used_in_analysis=True),
        make_article(used_in_analysis=False),
        make_article(used_in_analysis=True),
    ]
    assert lit_tools_mod._count_used_articles(articles) == 2


def test_count_used_articles_with_pdfs_requires_both_flags() -> None:
    """Only used-and-PDF-backed articles count toward the PDF subset."""
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
        make_article(used_in_analysis=False, pdf_links=["http://b"]),
    ]
    assert lit_tools_mod._count_used_articles_with_pdfs(articles) == 1


# -----------------------------------------------------------------------------
# _log_warm_start_diagnostics
# -----------------------------------------------------------------------------


def test_log_warm_start_diagnostics_none_returns_early() -> None:
    """None articles is a no-op (does not raise)."""
    lit_tools_mod._log_warm_start_diagnostics(None)


def test_log_warm_start_diagnostics_empty_returns_early() -> None:
    """An empty articles list is a no-op (does not raise)."""
    lit_tools_mod._log_warm_start_diagnostics([])


def test_log_warm_start_diagnostics_zero_used_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No used_in_analysis articles logs the fresh-search warning."""
    caplog.set_level("WARNING", logger=lit_tools_mod.__name__)
    articles = [make_article(used_in_analysis=False)]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "agent will search fresh" in caplog.text


def test_log_warm_start_diagnostics_used_with_mixed_pdfs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Used articles log the pdf/abstract-only split, not the warning."""
    caplog.set_level("INFO", logger=lit_tools_mod.__name__)
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
    ]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "Including 2 analyzed articles" in caplog.text
    assert "agent will search fresh" not in caplog.text


# -----------------------------------------------------------------------------
# _get_mcp_client_for_generation
# -----------------------------------------------------------------------------


async def test_get_mcp_client_for_generation_returns_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful get_mcp_client call returns its client unchanged."""
    sentinel = object()

    async def fake_get_mcp_client(**_: Any) -> Any:
        return sentinel

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    result = await lit_tools_mod._get_mcp_client_for_generation(None)
    assert result is sentinel


async def test_get_mcp_client_for_generation_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing get_mcp_client call is logged and re-raised, not swallowed."""

    async def fake_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("mcp unreachable")

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    with pytest.raises(RuntimeError, match="mcp unreachable"):
        await lit_tools_mod._get_mcp_client_for_generation(None)


# -----------------------------------------------------------------------------
# _log_generated_hypothesis_methods
# -----------------------------------------------------------------------------


def test_log_generated_hypothesis_methods_handles_set_and_none() -> None:
    """Logging tolerates both a set generation_method and a None one."""
    hyps = [
        make_hypothesis(
            text="a", generation_method=GenerationMethod.LITERATURE_TOOLS
        ),
        make_hypothesis(text="b", generation_method=None),
    ]
    # No assertion beyond "does not raise": this is a debug-trace helper.
    lit_tools_mod._log_generated_hypothesis_methods(hyps)


# -----------------------------------------------------------------------------
# generate_with_tools
# -----------------------------------------------------------------------------


async def test_generate_with_tools_orchestrates_both_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_with_tools threads the resolved client/registry through.

    Resolves the MCP client and threads it and the registry into both
    phases, returning phase 2's hypotheses unchanged.
    """
    sentinel_client = object()
    sentinel_registry = object()

    async def fake_get_mcp_client(**kwargs: Any) -> Any:
        assert kwargs["tool_registry"] is sentinel_registry
        return sentinel_client

    draft_calls: list[dict[str, Any]] = []
    validate_calls: list[dict[str, Any]] = []

    async def fake_draft_hypotheses(**kwargs: Any) -> list[dict[str, Any]]:
        draft_calls.append(kwargs)
        return [{"text": "draft one"}]

    final_hypotheses = [make_hypothesis(text="validated one")]

    async def fake_validate_hypotheses(**kwargs: Any) -> list[Hypothesis]:
        validate_calls.append(kwargs)
        return final_hypotheses

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)
    monkeypatch.setattr(
        lit_tools_mod, "draft_hypotheses", fake_draft_hypotheses
    )
    monkeypatch.setattr(
        lit_tools_mod, "validate_hypotheses", fake_validate_hypotheses
    )

    state = make_state(
        tool_registry=sentinel_registry,
        articles=[make_article(used_in_analysis=True)],
    )
    result = await lit_tools_mod.generate_with_tools(
        state, count=3, reference_index=None
    )

    assert result == final_hypotheses
    assert draft_calls[0]["count"] == 3
    assert draft_calls[0]["mcp_client"] is sentinel_client
    assert draft_calls[0]["tool_registry"] is sentinel_registry
    assert validate_calls[0]["draft_hypotheses"] == [{"text": "draft one"}]
    assert validate_calls[0]["mcp_client"] is sentinel_client
    assert validate_calls[0]["tool_registry"] is sentinel_registry
