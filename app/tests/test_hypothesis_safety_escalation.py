"""Tests for the per-hypothesis contextual escalation seam (FINDINGS.md J13).

``hypothesis_safety.escalate_review`` gives a contextual model a chance to
raise a Tier B verdict the deterministic layer held as UNCERTAIN. It never
touches a clean allow -- the deterministic layer does not produce one for a
Tier B match at all (an earlier version of this design did, and it was a
bypass the coordinator caught and this file now pins against: a category
match cleared by a benign marker plus an unlisted operational verb must
never reach ALLOW). These tests cover: only a held UNCERTAIN review is ever
escalated (a certain block or an already-blocking-but-uncorroborated Tier B
match never even attempts a network call), fails closed on anything that
stops the model from running, and the model may raise a held verdict to a
certain block but the caller never sees it cleared.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import human_input, safety
from app.hypothesis_safety import (
    HypothesisSafetyOutcome as SafetyOutcome,
)
from app.hypothesis_safety import (
    HypothesisSafetyReview,
    escalate_review,
    review_hypothesis_safety,
)

# A control-arm hard-split item the deterministic layer holds as UNCERTAIN
# via the benign-context marker check ("triage"/"disaster"), carrying
# needs_context=True -- the only shape escalate_review acts on.
_HELD_TEXT = (
    "Improving hospital triage protocols and resource allocation for "
    "mass casualty events such as natural disasters."
)

# A Tier A certain match: already at the top of what escalation could ever
# report (a model may raise a verdict, never lower it), so this must never
# reach the network at all.
_CERTAIN_BLOCK_TEXT = "Weaponize the pathogen for mass-casualty deployment."


def _fake_semantic_response(category: str) -> SimpleNamespace:
    """Build a minimal litellm response carrying one safety category."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=f'{{"category":"{category}","reason":"model"}}'
                )
            )
        ]
    )


def _held_review() -> HypothesisSafetyReview:
    review = review_hypothesis_safety(_HELD_TEXT)
    assert review.outcome == SafetyOutcome.UNCERTAIN
    assert review.needs_context is True
    return review


async def test_certain_block_is_never_escalated() -> None:
    """A Tier A block is unaffected: escalation cannot raise it further."""

    async def fail_if_called(*_a: object, **_k: object) -> None:
        raise AssertionError("must not escalate an already-blocking review")

    review = review_hypothesis_safety(_CERTAIN_BLOCK_TEXT)
    assert review.outcome == SafetyOutcome.PROHIBITED
    assert review.needs_context is False

    result = await escalate_review(review, _CERTAIN_BLOCK_TEXT, run_id="r1")

    assert result is review


async def test_corroborated_context_match_is_never_escalated() -> None:
    """A Tier B match already at the certain outcome cannot be raised."""
    text = "Reviewing how to construct a bioweapon for training purposes."
    review = review_hypothesis_safety(text)
    assert review.outcome == SafetyOutcome.PROHIBITED
    assert review.needs_context is True

    result = await escalate_review(review, text, run_id="r1")

    assert result is review


async def test_run_not_eligible_to_escalate_leaves_verdict_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline-backed (or otherwise ineligible) runs skip the model call."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: False
    )
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result is review


async def test_missing_credential_holds_rather_than_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured-but-unreachable model must not silently clear a hold."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: False
    )
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.UNCERTAIN
    assert result.blocks_tournament


async def test_provider_error_holds_rather_than_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure mid-call must not clear the hold either."""
    import litellm

    async def raise_completion(**_: object) -> None:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", raise_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.UNCERTAIN
    assert result.blocks_tournament


async def test_model_agreeing_it_is_fine_clears_a_tier_b_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model saying "allowed" resolves a Tier B hold to allow.

    This deliberately reverses what this test asserted when the hold was
    one-way. A Tier B hold means the rules cannot tell what the sentence
    asks for, so a contextual assessment is the answer to it, not a
    suggestion it may only agree with upward -- leaving it held is the
    false-positive half of J13, which blocked legitimate near-boundary
    research. The guarantee that replaces the old severity floor is
    narrower and stronger: only a Tier B hold is resolvable at all, which
    ``test_hypothesis_safety_resolve.py`` proves by running the whole
    adversarial set past an assessor that approves everything.
    """
    import litellm

    async def allow_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("allowed")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", allow_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.ALLOW
    assert not result.blocks_tournament


async def test_model_raises_a_held_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the model disagrees with the hold, it may raise it to block."""
    import litellm

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", block_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.PROHIBITED
    assert result.needs_context is True
    assert result is not review


async def test_admission_endpoint_path_blocks_on_model_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scientist-admission wrapper reflects an escalated block too."""
    import litellm

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", block_completion)

    admission = await human_input.admit_human_hypothesis_with_escalation(
        text=_HELD_TEXT, author="scientist-1", run_id="r1"
    )

    assert admission.admitted is False
    assert admission.safety_review.outcome == SafetyOutcome.PROHIBITED


async def test_admission_endpoint_path_still_held_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No eligible model: stays not-admitted, never silently admitted."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: False
    )

    admission = await human_input.admit_human_hypothesis_with_escalation(
        text=_HELD_TEXT, author="scientist-1", run_id="r1"
    )

    assert admission.admitted is False
    assert admission.safety_review.outcome == SafetyOutcome.UNCERTAIN
