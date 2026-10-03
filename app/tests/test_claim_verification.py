from __future__ import annotations

import json
import sqlite3
import types
from collections.abc import Sequence
from typing import Any

import pytest
from co_scientist.cache import scoped_cache_override
from litellm.exceptions import RateLimitError

from app import store
from app.claims import (
    AssessorDraft,
    EvidencePassage,
    _downgrade_unproven_label,
    as_passages,
    assess_claim,
)
from app.claims import EntailmentLabel as OppositionEntailmentLabel
from app.claims import (
    EntailmentLabel as ProvenanceEntailmentLabel,
)
from app.claims.gate import (
    DEFAULT_CLAIM_ROLE,
    ClaimAssessment,
    ClaimRole,
    claim_status,
    is_categorical_contradiction,
    is_contradicting,
    is_excused,
    is_speculative,
    is_supporting,
    knowledge_kind,
    label_of,
    role_of,
)
from app.claims.gate import EntailmentLabel as MatrixEntailmentLabel
from app.claims.gate import EntailmentLabel as VerdictEntailmentLabel
from app.claims.gate import _blocks_for_missing_support as blocks_for_missing
from app.claims.grounding import (
    AssessorSpec,
    _has_supported_claim,
    assess_hypothesis_claims,
    persist_grounding,
)
from app.claims.verifier import make_llm_assessor
from app.report import content as report_content
from app.report import gates as report_gates
from app.report.content import derive_knowledge_facts
from app.report.markdown.hypothesis import _render_claim_evidence
from app.store import NewClaimEvidence, db
from tests._client import make_client
from tests._drain_helpers import _build_report
from tests._store_helpers import _add

from ._llm_fake_backend import install_completion_backend


def _verdict_edge(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def test_the_persisted_vocabulary_is_unchanged() -> None:
    assert [label.value for label in VerdictEntailmentLabel] == [
        "supports",
        "partial",
        "contradicts",
        "insufficient",
    ]
    assert [role.value for role in ClaimRole] == ["categorical", "speculative"]
    assert DEFAULT_CLAIM_ROLE == "categorical"


@pytest.mark.parametrize("raw", [None, "", "bogus", "Supports", 3])
def test_a_missing_or_unrecognized_label_has_no_verdict(raw: Any) -> None:
    edge = _verdict_edge(label=raw)
    assert label_of(edge) is None
    assert not is_supporting(edge)
    assert not is_contradicting(edge)
    assert knowledge_kind(edge) is None


def test_a_missing_role_reads_as_categorical() -> None:
    assert role_of(_verdict_edge()) == "categorical"
    assert role_of(_verdict_edge(claim_role="")) == "categorical"
    assert role_of(_verdict_edge(claim_role="speculative")) == "speculative"
    assert role_of(_verdict_edge(claim_role="exotic")) == "exotic"
    assert is_speculative("speculative")
    assert not is_speculative(None) and not is_speculative("exotic")


def test_only_supports_and_partial_are_supporting() -> None:
    got = {label.value: label.is_supporting for label in VerdictEntailmentLabel}
    assert got == {
        "supports": True,
        "partial": True,
        "contradicts": False,
        "insufficient": False,
    }
    assert is_supporting(_verdict_edge(label="partial"))
    assert not is_supporting(_verdict_edge(label="insufficient"))


def test_a_proposal_can_be_contradicted_without_withholding_the_idea() -> None:
    for role in ("categorical", None):
        edge = _verdict_edge(label="contradicts", claim_role=role)
        assert is_contradicting(edge) and is_categorical_contradiction(edge)
    proposal = _verdict_edge(label="contradicts", claim_role="speculative")
    assert is_contradicting(proposal)
    assert not is_categorical_contradiction(proposal)


def test_only_an_explicit_insufficient_proposal_is_excused() -> None:
    assert is_excused(
        _verdict_edge(label="insufficient", claim_role="speculative")
    )
    assert not is_excused(_verdict_edge(label="insufficient"))
    assert not is_excused(_verdict_edge(claim_role="speculative"))
    assert not is_excused(
        _verdict_edge(label="contradicts", claim_role="speculative")
    )


def test_partial_is_not_a_knowledge_row() -> None:
    kinds = {
        label.value: knowledge_kind(_verdict_edge(label=label.value))
        for label in VerdictEntailmentLabel
    }
    assert kinds == {
        "supports": "fact",
        "partial": None,
        "contradicts": "contradiction",
        "insufficient": None,
    }


def test_status_reads_a_missing_label_as_insufficient() -> None:
    assert claim_status(_verdict_edge(label="partial")) == "Partially supported"
    assert claim_status(_verdict_edge(claim_role="speculative")) == (
        "Speculative — evidence insufficient"
    )
    assert claim_status(_verdict_edge()) == "Unsupported categorical claim"


# Partial supports the publication badge but is not a durable knowledge fact.
# Speculative contradictions remain findings; missing labels are not excused by
# speculative roles.


_LABELS = ("supports", "partial", "contradicts", "insufficient", None)
_ROLES = ("categorical", "speculative", None)
_ODD = (("bogus", "categorical"), ("insufficient", "exotic"))

_SUPPORTED = {"supports", "partial"}
_REASON = "Evidence verification did not support every material claim."
_STATUS = {
    "supports": "Supported",
    "partial": "Partially supported",
    "contradicts": "Contradicted",
}
_UNEXCUSED_STATUS = "Unsupported categorical claim"
_EXCUSED_STATUS = "Speculative — evidence insufficient"


def _matrix_edge(label: str | None, role: str | None) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "hypothesis_id": "h1",
        "claim": "IL-6 increases inflammation via STAT3 signaling.",
        "supporting": [{"evidence_id": "e-for", "quote": "q"}],
        "contradicting": [{"evidence_id": "e-against", "quote": "q"}],
    }
    if label is not None:
        edge["label"] = label
    if role is not None:
        edge["claim_role"] = role
    return edge


