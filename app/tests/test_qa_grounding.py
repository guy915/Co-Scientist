"""Tests for citation-grounded Q&A: the evidence manifest and message meta.

``_build_evidence_manifest`` is a pure function (no DB), so it is tested
directly. Message ``meta`` persistence is exercised through the store with an
isolated per-test database.
"""
# pylint: disable=unused-argument
from __future__ import annotations

from typing import Any

from app import store
from app.runs import _build_evidence_manifest


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
    manifest = _build_evidence_manifest(evidence, citations)

    # e3 and e1 are cited (in citation order), e2 trails as uncited.
    assert [m["evidence_id"] for m in manifest] == ["e3", "e1", "e2"]
    assert [m["n"] for m in manifest] == [1, 2, 3]
    assert manifest[0]["state"] == "verified"
    assert manifest[1]["state"] == "partial"


def test_manifest_keeps_strongest_state_per_evidence() -> None:
    """When an item is cited by several claims, the strongest state wins."""
    evidence = [_evidence("e1")]
    citations = [_citation("e1", "unsupported"), _citation("e1", "verified")]
    manifest = _build_evidence_manifest(evidence, citations)
    assert manifest[0]["state"] == "verified"


def test_manifest_marks_uncited_availability() -> None:
    """Uncited evidence is labelled by availability, not a citation state."""
    evidence = [_evidence("e1", available=False)]
    manifest = _build_evidence_manifest(evidence, [])
    assert manifest[0]["state"] == "unavailable"


def test_manifest_is_capped() -> None:
    """The manifest is bounded to keep the prompt size predictable."""
    evidence = [_evidence(f"e{i}") for i in range(30)]
    manifest = _build_evidence_manifest(evidence, [], cap=12)
    assert len(manifest) == 12
    assert manifest[-1]["n"] == 12


def test_manifest_ignores_citations_to_unknown_evidence() -> None:
    """A citation pointing at missing evidence is skipped, not crashed on."""
    evidence = [_evidence("e1")]
    citations = [_citation("ghost", "verified"), _citation("e1", "partial")]
    manifest = _build_evidence_manifest(evidence, citations)
    assert [m["evidence_id"] for m in manifest] == ["e1"]
    assert manifest[0]["state"] == "partial"


def test_message_meta_round_trips(isolated_db: str) -> None:
    """A message's structured meta survives a write/read cycle."""
    store.create_run("rg",
                     "default",
                     "engine", {},
                     client_id="c1",
                     db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    sources = [{"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}]
    store.append_message(run_id,
                         "system",
                         "Answer [1].",
                         "qa",
                         db_path=isolated_db,
                         meta={"sources": sources})

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 1
    assert msgs[0].meta == {"sources": sources}
    assert msgs[0].to_dict()["meta"] == {"sources": sources}


def test_message_without_meta_is_none(isolated_db: str) -> None:
    """Messages written without meta read back as ``None`` (back-compat)."""
    store.create_run("rg",
                     "default",
                     "engine", {},
                     client_id="c1",
                     db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id
    store.append_message(run_id,
                         "user",
                         "hi",
                         "steering",
                         db_path=isolated_db)
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[0].meta is None
