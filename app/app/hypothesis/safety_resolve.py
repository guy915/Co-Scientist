"""Contextual resolution of a Tier B "needs context" safety hold.

The deterministic classifier (``co_scientist.safety``) has two tiers. Tier
A patterns name an *action* -- weaponize, enhance transmissibility, build a
nuclear device -- and are terminal: no surrounding text excuses them, and
nothing in this module can touch them. Tier B patterns name only a
*category* -- "bioweapon", "nerve agent", "mass casualty", "without
informed consent", "eugenics". A category term says what a sentence is
about, not what it asks for, so the classifier deliberately refuses to
decide and returns UNCERTAIN with ``needs_context=True``.

**That hold is a question, not an accusation, and this module answers it.**

Why it cannot be answered with more patterns. The five legitimate items
the hard control split holds today are disaster-response triage, a nerve
agent *detection* assay, declassified treaty-compliance records, a history
of the eugenics movement, and an ethics review of Tuskegee. What separates
them from an attack is not vocabulary -- every benign marker they contain
("reviewing", "historical", "analysis") appears just as naturally in "a
historical review of how to make a nerve agent". It is whether the
sentence asks to *bring the dangerous thing about*, which no keyword list
decides: an earlier version of this policy tried, gating a clear on the
absence of a verb from a finite list, and "make", "obtain" and "acquire"
walked straight through it. Tier B exists precisely because the question
needs a reader.

What keeps this from being that same bypass with a model in place of a
regex:

- **Tier A is unreachable from here.** :func:`resolve_hold` accepts only
  an UNCERTAIN verdict carrying ``needs_context=True``, which only
  ``_resolve_context_hit`` produces. A model that answered "allow" to
  every input on earth could not clear one Tier A block, and
  ``test_hypothesis_safety_resolve.py`` proves it by doing exactly that
  over the whole adversarial set.
- **Every failure is a hold.** Disabled, offline-pinned, no credential,
  provider error, unparseable answer, or any verdict other than a clean
  allow leaves the deterministic hold exactly as it was. The permissive
  outcome requires an affirmative answer; nothing else produces it.
- **A raise still works.** The model may also resolve the hold *upward*
  to prohibited, which is what ``escalate_review`` already did.

The hypothesis text is data, never instruction: it is passed to the
assessor as the content under review, and only the assessor's structured
verdict is read back.
"""

from __future__ import annotations

import logging

from co_scientist.safety import POLICY_VERSION, SafetyOutcome, SafetyReview

logger = logging.getLogger(__name__)

_STAGE = "hypothesis"

_CLEARED_REASON = (
    "matched a sensitive category term, and a contextual assessment read "
    "the surrounding text as descriptive rather than operational"
)


def is_resolvable_hold(review: SafetyReview) -> bool:
    """Return whether this verdict is a Tier B hold this module may resolve.

    The single gate that keeps Tier A out. ``needs_context`` is set only
    by ``co_scientist.safety._resolve_context_hit``, the Tier B resolver;
    a Tier A verdict never carries it, so no combination of model output
    can route one here.

    Args:
        review: The deterministic verdict to test.

    Returns:
        True only for an UNCERTAIN, needs-context (Tier B) verdict.
    """
    return bool(review.needs_context) and (
        review.outcome == SafetyOutcome.UNCERTAIN
    )


def _cleared(review: SafetyReview) -> SafetyReview:
    """Build the allow that a clean contextual assessment produces."""
    return SafetyReview(
        SafetyOutcome.ALLOW,
        _CLEARED_REASON,
        review.matches,
        POLICY_VERSION,
        True,
    )


def _raised(
    review: SafetyReview, reason: str, matches: tuple[str, ...]
) -> SafetyReview:
    """Build the prohibition that an adverse contextual assessment produces."""
    return SafetyReview(
        SafetyOutcome.PROHIBITED,
        reason,
        matches or review.matches,
        POLICY_VERSION,
        True,
    )


async def resolve_hold(
    review: SafetyReview,
    text: str,
    *,
    run_id: str,
    db_path: str | None = None,
) -> SafetyReview:
    """Answer a Tier B hold with a contextual assessment, in either direction.

    Fails closed at every step: anything other than an affirmative,
    successfully-parsed clean assessment returns ``review`` untouched.

    Args:
        review: The deterministic Tier B hold to resolve.
        text: The hypothesis text the hold was computed from.
        run_id: Run the hypothesis belongs to, for offline/approval gating.
        db_path: Optional override for the SQLite database path.

    Returns:
        An ALLOW, a PROHIBITED, or ``review`` unchanged when the
        assessment did not run or did not resolve the question.
    """
    if not is_resolvable_hold(review):
        return review
    from app import safety as app_safety

    decision = await app_safety.assess_hold_contextually(
        run_id, text, _STAGE, db_path=db_path
    )
    if decision is None:
        return review
    if decision.decision == "block":
        return _raised(review, decision.reason, tuple(decision.matches))
    if decision.decision == "allow":
        logger.info(
            "Contextual assessment cleared a held hypothesis in run %s "
            "(category term %s).",
            run_id,
            ", ".join(review.matches) or "unrecorded",
        )
        return _cleared(review)
    return review
