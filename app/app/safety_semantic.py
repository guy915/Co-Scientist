"""The contextual (model) half of the content safety screen.

Split from ``app.safety`` so the deterministic policy, the model assessment,
and the run-level effects stay independently readable while each module stays
under the repository's file-length ceiling. ``app.safety`` keeps
``screen_contextual`` and ``_semantic_credential_available`` -- both are
established monkeypatch seams -- and calls into the helpers here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import (
    deepseek_thinking_kwargs,
    thinking_safe_max_tokens,
    thinking_safe_timeout,
)
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
        "Return JSON only with category, reason, risk_domains, and "
        "operational_detail. category must be one of prohibited, "
        "ethical_concern, uncertain, redacted, allowed. Treat requests that "
        "meaningfully enable weaponization, harmful pathogen enhancement, "
        "mass-casualty capability, non-consensual human experimentation, or "
        "evasion as prohibited or ethical_concern. Legitimate dual-use work "
        "with actionable harmful operational detail is redacted. Ambiguous "
        "risk is uncertain. Do not reproduce or elaborate unsafe detail.\n"
        f"Stage: {stage}\nContent:\n{text[:16000]}"
    )


_SEMANTIC_CATEGORY_TO_DECISION = {
    "prohibited": "block",
    "ethical_concern": "block",
    "uncertain": "hold",
    "redacted": "redact",
    "allowed": "allow",
}


async def _call_semantic_safety_model(
    text: str, stage: str, model: str
) -> dict[str, Any]:
    """Call the semantic safety model and return its parsed JSON response."""
    import litellm

    from app import credentials

    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this screen.
    model, api_key = credentials.byok_model_and_key(model)
    # Sending no max_tokens was not "unbounded" -- it took the provider's
    # own default, small enough for thinking to exhaust before the verdict
    # is written. That failure is silent all the way to the outcome: empty
    # content parses to {}, {} carries no category, and a missing category
    # is "uncertain", which is hold-plus-human-review. Runs would park for
    # adjudication on a truncated call rather than on their content. The
    # 20s clock could not fund the reasoning either; both gates run inside
    # durable tasks, so neither ceiling is blocking a request.
    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": _semantic_prompt(text, stage)}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=thinking_safe_max_tokens(model, 1_000),
        timeout=thinking_safe_timeout(model, 20),
        **deepseek_thinking_kwargs(model),
        api_key=api_key,
    )
    content = response.choices[0].message.content or "{}"
    parsed: dict[str, Any] = json.loads(content)
    return parsed


def _build_semantic_decision(
    stage: str, model: str, parsed: dict[str, Any]
) -> SafetyDecision:
    """Turn a parsed semantic-model response into a :class:`SafetyDecision`."""
    category = str(parsed.get("category") or "uncertain")
    if category not in _SEMANTIC_CATEGORY_TO_DECISION:
        category = "uncertain"
    decision = _SEMANTIC_CATEGORY_TO_DECISION[category]
    domains = parsed.get("risk_domains")
    return SafetyDecision(
        stage=stage,
        decision=decision,
        reason=str(parsed.get("reason") or "Contextual safety assessment."),
        category=category,
        risk_domains=(
            [str(item) for item in domains] if isinstance(domains, list) else []
        ),
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
