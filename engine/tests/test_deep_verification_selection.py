"""Which hypotheses deep verification runs on, and how often.

The published rule is blanket and per-hypothesis: ``03-reflection.md``'s
``ReviewHypothesis`` verifies the hypothesis, then creates *that*
hypothesis's ``AddToTournament`` task. Blanket is affordable only because
it is incremental, so these tests pin both halves -- every unverified idea
is verified, and no idea is ever verified twice, across a repeated cycle,
a restart, or any freshness signal going stale underneath it.

The selection rule itself lives in
``co_scientist.agents.reflection.verification_freshness``; the node's own
prompt, context and probe-retrieval mechanics stay in the sibling
``test_deep_verification``. Every test here monkeypatches
``call_llm_json`` on the node module, so no LLM or network calls are made.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.models import Hypothesis
from tests._state import make_article, make_hypothesis, make_state


def _probe_response_mock() -> AsyncMock:
    """A verifier stub returning one non-fundamental probe and a verdict.

    Non-fundamental so ``_probe_queries`` still yields a search query but
    the run stays on the single-call path with no probe retrieval.
    """
    return AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": False,
                }
            ],
            "verdict": "holds",
            "overall_assessment": "ok",
        }
    )


async def test_verifies_every_unverified_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole pool is verified, not an Elo-selected slice of it.

    ``03-reflection.md`` runs deep verification inside
    ``ReviewHypothesis(HypothesisID)`` for the hypothesis being reviewed
    and only then creates that hypothesis's ``AddToTournament`` task, so
    the published rule is blanket: every idea, before it can be ranked.
    """
    fake = AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": True,
                }
            ],
            "verdict": "weakened",
            "overall_assessment": "ok",
        }
    )
    monkeypatch.setattr(dv, "call_llm_json", fake)

    hyps = [
        make_hypothesis(text=f"h{i}", elo_rating=1000 + i * 100)
        for i in range(5)  # elos 1000..1400
    ]
    state = make_state(
        hypotheses=hyps,
        research_goal="goal",
        model_name="test/model",
        run_id="r1",
    )
    out = await dv.deep_verification_node(state)

    verified = [h for h in out["hypotheses"] if h.deep_verification_probes]
    assert {h.text for h in verified} == {"h0", "h1", "h2", "h3", "h4"}
    assert verified[0].deep_verification_verdict == "weakened"
    # Full/simulation reviews run in the comprehensive Reflection node.
    assert fake.await_count == 5


async def test_a_verified_hypothesis_is_never_verified_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The once-ever marker outranks every staleness signal there is.

    Blanket verification is affordable only because it is incremental.
    Probe retrieval adds citations to the hypothesis it verified, so the
    freshness fingerprint alone would go stale on the very pass that
    wrote it and re-verify the whole pool every cycle.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="verified once")
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert fake.await_count == 1

    # Every input the fingerprint covers moves underneath it.
    h.citation_map = {"C9": {"source_id": "arrived-later"}}
    await dv.deep_verification_node(state)

    assert fake.await_count == 1
    assert dv.verification_issued(h)


async def test_a_resumed_run_does_not_re_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker rides in ``enrichments``, so it survives a checkpoint.

    Held only in memory it would turn a bounded, once-per-idea cost into
    a fresh whole-pool wave on every restart.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="verified before the restart")
    await dv.deep_verification_node(make_state(hypotheses=[h]))
    assert fake.await_count == 1

    restored = Hypothesis.from_dict(h.to_dict())
    await dv.deep_verification_node(make_state(hypotheses=[restored]))

    assert fake.await_count == 1


async def test_evolution_children_are_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child is a new idea, so it gets its own one verification.

    The child is a fresh ``Hypothesis`` with empty ``enrichments``; the
    parent's marker is not inherited, so the incremental rule funds each
    cycle's new ideas without re-funding the ones already verified.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    parent = make_hypothesis(text="parent")
    state = make_state(hypotheses=[parent])
    await dv.deep_verification_node(state)
    assert fake.await_count == 1

    child = make_hypothesis(text="child", parent_id=parent.id, generation=1)
    state["hypotheses"].append(child)
    await dv.deep_verification_node(state)

    assert fake.await_count == 2
    assert child.deep_verification_verdict == "holds"


