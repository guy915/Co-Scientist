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


def _final_state_with_novelty_review() -> dict[str, Any]:
    """A final state whose hypothesis carries the published novelty review."""
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-n",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                reviews=[
                    {
                        "review_summary": "Sound, moderately novel.",
                        "scores": {"novelty": 6},
                        "safety_ethical_concerns": "",
                        "detailed_feedback": {},
                        "constructive_feedback": "Tighten the controls.",
                        "overall_score": 6.0,
                        "already_explored": [
                            "CXCR1 is a known breast-CSC marker."
                        ],
                        "novel_aspects": [
                            "The proposed feedback loop is new."
                        ],
                    }
                ],
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_writes_novelty_review_lists_into_critique(
    isolated_db: str,
) -> None:
    """The published Aspects-already-explored/Novel-Aspects lists reach the reader (MO-3)."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_novelty_review(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    review = next(r for r in reviews if r["reviewer_agent"] == "review")
    assert "Aspects already explored:" in review["critique"]
    assert "CXCR1 is a known breast-CSC marker." in review["critique"]
    assert "Novel Aspects:" in review["critique"]
    assert "The proposed feedback loop is new." in review["critique"]
    # The plain constructive-feedback content is preserved too.
    assert "Tighten the controls." in review["critique"]


def _final_state_with_mature_reviews() -> dict[str, Any]:
    """A final state whose hypothesis carries all three mature reviews."""
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-m",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                enrichments={
                    "full": {
                        "verdict": "rejected",
                        "correctness": "The pathway claim is circular.",
                        "quality_and_novelty": "Incremental.",
                        "literature_grounding": "Thin.",
                        "justification": "Circular pathway reasoning.",
                        "assumptions": [
                            {
                                "assumption": "CXCR1 is the only driver",
                                "reasoning": (
                                    "Two other chemokine receptors are"
                                    " independently sufficient."
                                ),
                                "support": "likely_false",
                            }
                        ],
                        "retrieved_articles": [{"title": "not persisted"}],
                    },
                    "simulation": {
                        "verdict": "breaks_down",
                        "model": "Xenograft simulation",
                        "steps": [{"step": "ligand binds", "plausible": False}],
                        "failure_points": ["binding never occurs"],
                        "robustness": "Fragile.",
                        "decisive_step": "Step one fails.",
                    },
                    "recurrent": {
                        "verdict": "needs_revision",
                        "justification": "Still circular after review.",
                    },
                },
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_persist_writes_distinct_mature_review_rows(isolated_db: str) -> None:
    """Full/simulation/recurrent results reach the reader as labeled rows.

    They used to stop at the engine's enrichments (audit E1): nothing the
    report reader could see. Each becomes its own review row under a
    distinct reviewer_agent, with the verdict as the summary.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_mature_reviews(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    by_agent = {r["reviewer_agent"]: r for r in reviews}
    assert set(by_agent) == {
        "full_review",
        "simulation_review",
        "recurrent_review",
    }
    assert by_agent["full_review"]["summary"] == (
        "Full review verdict: rejected"
    )
    assert "Circular pathway reasoning." in by_agent["full_review"]["critique"]
    assert "CXCR1 is the only driver" in by_agent["full_review"]["critique"]
    # The published free-text reasoning paragraph (MO-9) rides alongside
    # the assumption and its support verdict.
    assert (
        "Two other chemokine receptors are independently sufficient."
        in by_agent["full_review"]["critique"]
    )
    assert by_agent["simulation_review"]["summary"] == (
        "Simulation review verdict: breaks_down"
    )
    assert "binding never occurs" in by_agent["simulation_review"]["critique"]
    assert by_agent["recurrent_review"]["summary"] == (
        "Recurrent review verdict: needs_revision"
    )
    # Retrieval bookkeeping never reaches the persisted row.
    assert "not persisted" not in str(by_agent)


def _citations_citation_map() -> dict[str, Any]:
    """Three citations engineered to land in three distinct citation states.

    Once routed through ``classify_citation``: a retrieved paper whose abstract
    overlaps the grounding (verified), a paper with a URL but no retrieved
    abstract (unsupported), and a knowledge-graph source with no URL
    (unavailable).
    """
    return {
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
    }


def _final_state_with_citations() -> dict[str, Any]:
    """A minimal final state whose hypothesis cites three distinct sources."""
    grounding = "CXCR1 signaling drives breast cancer stem cell renewal"
    return {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-a",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                literature_grounding=grounding,
                citation_map=_citations_citation_map(),
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


def test_a_knowledge_graph_citations_evidence_row_keeps_its_display_text(
    isolated_db: str,
) -> None:
    """A non-paper citation's evidence title must not become its bare key.

    ``_persist_one_citation`` fell back to the [C*] key itself
    (``cite_info.get("title", cite_key)``) whenever a source carried no
    "title" -- true of every non-paper source, which is keyed by "display"
    instead (see ``citations._enrichment_reference_entries``). A run citing
    an INDRA statement therefore persisted an evidence row titled literally
    "C3" rather than the statement it names.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_citations(),
        db_path=isolated_db,
    )

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    kg_row = next(e for e in evidence if e["source"] == "knowledge_graph")
    assert kg_row["title"] == "INDRA: CXCR1 -> STAT3"


def _final_state_with_multi_source_grounding() -> dict[str, Any]:
    """A run-shaped grounding: several sentences, each citing its own paper.

    The single-sentence fixture above cannot distinguish a citation matched
    against the sentence that cites it from one matched against the whole
    paragraph, because there is only one sentence. A real grounding is a
    synthesis paragraph spanning every source, and each abstract restates
    only its own sentence.
    """
    grounding = (
        "CXCR1 signaling drives breast cancer stem cell renewal [C1]. "
        "Hypoxia-inducible factor stabilization expands the perivascular "
        "niche in glioma [C2]. "
        "The proposed coupling between the two is an extension of both."
    )
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
                    },
                    "C2": {
                        "type": "paper",
                        "title": "HIF expands the glioma niche",
                        "url": "https://example.org/c2",
                    },
                },
            )
        ],
        "articles": [
            {
                "title": "CXCR1 drives CSC renewal",
                "url": "https://example.org/c1",
                "abstract": (
                    "CXCR1 signaling drives breast cancer stem cell renewal "
                    "across xenograft models."
                ),
            },
            {
                "title": "HIF expands the glioma niche",
                "url": "https://example.org/c2",
                "abstract": (
                    "Hypoxia-inducible factor stabilization expands the "
                    "perivascular niche in glioma xenografts."
                ),
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


def test_each_citation_is_scored_against_the_sentence_that_cites_it(
    isolated_db: str,
) -> None:
    """A multi-source grounding must not make every citation unsupported.

    Coverage is measured over the claim's own vocabulary, so handing the
    classifier the whole grounding paragraph divides each source's real
    overlap by every other source's words too. In one live run the best of
    27 citations scored 0.23 against a 0.30 "partial" line, so a run whose
    every citation was retrieved and on-point still reported 0 verified,
    0 partial, 33 unsupported -- the same unreachable-upper-states failure
    the Jaccard fix removed, arriving by a different route.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_final_state_with_multi_source_grounding(),
        db_path=isolated_db,
    )

    citations = store.list_citations(run.id, db_path=isolated_db)
    states = {c["claim"]: c["state"] for c in citations}
    assert states == {
        "[C1] cited in hypothesis": "verified",
        "[C2] cited in hypothesis": "verified",
    }