def _cases() -> list[tuple[str | None, str | None]]:
    grid = [(label, role) for label in _LABELS for role in _ROLES]
    return grid + list(_ODD)


def _speculative(role: str | None) -> bool:
    return role == "speculative"


@pytest.mark.parametrize(("label", "role"), _cases())
def test_supported_means_supports_or_partial(label: Any, role: Any) -> None:
    ids = report_gates._supported_hypothesis_ids([_matrix_edge(label, role)])
    assert ids == ({"h1"} if label in _SUPPORTED else set())


@pytest.mark.parametrize(("label", "role"), _cases())
def test_a_contradiction_withholds_only_when_categorical(
    label: Any, role: Any
) -> None:
    ids = report_gates.contradicted_hypothesis_ids(
        "", None, claim_edges=[_matrix_edge(label, role)]
    )
    expected = label == "contradicts" and not _speculative(role)
    assert ids == ({"h1"} if expected else set())


@pytest.mark.parametrize(("label", "role"), _cases())
def test_the_withheld_contradiction_panel_ignores_role(
    label: Any, role: Any
) -> None:
    claims = report_content._contradicted_claims([_matrix_edge(label, role)])
    assert len(claims) == (1 if label == "contradicts" else 0)


@pytest.mark.parametrize(("label", "role"), _cases())
def test_unsupported_reason_skips_support_and_excused_gaps(
    label: Any, role: Any
) -> None:
    reasons = report_content._claim_edge_reasons([_matrix_edge(label, role)])
    excused = label == "insufficient" and _speculative(role)
    clean = label in _SUPPORTED or excused
    assert reasons == ({} if clean else {"h1": {_REASON}})


@pytest.mark.parametrize(("label", "role"), _cases())
def test_reader_facing_status_text(label: Any, role: Any) -> None:
    if label in _STATUS:
        expected = _STATUS[label]
    elif _speculative(role):
        expected = _EXCUSED_STATUS
    else:
        expected = _UNEXCUSED_STATUS
    line = _render_claim_evidence([_matrix_edge(label, role)])[2]
    shown_role = role or "categorical"
    assert line.startswith(f"- **{expected} · {shown_role}** — ")


