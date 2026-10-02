"""Tests for the per-hypothesis contextual escalation seam (FINDINGS.md J13).

``hypothesis.safety.escalate_review`` gives a contextual model a chance to
raise a Tier B verdict the deterministic layer held as UNCERTAIN. It never
touches a clean allow -- the deterministic layer does not produce one for a
Tier B match at all (an earlier version of this design did, and it was a
bypass the coordinator caught and this file now pins against: a category
match cleared by a benign marker plus an unlisted operational verb must
never reach ALLOW). These tests cover: only a held UNCERTAIN review is ever
escalated (a certain block or an already-blocking-but-uncorroborated Tier B
match never even attempts a network call), fails closed on anything that
stops the model from running, and the model may either raise a held verdict
to a certain block or clear it after contextual review.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import human_input, safety
from app.config import settings
from app.hypothesis.safety import (
    HypothesisSafetyOutcome as SafetyOutcome,
)
from app.hypothesis.safety import (
    HypothesisSafetyReview,
    escalate_review,
    review_hypothesis_safety,
)
from tests._process_mode_helpers import FakeProcessMode

from ._llm_fake_backend import install_completion_backend

_MODEL = "openrouter/test/safety:free"


@pytest.fixture(autouse=True)
def _qualified_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from co_scientist.llm.admission import free_catalog

    monkeypatch.setattr(settings, "semantic_safety_model", _MODEL)
    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(
            lambda: {
                "test/safety:free": {
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                }
            }
        )
    )


def _assert_free_request(kwargs: dict[str, Any]) -> None:
    assert kwargs["model"] == _MODEL
    assert kwargs["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }


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
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A configured-but-unreachable model must not silently clear a hold."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online(credential=False)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.UNCERTAIN
    assert result.blocks_tournament


async def test_provider_error_holds_rather_than_allows(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A provider failure mid-call must not clear the hold either."""
    calls: list[dict[str, Any]] = []

    async def raise_completion(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()
    install_completion_backend(monkeypatch, raise_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert calls
    for request in calls:
        _assert_free_request(request)
    assert result.outcome == SafetyOutcome.UNCERTAIN
    assert result.blocks_tournament


async def test_model_agreeing_it_is_fine_clears_a_tier_b_hold(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
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

    async def allow_completion(**kwargs: Any) -> SimpleNamespace:
        _assert_free_request(kwargs)
        return _fake_semantic_response("allowed")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()
    install_completion_backend(monkeypatch, allow_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.ALLOW
    assert not result.blocks_tournament


async def test_model_raises_a_held_verdict(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """When the model disagrees with the hold, it may raise it to block."""

    async def block_completion(**kwargs: Any) -> SimpleNamespace:
        _assert_free_request(kwargs)
        return _fake_semantic_response("prohibited")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()
    install_completion_backend(monkeypatch, block_completion)
    review = _held_review()

    result = await escalate_review(review, _HELD_TEXT, run_id="r1")

    assert result.outcome == SafetyOutcome.PROHIBITED
    assert result.needs_context is True
    assert result is not review


async def test_admission_endpoint_path_blocks_on_model_raise(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The scientist-admission wrapper reflects an escalated block too."""

    async def block_completion(**kwargs: Any) -> SimpleNamespace:
        _assert_free_request(kwargs)
        return _fake_semantic_response("prohibited")

    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()
    install_completion_backend(monkeypatch, block_completion)

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