async def test_blocked_ideas_are_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification guards tournament entry, so it funds only entrants.

    The published order puts the initial review's discard first ("Full
    review. If a hypothesis passes the initial review..."), and an idea
    the review gate barred never reaches a tournament match for deep
    verification to have protected.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    blocked = make_hypothesis(text="blocked", review_disposition="inaccurate")
    state = make_state(hypotheses=[blocked])
    await dv.deep_verification_node(state)

    assert fake.await_count == 0
    assert not dv.verification_issued(blocked)


async def test_skips_already_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leader whose verification inputs are unchanged is not re-verified."""
    fake = AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": False,
                }
            ],
            "verdict": "holds",
            "overall_assessment": "ok",
        }
    )
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="already", elo_rating=2000)
    h.deep_verification_probes = [
        {
            "question": "old",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": True,
        }
    ]
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    await dv.deep_verification_node(state)
    assert fake.await_count == 0  # inputs unchanged -> reused


async def test_reverifies_when_hypothesis_text_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rewriting a hypothesis invalidates the verification of the old one."""
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="original", elo_rating=2000)
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    # Evolution (or a scientist edit) rewrites the text in place.
    h.text = "materially different claim"

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_reverifies_when_the_verifier_model_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict from another model is not carried over as current."""
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, "some-other-model"
    )
    state = make_state(hypotheses=[h])

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_unrelated_evidence_does_not_invalidate_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence the hypothesis never cites cannot make its verdict stale.

    The evidence context is assembled run-wide, so hashing all of it would
    re-verify the whole leaderboard whenever any article arrived anywhere.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.citation_map = {"C1": {"source_id": "cited-1", "title": "Cited"}}
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    # A new article lands in the run that this hypothesis does not cite.
    state["articles"] = [
        make_article("Unrelated paper", abstract="x", used_in_analysis=True)
    ]

    await dv.deep_verification_node(state)

    assert fake.await_count == 0


async def test_reverifies_when_cited_evidence_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence the hypothesis now cites is a new input to its verdict."""
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.citation_map = {"C1": {"source_id": "cited-1"}}
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.citation_map["C2"] = {"source_id": "cited-2"}

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_a_hypothesis_with_no_stored_verification_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idea that has never been verified carries no fingerprint."""
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    verified = make_hypothesis(text="incumbent", elo_rating=2000)
    promoted = make_hypothesis(text="newcomer", elo_rating=1900)
    state = make_state(hypotheses=[verified, promoted])
    verified.deep_verification_fingerprint = dv.verification_fingerprint(
        verified, state["model_name"]
    )

    await dv.deep_verification_node(state)

    assert fake.await_count == 1
    assert promoted.deep_verification_fingerprint is not None


async def test_verification_is_run_once_across_repeated_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The observed four-cycle pattern costs one verification, not four.

    The node runs once per work cycle, ahead of each tournament. An idea
    already verified must not be re-verified by any later cycle.
    """
    fake = _probe_response_mock()
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="stable leader", elo_rating=2000)
    state = make_state(hypotheses=[h])

    for _ in range(4):
        await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_a_failed_verification_spends_the_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure is not recorded as a verification, and is not re-fired.

    The marker is written when the attempt is *issued*, not when it
    succeeds: re-firing on failure is how a bounded once-per-idea wave
    becomes a per-cycle one for exactly the ideas the verifier keeps
    failing on. The accepted cost is that a hard failure leaves the idea
    explicitly ``unverified`` for the rest of the run; the transient case
    is already answered by the retry ladders below this seam.
    """
    calls = 0

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(dv, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    await dv.deep_verification_node(state)

    assert calls == 1
    assert h.deep_verification_fingerprint is None
    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
