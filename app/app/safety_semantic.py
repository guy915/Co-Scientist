"""The contextual (model) half of the content safety screen.

Split from ``app.safety`` so the deterministic policy, the model assessment,
and the run-level effects stay independently readable while each module stays
under the repository's file-length ceiling. ``app.safety`` keeps
``screen_contextual`` and ``_semantic_credential_available`` -- both are
established monkeypatch seams -- and calls into the helpers here.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.llm import call_llm_json
from co_scientist.llm_json_lists import coerce_json_list
from co_scientist.llm_types import CompletionSpec, LLMCallOptions
from co_scientist.schemas.builders import obj

from app.safety_types import SafetyDecision

logger = logging.getLogger(__name__)

__all__ = [
    "run_semantic_safety_model",
    "semantic_credential_missing_decision",
    "semantic_safety_error_decision",
]


def _semantic_prompt(text: str, stage: str) -> str:
    """Build a bounded contextual-risk classification prompt."""
    return (
        "Classify the scientific content under a research safety policy. "
        "Return JSON only with category, reason, risk_domains, "
        "operational_detail, offensive_score, "
        "is_personal_medical_recommendation, and "
        "is_personal_finance_recommendation. category must be one of "
        "prohibited, ethical_concern, uncertain, redacted, allowed. Treat "
        "requests that meaningfully enable weaponization, harmful pathogen "
        "enhancement, mass-casualty capability, non-consensual human "
        "experimentation, or evasion as prohibited or ethical_concern. "
        "Legitimate dual-use work with actionable harmful operational detail "
        "is redacted. Ambiguous risk is uncertain. Do not reproduce or "
        "elaborate unsafe detail.\n"
        "offensive_score is 1-5, where 5 is content a colleague would report "
        "as demeaning, harassing, or discriminatory toward a group of people; "
        "clinical or frank language about a disease, a population, or a body "
        "is 1.\n"
        "The two recommendation flags are true only when the content asks "
        "for, or gives, a course of action for one named person's own health "
        "or money -- their diagnosis, their treatment, their portfolio. "
        "Research about a disease, a drug, a market or a cohort is false, "
        "including when the person writing has the condition themselves.\n"
        f"Stage: {stage}\nContent:\n{text[:16000]}"
    )


# "uncertain" is listed first because it is the enum's backfill default:
# under the json_object downgrade, a model that omits ``category``
# entirely gets it filled with the enum's first value
# (``co_scientist.llm_json._default_for_field_schema``), and a missing
# verdict must read as "needs a human", never as the strictest or the
# most permissive category by accident of list order.
_SEMANTIC_CATEGORY_SCHEMA = {
    "type": "string",
    "enum": [
        "uncertain",
        "prohibited",
        "ethical_concern",
        "redacted",
        "allowed",
    ],
}

# Bare-string tolerant, exactly like claim_verifier's citation list: under
# the json_object downgrade a model can plausibly write one domain
# unwrapped rather than as a one-element array, and ``coerce_json_list``
# (below, in ``_merge_risk_domains``) is what recovers that shape -- a
# plain ``array`` type would fail local schema validation before that
# recovery ever runs.
_RISK_DOMAINS_SCHEMA = {
    "oneOf": [
        {"type": "array", "items": {"type": "string"}},
        {"type": "string"},
    ]
}

# The fields ``_build_semantic_decision``, ``_offensive_score``,
# ``_structured_flag_domains`` and ``_merge_risk_domains`` actually read.
# ``operational_detail`` (asked for in the prompt for the model's own
# reasoning, per the reference product's shape) is not one of them, so it
# is left off this closed schema -- an object node built by
# ``co_scientist.schemas.builders.obj`` prunes any undeclared key under
# the json_object downgrade rather than failing on it.
_SEMANTIC_DECISION_SCHEMA = obj(
    {
        "category": _SEMANTIC_CATEGORY_SCHEMA,
        "reason": {"type": "string"},
        "risk_domains": _RISK_DOMAINS_SCHEMA,
        "offensive_score": {"type": "number"},
        "is_personal_medical_recommendation": {"type": "boolean"},
        "is_personal_finance_recommendation": {"type": "boolean"},
    },
    optional=(
        "risk_domains",
        "is_personal_medical_recommendation",
        "is_personal_finance_recommendation",
    ),
)

_SEMANTIC_CATEGORY_TO_DECISION = {
    "prohibited": "block",
    "ethical_concern": "block",
    "uncertain": "hold",
    "redacted": "redact",
    "allowed": "allow",
}

# Structured signals the reference product carries on its run config
# (offensive_score 1-5, is_personal_medical_recommendation,
# is_personal_finance_recommendation) rather than leaving to prose. They are
# read here, inside the one authoritative screen, and not as a second verdict
# beside it: each fires a named risk domain on the decision the caller
# already gates on, and can only raise an otherwise-clean pass to a hold for
# human adjudication. Nothing here lowers a verdict, and nothing here blocks
# -- these three name a misuse of the product or a tone problem, neither of
# which is the deterministic policy's hard-hazard case.
_OFFENSIVE_HOLD_SCORE = 4

_PERSONAL_RECOMMENDATION_FLAGS = {
    "is_personal_medical_recommendation": "personal_medical_recommendation",
    "is_personal_finance_recommendation": "personal_finance_recommendation",
}


def _offensive_score(parsed: dict[str, Any]) -> float:
    """Read the 1-5 offensiveness score, unparseable values reading lowest."""
    try:
        return float(parsed.get("offensive_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _structured_flag_domains(parsed: dict[str, Any]) -> list[str]:
    """Name the risk domains the model's structured flags raise.

    Args:
        parsed: The semantic model's parsed JSON response.

    Returns:
        Risk-domain names, in a stable order; empty when nothing fires.
    """
    domains = [
        domain
        for key, domain in _PERSONAL_RECOMMENDATION_FLAGS.items()
        if parsed.get(key) is True
    ]
    if _offensive_score(parsed) >= _OFFENSIVE_HOLD_SCORE:
        domains.append("offensive_content")
    return domains


_FLAG_HOLD_REASONS = {
    "personal_medical_recommendation": (
        "reads as a personal medical recommendation rather than a research goal"
    ),
    "personal_finance_recommendation": (
        "reads as a personal financial recommendation rather than a research "
        "goal"
    ),
    "offensive_content": "was assessed as offensive toward a group of people",
}


def _flag_hold_reason(domains: list[str]) -> str:
    """Phrase the hold a structured flag raises, naming what fired."""
    causes = " and it ".join(
        _FLAG_HOLD_REASONS[domain]
        for domain in domains
        if domain in _FLAG_HOLD_REASONS
    )
    return f"Content {causes}; human review required."


async def _call_semantic_safety_model(
    text: str, stage: str, model: str
) -> dict[str, Any]:
    """Call the semantic safety model and return its parsed JSON response.

    Routed through the engine's ``call_llm_json`` seam rather than calling
    ``litellm`` directly (the shape ``claim_verifier`` moved off of in
    113218e9): a gateway model that answers a json_object request with the
    JSON wrapped in a Markdown fence -- reproduced against
    ``minimax/minimax-m3:free``, the free fallback chain's first rung --
    used to raise ``json.loads``'s "Expecting value" straight out of this
    function, which every caller treats as a provider failure and holds
    for human review (``_assessment_unavailable_decision``). The engine
    seam already strips fences (``llm_json.extract_response_json``),
    backfills required fields and prunes invented ones under the
    json_object downgrade, retries on the shared budget ladder, and
    raises once every attempt is exhausted -- so the same
    ``except Exception`` in ``screen_contextual``/``assess_hold_contextually``
    still catches a persistently bad model and still falls back to the
    unavailable-assessment hold; it just no longer trips on a
    well-formed-but-fenced first answer.

    Sending no ``max_tokens`` was not "unbounded" -- it took the
    provider's own default, small enough for thinking to exhaust before
    the verdict was written, and that failure was silent all the way to
    the outcome. The floor is no longer this module's job: the engine's
    own ``_apply_thinking_args`` raises ``max_tokens`` to its thinking
    floor (and applies the DeepSeek thinking kwargs) only for a model that
    actually reasons, so a plain answer-sized budget here is never
    double-floored. There is likewise no per-call timeout knob in this
    seam; the process-wide ``COSCIENTIST_LLM_TIMEOUT_SECONDS`` (600s
    default) governs instead of the 20s this module used to send --
    generous, but both gates run inside durable background tasks with no
    caller waiting on a clock.
    """
    from app import credentials

    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this screen.
    resolved_model, api_key = credentials.byok_model_and_key(model)
    spec = CompletionSpec(
        model_name=resolved_model,
        max_tokens=1_000,
        temperature=0,
        json_schema=_SEMANTIC_DECISION_SCHEMA,
        api_key=api_key,
    )
    # Caching stays off: the direct-litellm call this replaces was never
    # cached, and a safety gate re-screened on resume (screen_with_
    # escalation's approval check aside) should re-evaluate rather than
    # silently replay an earlier verdict. It also broke a test in
    # test_hypothesis_safety_escalation.py that fakes a provider failure
    # after an earlier test's success populated a hit for the same prompt.
    #
    # Two attempts, not the default five: the fence case this call exists
    # to fix resolves on attempt 1, and a second attempt covers one
    # budget-escalation rung for an ordinary hiccup. Both gates run inside
    # durable tasks with no caller waiting on a clock, but bootstrap holds
    # the run's very first lease for the duration -- five attempts at the
    # 600s process timeout is up to 50 minutes of a stuck lease where the
    # call this replaced gave up after one attempt at 20s.
    result: dict[str, Any] = await call_llm_json(
        _semantic_prompt(text, stage),
        spec,
        max_attempts=2,
        options=LLMCallOptions(use_cache=False, prompt_name="safety_screen"),
    )
    return result


def _merge_risk_domains(
    parsed: dict[str, Any], flagged: list[str]
) -> list[str]:
    """Combine the model's free-text risk domains with the flagged ones.

    Deduplicated because the model can name a domain in prose that a
    structured flag also raises, and a decision listing the same risk twice
    reads as two findings.

    Args:
        parsed: The semantic model's parsed JSON response.
        flagged: Risk domains raised by the structured flags.

    Returns:
        The domains in first-seen order.
    """
    # response_format={"type": "json_object"} carries no schema
    # enforcement, so a single domain can plausibly arrive as a bare
    # string rather than a one-element list.
    merged: list[str] = coerce_json_list(
        parsed.get("risk_domains"),
        element="str",
        site="safety_semantic.risk_domains",
    )
    merged.extend(domain for domain in flagged if domain not in merged)
    return merged


def _build_semantic_decision(
    stage: str, model: str, parsed: dict[str, Any]
) -> SafetyDecision:
    """Turn a parsed semantic-model response into a :class:`SafetyDecision`."""
    category = str(parsed.get("category") or "uncertain")
    if category not in _SEMANTIC_CATEGORY_TO_DECISION:
        category = "uncertain"
    decision = _SEMANTIC_CATEGORY_TO_DECISION[category]
    reason = str(parsed.get("reason") or "Contextual safety assessment.")
    flagged = _structured_flag_domains(parsed)
    # Escalate-only, and only from a clean pass: a structured flag can turn
    # an "allowed" verdict into a hold, but never softens a category the
    # model already withheld on, and never overwrites its reason for doing so.
    if flagged and decision == "allow":
        decision = "hold"
        category = "uncertain"
        reason = _flag_hold_reason(flagged)
    return SafetyDecision(
        stage=stage,
        decision=decision,
        reason=reason,
        category=category,
        risk_domains=_merge_risk_domains(parsed, flagged),
        requires_review=decision in {"hold", "redact"},
        assessor=f"semantic:{model}",
    )


async def run_semantic_safety_model(
    text: str, stage: str, model: str
) -> SafetyDecision:
    """Call the semantic safety model and turn its category into a decision."""
    parsed = await _call_semantic_safety_model(text, stage, model)
    return _build_semantic_decision(stage, model, parsed)


def _assessment_unavailable_decision(
    stage: str, baseline: SafetyDecision, assessor: str
) -> SafetyDecision:
    """Build the refusal used whenever the contextual screen cannot run.

    A deterministic redaction already withholds the content and names the
    spans to remove, so it stands; anything weaker becomes a hold, because a
    configured screen that did not run must not read as a clean pass.

    Args:
        stage: Safety stage being screened (``"intake"`` or ``"final"``).
        baseline: The deterministic decision the screen would have refined.
        assessor: Provenance string recorded on the decision.

    Returns:
        The decision to gate on in place of the missing assessment.
    """
    if baseline.decision == "redact":
        return baseline
    return SafetyDecision(
        stage=stage,
        decision="hold",
        reason=(
            "Contextual safety assessment was unavailable; human review "
            "required."
        ),
        category="uncertain",
        risk_domains=["assessment_unavailable"],
        requires_review=True,
        assessor=assessor,
    )


def semantic_safety_error_decision(
    stage: str, model: str, baseline: SafetyDecision, exc: Exception
) -> SafetyDecision:
    """Build the fallback decision when the semantic safety call fails."""
    logger.warning("Contextual safety assessment failed: %s", exc)
    return _assessment_unavailable_decision(
        stage, baseline, f"semantic:{model}:error"
    )


def semantic_credential_missing_decision(
    stage: str, model: str, baseline: SafetyDecision
) -> SafetyDecision:
    """Refuse when the configured screen has no credential to reach.

    Returning the deterministic baseline here was a silent fail-open: the
    screen is configured, so the deployment believes it is running, and a
    missing credential is a deployment fault rather than a property of the
    content. The refusal is logged at WARNING because nothing else on this
    path names the cause.
    """
    logger.warning(
        "Contextual safety assessment is enabled but model %s has no "
        "reachable provider credential; withholding %s stage for human "
        "review instead of screening on the deterministic rules alone.",
        model,
        stage,
    )
    return _assessment_unavailable_decision(
        stage, baseline, f"semantic:{model}:no_credential"
    )