@pytest.mark.parametrize(("label", "role"), _cases())
def test_knowledge_base_topic_cites_only_supporting_edges(
    label: Any, role: Any
) -> None:
    topics = report_content._knowledge_base_topics(
        [{"id": "h1", "title": "T"}], [_matrix_edge(label, role)]
    )
    expected = ["e-for"] if label in _SUPPORTED else []
    assert topics[0]["reference_ids"] == expected


@pytest.mark.parametrize(("label", "role"), _cases())
def test_only_settled_claims_become_knowledge_rows(
    label: Any, role: Any
) -> None:
    rows = derive_knowledge_facts([_matrix_edge(label, role)])
    got = [(r["kind"], r["state"], r["evidence_id"]) for r in rows]
    expected = {
        "supports": [("fact", "supports", "e-for")],
        "contradicts": [("contradiction", "contradicts", "e-against")],
    }
    assert got == expected.get(label, [])


def _assessment(label: MatrixEntailmentLabel) -> ClaimAssessment:
    return ClaimAssessment("claim", label, (), (), "test")


@pytest.mark.parametrize("label", list(MatrixEntailmentLabel))
def test_the_claim_gate_counts_partial_as_support(
    label: MatrixEntailmentLabel,
) -> None:
    assessments = [_assessment(label)]
    supported = label.value in _SUPPORTED
    assert _has_supported_claim([(assessments[0], "categorical")]) is supported
    blocks = blocks_for_missing(assessments, require_supported_claim=True)
    assert blocks is not supported
    assert not blocks_for_missing(assessments, require_supported_claim=False)


@pytest.mark.parametrize("label", list(MatrixEntailmentLabel))
def test_an_unproven_verdict_downgrades_to_insufficient(
    label: MatrixEntailmentLabel,
) -> None:
    span: Any = object()
    insufficient = MatrixEntailmentLabel.INSUFFICIENT
    proven_for = _downgrade_unproven_label(label, [span], [])
    proven_against = _downgrade_unproven_label(label, [], [span])
    contradicts = label is MatrixEntailmentLabel.CONTRADICTS
    assert proven_for is (insufficient if contradicts else label)
    assert proven_against is (
        label if contradicts or label is insufficient else insufficient
    )
    assert _downgrade_unproven_label(label, [], []) is insufficient


def test_a_persisted_edge_defaults_to_a_categorical_claim() -> None:
    edge = NewClaimEvidence("r", "h", "c", "supports", [], [], "a")
    assert edge.claim_role == "categorical"


async def test_grounding_retains_method_across_api_reopen(
    isolated_db: str,
) -> None:
    client = make_client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Study tissue repair"}
    ).json()["id"]
    claim = "A dietary change improves cardiovascular outcomes in adults."
    _add(run_id, "Diet study", claim, isolated_db)

    def assess(
        claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            ProvenanceEntailmentLabel.SUPPORTS,
            supporting=((passages[0].evidence_id, claim),),
            verification_method="model_primary",
        )

    persist_grounding(
        run_id,
        assess_hypothesis_claims(
            store.list_hypotheses(run_id),
            as_passages([claim]),
            AssessorSpec(assessor=assess, assessor_id="llm:test"),
        ),
    )
    reopened = make_client().get(f"/api/runs/{run_id}/claim-evidence")
    assert reopened.status_code == 200
    edges = reopened.json()["claim_evidence"]
    assert edges and all(
        e["verification_method"] == "model_primary" for e in edges
    )
    assert all(e["assessor"] == "llm:test" for e in edges)
    payload, markdown = await _build_report(store.get_run(run_id), isolated_db)
    assert (
        payload["claim_evidence"][0]["verification_method"] == "model_primary"
    )
    assert "Assessment method: model judgment" in markdown


def test_legacy_edges_keep_unknown_method_after_repeat_migration(
    isolated_db: str,
) -> None:
    run = store.create_run("Legacy evidence", "express", "engine", {})
    hyp_id = _add(
        run.id, "Legacy", "A public research hypothesis.", isolated_db
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A legacy claim.",
            label="insufficient",
            supporting=[],
            contradicting=[],
            assessor="llm:old",
        )
    )
    with sqlite3.connect(isolated_db) as conn:
        columns = {
            r[1] for r in conn.execute("PRAGMA table_info(claim_evidence)")
        }
        if "verification_method" in columns:
            conn.execute(
                "ALTER TABLE claim_evidence DROP COLUMN verification_method"
            )
    for _ in range(2):
        db._initialized.discard(isolated_db)
        with db.connect(isolated_db):
            pass
    edges = store.list_claim_evidence(run.id)
    assert len(edges) == 1
    assert edges[0]["verification_method"] == "legacy_unknown"
    assert edges[0]["assessor"] == "llm:old"


