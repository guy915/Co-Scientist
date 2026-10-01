"""Structured safety signals fold into the one screen, never beside it.

The reference product carries its safety judgments as fields on the run
config -- an ``offensive_score`` of 1-5 and two "is this a personal
recommendation" booleans -- rather than as prose. We read the same three
signals, but from inside ``screen_contextual``'s own model call, so they
raise named risk domains on the decision the gate already acts on instead of
standing up a second verdict next to ``app.safety``.

These tests pin the direction of that fold: a flag may raise a clean pass to
a hold, and may never soften a verdict the model already withheld on.
"""

from __future__ import annotations

import json
from typing import Any

from app.safety.semantic import _build_semantic_decision


def _decision(stage: str = "intake", **fields: Any) -> Any:
    """Build a decision from a semantic-model response with these fields."""
    return _build_semantic_decision(stage, "m", fields)


def test_a_clean_pass_holds_on_a_personal_medical_recommendation() -> None:
    """Asking what to take for one's own condition is not a research goal."""
    decision = _decision(
        category="allowed", is_personal_medical_recommendation=True
    )

    assert decision.decision == "hold"
    assert decision.requires_review is True
    assert "personal_medical_recommendation" in decision.risk_domains
    assert "personal medical recommendation" in decision.reason


def test_a_clean_pass_holds_on_a_personal_finance_recommendation() -> None:
    """The finance flag holds on the same terms as the medical one."""
    decision = _decision(
        category="allowed", is_personal_finance_recommendation=True
    )

    assert decision.decision == "hold"
    assert "personal_finance_recommendation" in decision.risk_domains


def test_offensive_content_holds_only_at_the_top_of_the_scale() -> None:
    """The score is 1-5 and only its top two rungs withhold anything.

    Clinical language about a disease or a population scores low by design;
    holding at 3 would park ordinary biomedical goals for adjudication.
    """
    assert _decision(category="allowed", offensive_score=3).decision == "allow"
    assert _decision(category="allowed", offensive_score=4).decision == "hold"
    assert _decision(category="allowed", offensive_score=5).decision == "hold"


def test_an_unparseable_score_reads_lowest_rather_than_holding() -> None:
    """A malformed field is a model fault, not evidence about the content.

    The deterministic rules and the model's own category still bound this
    decision from below, so reading a junk score as 0 cannot fail open past
    them.
    """
    assert _decision(category="allowed", offensive_score="n/a").decision == (
        "allow"
    )
    assert _decision(category="allowed", offensive_score=None).decision == (
        "allow"
    )


def test_a_flag_never_softens_a_verdict_the_model_withheld_on() -> None:
    """Escalate-only: a hold-worthy flag cannot turn a block into a hold."""
    decision = _decision(
        category="prohibited",
        reason="Enables a mass-casualty capability.",
        is_personal_medical_recommendation=True,
    )

    assert decision.decision == "block"
    assert decision.category == "prohibited"
    # The block's own reason survives; the flag only adds its domain.
    assert decision.reason == "Enables a mass-casualty capability."
    assert "personal_medical_recommendation" in decision.risk_domains


def test_a_flag_does_not_disturb_a_redaction() -> None:
    """A redaction already withholds the content and names its spans."""
    decision = _decision(category="redacted", offensive_score=5)

    assert decision.decision == "redact"
    assert "offensive_content" in decision.risk_domains


def test_the_flags_are_silent_on_ordinary_research() -> None:
    """Nothing fires, so nothing is added and the pass stands."""
    decision = _decision(
        category="allowed",
        reason="Benign.",
        offensive_score=1,
        is_personal_medical_recommendation=False,
        is_personal_finance_recommendation=False,
    )

    assert decision.decision == "allow"
    assert decision.risk_domains == []
    assert decision.requires_review is False


def test_a_bare_string_risk_domain_is_still_recovered() -> None:
    """A single domain reported as a bare string, not a list, still counts.

    ``response_format={"type": "json_object"}`` carries no schema
    enforcement, so a model naming exactly one risk domain can plausibly
    write it as a string rather than a one-element list; that must not
    read as "the model reported no domains".
    """
    decision = _decision(
        category="allowed",
        risk_domains="dual_use_concern",
    )

    assert decision.risk_domains == ["dual_use_concern"]


def test_a_domain_the_model_also_named_is_listed_once() -> None:
    """Two findings of the same risk read as two findings."""
    decision = _decision(
        category="allowed",
        risk_domains=["personal_medical_recommendation"],
        is_personal_medical_recommendation=True,
    )

    assert decision.risk_domains == ["personal_medical_recommendation"]


def test_both_recommendation_flags_are_named_in_one_reason() -> None:
    """A held decision says everything that put it there."""
    decision = _decision(
        category="allowed",
        is_personal_medical_recommendation=True,
        offensive_score=5,
    )

    assert decision.risk_domains == [
        "personal_medical_recommendation",
        "offensive_content",
    ]
    assert "personal medical recommendation" in decision.reason
    assert "offensive" in decision.reason


def test_the_screen_asks_for_the_structured_fields() -> None:
    """The signals have to be requested to be read.

    The response is parsed leniently -- an absent flag is simply false -- so
    a prompt that stopped asking for them would silently stop screening for
    them, with every test above still passing.
    """
    from app.safety.semantic import _semantic_prompt

    prompt = _semantic_prompt("a goal", "intake")

    assert "offensive_score" in prompt
    assert "is_personal_medical_recommendation" in prompt
    assert "is_personal_finance_recommendation" in prompt


def test_the_flags_survive_the_json_the_provider_actually_returns() -> None:
    """The model answers with a JSON string, not a Python dict."""
    parsed = json.loads(
        '{"category":"allowed","reason":"t",'
        '"is_personal_finance_recommendation":true,"offensive_score":2}'
    )

    decision = _build_semantic_decision("intake", "m", parsed)

    assert decision.decision == "hold"
    assert decision.risk_domains == ["personal_finance_recommendation"]
