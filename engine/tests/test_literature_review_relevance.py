from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.evidence import relevance, search
from co_scientist.offline import llm as offline_llm
from tests._llm_fake import mock_call_llm_json
from tests._research_fakes import _stub_node
from tests._state import make_state


def _candidate(title: str, lexical_score: float) -> dict[str, object]:
    return {
        "title": title,
        "abstract": f"Abstract for {title}.",
        "retrieval_score": lexical_score,
    }


def _pool(n: int) -> dict[str, dict[str, object]]:
    return {
        f"p{i}": _candidate(f"Paper {i}", 1.0 - i / (n + 1))
        for i in range(1, n + 1)
    }


async def _ranked_review(
    monkeypatch: pytest.MonkeyPatch,
    pool: dict[str, Any],
    *,
    goal: str = "goal",
    count: int | None = None,
) -> dict[str, Any]:
    _stub_node(monkeypatch, server_available=True, search_payload=pool)
    monkeypatch.setattr(
        search, "merge_search_results", lambda *args, **kwargs: (pool, {})
    )
    result = await literature_review_node(
        make_state(
            research_goal=goal,
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            literature_review_papers_count=len(pool)
            if count is None
            else count,
        )
    )
    return {article.source_id: article for article in result["articles"]}


async def test_review_semantic_failure_preserves_lexical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_call_llm_json(
        monkeypatch, relevance, side_effect=RuntimeError("provider exploded")
    )
    papers = await _ranked_review(monkeypatch, _pool(2))
    assert len(papers) == 2
    assert all(
        article.retrieval_rationale == relevance._FAILED_JUDGMENT_RATIONALE
        for article in papers.values()
    )


async def test_review_with_negative_budget_keeps_only_lexical_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_judgment(**_: Any) -> Any:
        pytest.fail("A nonpositive budget must not purchase semantic judgments")

    monkeypatch.setattr(relevance, "call_llm_json", unexpected_judgment)
    result = await _ranked_review(
        monkeypatch,
        {
            "low": _candidate("Low", -0.2),
            "high": _candidate("High", 1.5),
            "spare": _candidate("Spare", 0.5),
        },
        count=-1,
    )
    assert result["low"].retrieval_score == 0.0
    assert result["high"].retrieval_score == 1.0
    assert all(
        article.retriever_version == relevance._LEXICAL_ONLY_VERSION
        for article in result.values()
    )