@pytest.mark.parametrize(
    "has_evidence, expected",
    [
        (True, "deterministic_lexical"),
        (False, "no_evidence"),
    ],
)
def test_deterministic_method_describes_actual_evidence_path(
    has_evidence: bool,
    expected: str,
) -> None:
    from app.claims import assess_claim

    claim = "A dietary change improves cardiovascular outcomes in adults."
    result = assess_claim(claim, as_passages([claim]) if has_evidence else [])
    assert result.verification_method == expected


def test_no_candidates_cannot_claim_model_verification() -> None:
    from app.claims import assess_claim

    def assess(
        _claim: str, _passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            ProvenanceEntailmentLabel.INSUFFICIENT,
            verification_method="model_primary",
        )

    result = assess_claim(
        "A hypothesis without retrieved evidence.", [], assessor=assess
    )
    assert result.verification_method == "no_evidence"


CLAIM = "Kinase X inhibition reduces tumor growth in AML cells."
QUOTE = "Kinase X inhibition increased tumor growth threefold in AML cells."


def install_replies(
    monkeypatch: pytest.MonkeyPatch, replies: list[Any]
) -> list[Any]:
    requests: list[Any] = []

    async def completion(**kwargs: Any) -> Any:
        requests.append(kwargs)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=json.dumps(reply))
                )
            ]
        )

    install_completion_backend(monkeypatch, completion)
    return requests


def draft(quote: str = QUOTE, passage: int = 1) -> dict[str, Any]:
    return {
        "label": "contradicts",
        "supporting": [],
        "contradicting": [{"passage": passage, "quote": quote}],
    }


def confirmation(index: int = 1, **kwargs: Any) -> dict[str, Any]:
    return {
        "index": index,
        "same_conditions": True,
        "mutually_exclusive": True,
        **kwargs,
    }


def test_directional_opposition_is_verified_and_located(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch, [draft(), {"verdicts": [confirmation()]}]
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.CONTRADICTS
    assert result.verification_method == "model_opposition_verified"
    assert result.contradicting_passages[0].quote == QUOTE
    assert result.contradicting_passages[0].evidence_id == "ev-1"
    assert len(requests) == 2


def test_verified_opposition_preserves_numeric_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_replies(monkeypatch, [draft(), {"verdicts": [confirmation()]}])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("12345", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.CONTRADICTS
    assert [s.evidence_id for s in result.contradicting_passages] == ["12345"]


def test_empty_verification_envelope_retries_before_confirming_opposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch,
        [draft(), {}, {"verdicts": [confirmation()]}],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.CONTRADICTS
    assert result.verification_method == "model_opposition_verified"
    assert len(requests) == 3


def test_batch_verifies_multiple_oppositions_in_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.claims import assess_claims_batch
    from app.claims.verifier import make_llm_batch_assessor

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote, passage=2)},
                ]
            },
            {"verdicts": [confirmation(2), confirmation(1)]},
        ],
    )
    counter = [0]
    assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat", call_counter=counter
    )
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [r.label for r in results] == [
        OppositionEntailmentLabel.CONTRADICTS
    ] * 2
    assert [r.verification_method for r in results] == [
        "model_opposition_verified"
    ] * 2
    assert [r.contradicting_passages[0].evidence_id for r in results] == [
        "ev-1",
        "ev-2",
    ]
    assert len(requests) == counter[0] == 2


