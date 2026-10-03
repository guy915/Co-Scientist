"""Drain persistence of the proposer's own safety assessment (MO-10).

Split out of ``test_engine_drain.py`` to keep that module within the size
cap once this test was added alongside the module's existing MO-6
(scene-setting) test. Safety and toxicity is distinct from a reviewer's
safety_ethical_concerns and never consulted by the safety gate.
"""

from __future__ import annotations

from app import store
from app.engine_adapter.drain.hypotheses import _authored_title
from tests._drain_helpers import _engine_hypothesis, _persist


def test_persist_writes_safety_and_toxicity_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """The proposer's own safety assessment (MO-10) reaches the row.

    Distinct from a reviewer's safety_ethical_concerns: this is the
    proposal's own field, and must never be consulted by the safety gate.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-safety",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                safety_and_toxicity=(
                    "Limited human safety data exists for this class."
                ),
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    _persist(
        run_id=run.id,
        final_state=final_state,
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["safety_and_toxicity"] == (
        "Limited human safety data exists for this class."
    )


_STATEMENT = "Blocking CXCR1 suppresses breast cancer stem cells. It works."


def test_authored_title_used_verbatim_when_present() -> None:
    """An LLM-authored title is preferred over the derived one."""
    title = _authored_title(
        {"title": "CXCR1 Blockade Against Breast Cancer Stem Cells"},
        _STATEMENT,
    )
    assert title == "CXCR1 Blockade Against Breast Cancer Stem Cells"


def test_authored_title_falls_back_when_field_absent() -> None:
    """A payload with no title key falls back exactly as it did before."""
    assert _authored_title({}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_malformed() -> None:
    """A non-string title (a json_object-downgrade artifact) degrades safely."""
    assert _authored_title({"title": ["not", "a", "string"]}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": 42}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_blank() -> None:
    """An empty or whitespace-only title falls back rather than persisting."""
    assert _authored_title({"title": ""}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": "   \n\t"}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_is_clipped_past_the_display_cap() -> None:
    """A title over the cap is clipped, not discarded back to the fallback."""
    long_title = "A" * 150
    title = _authored_title({"title": long_title}, _STATEMENT)
    assert title == "A" * 120
    assert len(title) == 120


def test_persist_writes_the_authored_title_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """The authored title (not first_sentence) reaches the store row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-title",
                _STATEMENT,
                title="CXCR1 Blockade Against Breast Cancer Stem Cells",
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["title"] == "CXCR1 Blockade Against Breast Cancer Stem Cells"


def test_persist_derives_the_title_for_an_evolved_child_without_one(
    isolated_db: str,
) -> None:
    """An evolved child with no authored title falls back to its own text.

    Not the parent's title: the child's mechanism may have diverged, so
    first_sentence(child.text) is the right fallback, never the parent's
    (possibly stale) title.
    """
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "parent-1",
                "Parent hypothesis about kinase X. Details follow.",
                title="Kinase X Inhibition Strategy",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Child hypothesis: kinase X plus cofactor W. More detail.",
                parent_id="parent-1",
                generation=1,
                origin="evolution",
                # No authored title on this response -- json_object
                # downgrade, or the evolution LLM simply omitted it.
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert hyps["parent-1"]["title"] == "Kinase X Inhibition Strategy"
    assert hyps["child-1"]["title"] == (
        "Child hypothesis: kinase X plus cofactor W"
    )
