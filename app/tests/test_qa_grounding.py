"""Tests for citation-grounded Q&A: the evidence manifest and message meta.

``build_evidence_manifest`` is a pure function (no DB), so it is tested
directly. Message ``meta`` persistence is exercised through the store with an
isolated per-test database.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.qa import QaRunContext, build_evidence_manifest, build_system_prompt


def _evidence(eid: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": eid,
        "title": f"Title {eid}",
        "source": "PubMed",
        "url": f"https://example/{eid}",
        "year": 2023,
        "available": True,
    }
    base.update(over)
    return base


def _citation(eid: str, state: str) -> dict[str, Any]:
    return {"evidence_id": eid, "state": state, "claim": "c"}


def test_manifest_lists_cited_evidence_first() -> None:
    """Cited evidence is numbered before uncited evidence."""
    evidence = [_evidence("e1"), _evidence("e2"), _evidence("e3")]
    citations = [_citation("e3", "verified"), _citation("e1", "partial")]
    manifest = build_evidence_manifest(evidence, citations)

    # e3 and e1 are cited (in citation order), e2 trails as uncited.
    assert [m["evidence_id"] for m in manifest] == ["e3", "e1", "e2"]
    assert [m["n"] for m in manifest] == [1, 2, 3]
    assert manifest[0]["state"] == "verified"
    assert manifest[1]["state"] == "partial"


def test_system_prompt_enforces_grounding_only() -> None:
    """The Q&A prompt instructs answering only from the run's own artifacts.

    Grounding is the M7 invariant: the assistant must answer from the run's
    hypotheses/reviews/matches/evidence, cite only the numbered manifest, and
    decline rather than draw on outside knowledge.
    """
    prompt = build_system_prompt(
        QaRunContext(
            research_goal="A goal",
            hypotheses=[
                {
                    "title": "H1",
                    "elo_rating": 1200,
                    "win_count": 1,
                    "loss_count": 0,
                }
            ],
            reviews=[],
            matches=[],
            history=[],
            manifest=build_evidence_manifest([_evidence("e1")], []),
        ),
    )
    lowered = prompt.lower()
    # Claims about the run are confined to the run's own artifacts, and the
    # assistant declines rather than filling the gap when they fall short.
    assert "must come only from the artifacts above" in lowered
    assert "do not contain the answer" in lowered
    # It grounds citations to the numbered manifest, never invented ones.
    assert "never invent a citation" in lowered
    # The run's own goal and hypothesis are in the grounding context.
    assert "A goal" in prompt
    assert "H1" in prompt


def test_system_prompt_separates_background_from_run_claims() -> None:
    """Field background is usable as background, but is not citable.

    The audience's lab context is not run evidence. Answering "what is a
    DPD?" from it is correct; citing it as [n] alongside the numbered
    manifest is not, since [n] must resolve to a real retrieved source.
    """
    prompt = build_system_prompt(
        QaRunContext(
            research_goal="A goal",
            hypotheses=[],
            reviews=[],
            matches=[],
            history=[],
            manifest=build_evidence_manifest([_evidence("e1")], []),
        ),
        audience_context="The lab uses Modular Response Analysis.",
    )
    lowered = prompt.lower()
    assert "modular response analysis" in lowered
    assert "never cite it as [n]" in lowered
    # The background is appended after the rule that governs its use.
    assert lowered.index("never cite it as [n]") < lowered.index(
        "modular response analysis"
    )


def test_system_prompt_marks_corpus_catalog_as_prior_work() -> None:
    """The catalog is the group's own papers, not this run's output.

    Its abstracts are quotable and must be attributed by title, but they are
    not in the numbered manifest, so [n] must not be used for them -- and they
    must not be reported as findings this run produced.
    """
    prompt = build_system_prompt(
        QaRunContext(
            research_goal="A goal",
            hypotheses=[],
            reviews=[],
            matches=[],
            history=[],
            manifest=build_evidence_manifest([_evidence("e1")], []),
        ),
        corpus_catalog=(
            "- **Control of cell state transitions** "
            "(paper_id: `control-of-cell-state-transitions`)\n  cSTAR maps "
            "cell states."
        ),
    )
    lowered = prompt.lower()
    assert "control of cell state transitions" in lowered
    assert "attribute anything you take from them by paper title" in lowered
    assert "not results from this run" in lowered


def test_system_prompt_omits_the_corpus_section_when_empty() -> None:
    """No corpus installed must not leave an empty heading in the prompt."""
    prompt = build_system_prompt(
        QaRunContext(
            research_goal="A goal",
            hypotheses=[],
            reviews=[],
            matches=[],
            history=[],
            manifest=build_evidence_manifest([_evidence("e1")], []),
        ),
    )
    assert "published papers" not in prompt.lower()


def test_manifest_keeps_strongest_state_per_evidence() -> None:
    """When an item is cited by several claims, the strongest state wins."""
    evidence = [_evidence("e1")]
    citations = [_citation("e1", "unsupported"), _citation("e1", "verified")]
    manifest = build_evidence_manifest(evidence, citations)
    assert manifest[0]["state"] == "verified"


def test_manifest_marks_uncited_availability() -> None:
    """Uncited evidence is labelled by availability, not a citation state."""
    evidence = [_evidence("e1", available=False)]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["state"] == "unavailable"


def test_manifest_is_capped() -> None:
    """The manifest is bounded to keep the prompt size predictable."""
    evidence = [_evidence(f"e{i}") for i in range(30)]
    manifest = build_evidence_manifest(evidence, [], cap=12)
    assert len(manifest) == 12
    assert manifest[-1]["n"] == 12


def test_manifest_ignores_citations_to_unknown_evidence() -> None:
    """A citation pointing at missing evidence is skipped, not crashed on."""
    evidence = [_evidence("e1")]
    citations = [_citation("ghost", "verified"), _citation("e1", "partial")]
    manifest = build_evidence_manifest(evidence, citations)
    assert [m["evidence_id"] for m in manifest] == ["e1"]
    assert manifest[0]["state"] == "partial"


def test_message_meta_round_trips(isolated_db: str) -> None:
    """A message's structured meta survives a write/read cycle."""
    store.create_run(
        "rg",
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    sources = [{"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}]
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content="Answer [1].",
            kind="qa",
            meta={"sources": sources},
        ),
        db_path=isolated_db,
    )

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 1
    assert msgs[0].meta == {"sources": sources}
    assert msgs[0].to_dict()["meta"] == {"sources": sources}


def test_message_without_meta_is_none(isolated_db: str) -> None:
    """Messages written without meta read back as ``None`` (back-compat)."""
    store.create_run(
        "rg",
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="hi", kind="steering"
        ),
        db_path=isolated_db,
    )
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[0].meta is None
