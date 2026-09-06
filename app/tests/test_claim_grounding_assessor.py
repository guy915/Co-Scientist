"""Assessor selection, LLM provenance, and assessment concurrency (M5).

Split out of ``test_claim_grounding.py`` when that file passed the
module-size budget. That file covers what grounding *persists and gates*;
this one covers *which assessor runs and how* -- the deterministic/LLM
choice, the provenance spans an LLM assessor's own quotes produce, and the
two properties that keep assessment off the SQLite writer: it holds no
connection, and it overlaps its per-claim provider calls.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.claim_grounding import (
    AssessorSpec,
    GroundingTarget,
    build_assessor,
    evidence_passages,
    ground_hypotheses,
)
from app.claims import AssessorDraft, EntailmentLabel, as_passages
from tests._store_helpers import _add

# A claim the seeded pubmed abstract supports, so a run's verdict turns on
# which assessor produced it rather than on whether the evidence bears out.
_SUPPORTED = "A dietary change improves cardiovascular outcomes in adults."


def _may_call_out(monkeypatch: Any) -> None:
    """Put the process in the state where a provider call is permissible."""
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


def test_build_assessor_selects_by_mode(monkeypatch: Any) -> None:
    """`build_assessor` returns the deterministic or LLM assessor by mode.

    Explicit about the process state because mode is no longer the only
    input: an offline process takes the deterministic assessor whatever the
    mode says, which the test below covers.
    """
    _may_call_out(monkeypatch)

    _, det_id = build_assessor("deterministic", "unused")
    assert det_id == "deterministic-v1"
    _, llm_id = build_assessor("llm", "deepseek/deepseek-chat")
    assert llm_id == "llm:deepseek/deepseek-chat"


def test_offline_never_builds_the_assessor_that_calls_a_provider(
    monkeypatch: Any,
) -> None:
    """Mode says "llm", the process is offline, and nothing is billed.

    ``claim_assessor`` defaults to ``"llm"`` and this call site never passed
    through the engine's offline router, so a run the whole system believed
    was offline still sent one real provider call per claim group against
    whatever credential was in the environment -- 177 of them in a single
    offline ``make parity`` run. A credential is deliberately present here,
    since its presence is exactly what made the leak spend money.
    """
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-have-been-billed")

    _, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")

    assert assessor_id == "deterministic-v1"


def _ev_completion(ev_id: str) -> Any:
    """A faked litellm.acompletion citing ``ev_id`` so its span locates."""
    import types

    async def _completion(**_kwargs: Any) -> Any:
        content = (
            '{"label": "supports", "supporting": '
            f'[{{"evidence_id": "{ev_id}", '
            '"quote": "reduces melanoma tumor growth"}], '
            '"contradicting": []}'
        )
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    return _completion


def _seed_llm_assessor(db_path: str) -> tuple[Any, str, str]:
    """Seed a supported hypothesis + a pubmed evidence row for LLM grounding."""
    run = store.create_run("grounding goal", "standard", "engine", {})
    hyp_id = _add(
        run.id,
        "Supported",
        "Inhibiting kinase X reduces melanoma tumor growth in mouse models.",
        db_path,
    )
    ev_id = store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Kinase X melanoma study",
            source="pubmed",
            url="https://example.org/ev",
            abstract=(
                "Kinase X inhibition reduces melanoma tumor growth markedly."
            ),
        ),
        db_path=db_path,
    )
    return run, hyp_id, ev_id


def test_ground_with_llm_assessor_persists_provenance(
    isolated_db: str, monkeypatch: Any
) -> None:
    """Grounding with the LLM assessor (faked) persists llm-tagged spans."""
    import litellm
    from co_scientist.cache import scoped_cache_override

    _may_call_out(monkeypatch)
    run, hyp_id, ev_id = _seed_llm_assessor(isolated_db)
    # The faked model cites the real evidence id so the span locates.
    monkeypatch.setattr(litellm, "acompletion", _ev_completion(ev_id))

    assessor, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")
    with scoped_cache_override(False):
        ground_hypotheses(
            run.id,
            store.list_hypotheses(run.id),
            evidence_passages(run.id, db_path=isolated_db),
            assessment=AssessorSpec(assessor, assessor_id),
            target=GroundingTarget(db_path=isolated_db),
        )

    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    edge = next(e for e in edges if e["hypothesis_id"] == hyp_id)
    assert edge["assessor"] == "llm:deepseek/deepseek-chat"
    span = edge["supporting"][0]
    assert span["evidence_id"] == ev_id
    assert span["quote"] == "reduces melanoma tumor growth"
    assert span["url"] == "https://example.org/ev"


def test_ground_records_provenance_spans_round_trip(isolated_db: str) -> None:
    """A provenance-stamped support span round-trips through the store."""
    run = store.create_run("grounding goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    span = {
        "evidence_id": "ev-9",
        "quote": "reduces tumor growth",
        "start": 12,
        "end": 32,
        "source": "pubmed",
        "url": "https://example.org/9",
    }
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A supported claim.",
            label="supports",
            supporting=[span],
            contradicting=[],
            assessor="llm:deepseek/deepseek-chat",
        ),
        db_path=isolated_db,
    )
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    assert edges[0]["supporting"] == [span]
    assert edges[0]["assessor"] == "llm:deepseek/deepseek-chat"


def test_claim_assessment_holds_no_database_connection(
    isolated_db: str,
) -> None:
    """Assessing claims must be possible without touching the database.

    The assessor can be an LLM, and in production one synchronous call per
    claim ran inside the drain's single write transaction -- so the process
    held SQLite's one write lock across minutes of provider I/O. Everything
    else starved: run creation returned 500 with "database is locked" while
    the database itself sat idle, and a stack dump found the finalize task
    parked in ssl.read with the lock in hand.

    Separating assessment from persistence is what lets the drain do the
    provider work before it opens a transaction.
    """
    import sqlite3

    from app.claim_grounding import assess_hypothesis_claims

    hyp = {"id": "h1", "title": "Kinase X inhibition", "statement": _SUPPORTED}

    # Hold the write lock for the whole assessment; it must not care.
    blocker = sqlite3.connect(isolated_db, timeout=0.5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        assessed = assess_hypothesis_claims([hyp], as_passages([_SUPPORTED]))
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert [hyp_id for hyp_id, _ in assessed] == ["h1"]
    assert all(claims for _, claims in assessed)


def test_claim_assessment_runs_concurrently(isolated_db: str) -> None:
    """Claims must be assessed in parallel, not one provider call at a time.

    Every claim of every hypothesis is assessed independently, and with the
    LLM assessor each is a synchronous provider call. Run serially that is
    the longest phase of a finished run -- a stack dump caught finalize
    sitting in it for hours. The provider is not the constraint: measured on
    the production model, twenty-four concurrent completions return in the
    same wall clock as four. Assessments are independent, so overlapping
    them changes nothing about the verdicts.
    """
    import threading
    import time as _time

    from app.claim_grounding import assess_hypothesis_claims

    active = 0
    peak = 0
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> Any:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        _time.sleep(0.05)
        with lock:
            active -= 1
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    hyps = [
        {"id": f"h{i}", "title": f"H{i}", "statement": _SUPPORTED}
        for i in range(8)
    ]
    from app.claim_grounding_assess import AssessorSpec

    assess_hypothesis_claims(
        hyps, as_passages([_SUPPORTED]), AssessorSpec(_slow_assessor)
    )

    assert peak > 1, f"claims were assessed serially (peak concurrency {peak})"


def test_batch_assessor_costs_one_call_per_hypothesis(isolated_db: str) -> None:
    """13 hypotheses of ~17 claims each cost 13 calls, not 218.

    Regression for the production measurement (ultra run b82f9162): the
    per-claim path issued one provider call per atomic claim (218 calls
    across 13 hypotheses in a single pass); the batch path costs one call
    per hypothesis instead.
    """
    calls = {"n": 0}

    from app.claim_grounding import assess_hypothesis_claims

    def _batch(claims: Any, passages: Any) -> Any:
        calls["n"] += 1
        return [AssessorDraft(label=EntailmentLabel.INSUFFICIENT)] * len(claims)

    statement = " ".join(
        f"Claim number {i} about a dietary change improving outcomes."
        for i in range(17)
    )
    hyps = [
        {"id": f"h{i}", "title": f"H{i}", "statement": statement}
        for i in range(13)
    ]

    assessed = assess_hypothesis_claims(
        hyps,
        as_passages([_SUPPORTED]),
        AssessorSpec(assessor_id="llm:test-model", batch_assessor=_batch),
    )

    assert calls["n"] == 13
    assert len(assessed) == 13
    assert all(len(claims) == 17 for _, claims in assessed)


def test_batch_assessor_splits_a_claim_dense_hypothesis(
    isolated_db: str,
) -> None:
    """One hypothesis with 25 claims costs two calls, not one giant call."""
    calls = {"n": 0}

    from app.claim_grounding import assess_hypothesis_claims

    def _batch(claims: Any, passages: Any) -> Any:
        calls["n"] += 1
        return [AssessorDraft(label=EntailmentLabel.INSUFFICIENT)] * len(claims)

    statement = " ".join(
        f"Claim number {i} about a dietary change improving outcomes."
        for i in range(25)
    )
    hyps = [{"id": "h0", "title": "H0", "statement": statement}]

    assessed = assess_hypothesis_claims(
        hyps,
        as_passages([_SUPPORTED]),
        AssessorSpec(assessor_id="llm:test-model", batch_assessor=_batch),
    )

    assert calls["n"] == 2
    assert len(assessed[0][1]) == 25
