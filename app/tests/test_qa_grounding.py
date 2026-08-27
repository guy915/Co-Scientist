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
    assert "must come only from the context above" in lowered
    assert "do not contain the answer" in lowered
    # It grounds citations to the numbered manifest, never invented ones.
    assert "never invent a citation" in lowered
    # The run's own goal and hypothesis are in the grounding context.
    assert "A goal" in prompt
    assert "H1" in prompt


def test_manifest_keeps_strongest_state_per_evidence() -> None:
    """When an item is cited by several claims, the strongest state wins."""
    evidence = [_evidence("e1")]
    citations = [_citation("e1", "unsupported"), _citation("e1", "verified")]
    manifest = build_evidence_manifest(evidence, citations)
    assert manifest[0]["state"] == "verified"


def test_manifest_marks_uncited_availability() -> None:
    """Uncited, available evidence is labelled by its availability flag."""
    evidence = [_evidence("e1", available=True)]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["state"] == "available"


def test_manifest_withholds_unavailable_evidence() -> None:
    """Uncited evidence that could not be resolved is withheld, not listed.

    An unavailable source has no content the model could ground a citation
    in, so it must not enter the numbered list at all -- there is nothing
    for [n] to point at.
    """
    evidence = [_evidence("e1", available=False)]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest == []


def test_manifest_withholds_unsupported_citations() -> None:
    """A citation checked and found not to support its claim is withheld.

    Letting it into the context under the "unsupported" label still invites
    the model to cite it as though it were evidence.
    """
    evidence = [_evidence("e1"), _evidence("e2")]
    citations = [_citation("e1", "unsupported"), _citation("e2", "verified")]
    manifest = build_evidence_manifest(evidence, citations)
    assert [m["evidence_id"] for m in manifest] == ["e2"]


def test_manifest_includes_grounding_passage() -> None:
    """A source with an abstract carries a bounded passage to cite against.

    Not just a title.
    """
    evidence = [_evidence("e1", abstract="This paper shows X causes Y.")]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["passage"] == "This paper shows X causes Y."


def test_manifest_passage_is_none_without_an_abstract() -> None:
    """A source with no abstract carries no passage, rather than a blank."""
    evidence = [_evidence("e1")]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["passage"] is None


def test_manifest_passage_is_truncated() -> None:
    """A very long abstract is bounded so it cannot dominate the prompt."""
    evidence = [_evidence("e1", abstract="x" * 2000)]
    manifest = build_evidence_manifest(evidence, [])
    passage = manifest[0]["passage"]
    assert passage is not None
    assert len(passage) < 700
    assert passage.endswith("…")


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
