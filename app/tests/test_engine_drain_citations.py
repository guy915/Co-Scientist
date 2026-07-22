"""Engine-drain tests for citations and deep-verification reviews.

Split out of ``test_engine_drain.py`` by concern. These cover the drain's
citation classification through the shared four-state classifier and the
persistence of deep-verification probes as review rows. Shared builders live in
``tests/_drain_helpers.py``.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, store
from tests._drain_helpers import _engine_hypothesis, _final_state_with_features


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    """Hypotheses with probes get a deep_verification review row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    # Only the first hypothesis has probes.
    assert len(deep) == 1
    critique = deep[0]["critique"]
    assert "Does CXCR1 signaling drive the stem-cell phenotype?" in critique
    assert "CXCR2 can compensate when CXCR1 is blocked." in critique
    assert (
        "weakened" in deep[0]["summary"].lower()
        or "weakened" in critique.lower()
    )
    # Score columns are not produced by deep verification.
    assert deep[0]["novelty"] is None
    assert deep[0]["overall"] is None


def _final_state_with_citations() -> dict[str, Any]:
    """A minimal final state whose hypothesis cites three distinct sources.

    The three citations are engineered to land in three different citation
    states once routed through ``classify_citation``: a retrieved paper whose
    abstract overlaps the grounding (verified), a paper with a URL but no
    retrieved abstract (unsupported), and a knowledge-graph source with no URL
    (unavailable).
    """
    grounding = "CXCR1 signaling drives breast cancer stem cell renewal"
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-a",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                literature_grounding=grounding,
                citation_map={
                    "C1": {
                        "type": "paper",
                        "title": "CXCR1 drives CSC renewal",
                        "url": "https://example.org/c1",
                        "authors": ["Smith"],
                        "year": 2023,
                    },
                    "C2": {
                        "type": "paper",
                        "title": "Unrelated off-target study",
                        "url": "https://example.org/c2",
                        "authors": ["Doe"],
                        "year": 2021,
                    },
                    "C3": {
                        "type": "knowledge_graph",
                        "display": "INDRA: CXCR1 -> STAT3",
                    },
                },
            )
        ],
        "articles": [
            {
                "title": "CXCR1 drives CSC renewal",
                "url": "https://example.org/c1",
                "abstract": "CXCR1 signaling drives breast cancer stem "
                "cell renewal across xenograft models.",
                "authors": ["Smith"],
                "year": 2023,
            }
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_classifies_citations_via_shared_classifier(
    isolated_db: str,
) -> None:
    """Engine citations run through classify_citation, not a hardcoded state.

    Regression guard: the drain previously stamped every citation "verified",
    leaving the four-state citation UI dead for real runs. Each source must now
    resolve to the state its content warrants.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    citations = store.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "unsupported",
        "[C3] cited in hypothesis": "unavailable",
    }