def test_batch_short_verification_envelope_retries_before_confirming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.claims import assess_claims_batch
    from app.claims.verifier import make_llm_batch_assessor

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote, passage=2)},
                ]
            },
            {"verdicts": [confirmation(1)]},
            {"verdicts": [confirmation(1), confirmation(2)]},
        ],
    )
    assessor, assessor_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [result.label for result in results] == [
        OppositionEntailmentLabel.CONTRADICTS,
        OppositionEntailmentLabel.CONTRADICTS,
    ]
    assert len(requests) == 3


def test_two_malformed_verification_envelopes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(monkeypatch, [draft(), {}, {}])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.INSUFFICIENT
    assert result.verification_method == "model_opposition_unconfirmed"
    assert len(requests) == 3


def test_complete_negative_verification_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch,
        [
            draft(),
            {
                "verdicts": [
                    confirmation(
                        same_conditions=False,
                        mutually_exclusive=False,
                    )
                ]
            },
        ],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.INSUFFICIENT
    assert result.verification_method == "model_opposition_unconfirmed"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "verdicts",
    [
        [],
        [confirmation(same_conditions=False)],
        [confirmation(mutually_exclusive=False)],
        [confirmation(), confirmation()],
        [confirmation(99)],
        [confirmation(), confirmation(99)],
        [confirmation(), {}],
    ],
)
def test_unconfirmed_opposition_remains_insufficient(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: list[dict[str, Any]],
) -> None:
    install_replies(
        monkeypatch,
        [draft(), {"verdicts": verdicts}, {"verdicts": verdicts}],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.INSUFFICIENT
    assert result.contradicting_passages == ()
    assert result.verification_method == "model_opposition_unconfirmed"


@pytest.mark.parametrize(
    "verdicts",
    [
        [confirmation(1), confirmation(2), confirmation(3)],
        [confirmation(1), confirmation(1)],
        [confirmation(1), confirmation(3)],
    ],
)
def test_complete_invalid_batch_verification_envelopes_remain_rejected(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: list[dict[str, Any]],
) -> None:
    from app.claims import assess_claims_batch
    from app.claims.verifier import make_llm_batch_assessor

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote)},
                ]
            },
            {"verdicts": verdicts},
        ],
    )
    assessor, assessor_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [result.label for result in results] == [
        OppositionEntailmentLabel.INSUFFICIENT,
        OppositionEntailmentLabel.INSUFFICIENT,
    ]
    assert len(requests) == 2


@pytest.mark.parametrize(
    "quote",
    [
        "Invented kinase tumor growth quote.",
        "Photosynthesis oxygenates the atmosphere.",
    ],
)
def test_unlocated_or_unrelated_quotes_never_request_verification(
    monkeypatch: pytest.MonkeyPatch,
    quote: str,
) -> None:
    requests = install_replies(monkeypatch, [draft(quote)])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    passage = QUOTE if quote.startswith("Invented") else QUOTE + " " + quote
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", passage)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.INSUFFICIENT
    assert len(requests) == 1
    assert result.verification_method == "contradiction_guard_rejected"


def test_unavailable_verification_is_observable_without_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.llm import scoped_telemetry

    install_replies(
        monkeypatch,
        [draft(), RuntimeError("unavailable"), RuntimeError("unavailable")],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("test") as telemetry:
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is OppositionEntailmentLabel.INSUFFICIENT
    rows = telemetry.snapshot().values()
    assert result.verification_method == "model_opposition_unconfirmed"
    assert (
        sum(
            r["errors"].get("opposition_verification_unavailable", 0)
            for r in rows
        )
        == 1
    )
    assert all(not r["deterministic_fallbacks"] for r in rows)


@pytest.mark.parametrize("kind", ["budget", "park"])
def test_verification_propagates_task_control_errors(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from co_scientist.exceptions import (
        LLMCallBudgetExceededError,
        LLMRateLimitParkError,
    )

    error = (
        LLMCallBudgetExceededError(2, 1)
        if kind == "budget"
        else RateLimitError(
            message="free-models-per-day rate limit exceeded",
            llm_provider="openrouter",
            model="test-model",
        )
    )
    install_replies(monkeypatch, [draft(), error])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    expected = (
        LLMCallBudgetExceededError
        if kind == "budget"
        else LLMRateLimitParkError
    )
    with scoped_cache_override(False), pytest.raises(expected):
        assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
