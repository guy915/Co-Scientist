"""Deciding which hypotheses still need deep verification.

The published rule is blanket and per-hypothesis: ``03-reflection.md``'s
``ReviewHypothesis(HypothesisID)`` runs the full review, then the deep
verification, and only then creates *that* hypothesis's
``AddToTournament`` task. So every idea is verified, exactly once, before
the tournament can rank it -- never a post-tournament slice of leaders.

Blanket is affordable only because it is incremental, so two independent
bounds decide the population here.

**The once-ever marker.** ``deep_verification_issued`` rides in
``enrichments``, which is checkpointed with the hypothesis, so a resumed
run does not re-fire the wave -- the same shape ``review_recheck`` uses,
and for the same reason: a marker held only in memory turns a bounded,
once-per-idea cost into a fresh whole-pool wave on every restart. It is
written when the attempt is *issued*, not when it succeeds, because a
failed attempt has still been spent and re-firing on failure is how a
bounded wave becomes a per-cycle one for exactly the ideas the verifier
keeps failing on. Evolution children are fresh ``Hypothesis`` objects
with empty enrichments, so each cycle's new ideas are funded without
re-funding the ones already verified.

**The freshness fingerprint**, unchanged and now subordinate: each stored
verification records a digest of what produced it -- the hypothesis text,
the verifier model, the prompt version, and the evidence the hypothesis
cites. It still decides that an idea carrying a *matching* verification
needs none, which is what an in-place text rewrite or a restored
checkpoint depends on. It deliberately does not decide the opposite: the
marker outranks a stale fingerprint, because probe retrieval adds
citations to the very hypothesis it verified, so fingerprint staleness
alone would re-verify the whole pool on every cycle -- the pool x cycles
cost this node exists to not have.

Ideas the review gate barred are skipped outright. Verification now
guards tournament entry, and an idea that cannot enter a tournament has
nothing here to protect; the published order agrees, gating the deeper
reviews on the initial review's discard ("Full review. If a hypothesis
passes the initial review...").
"""

import hashlib
import json

from co_scientist.models import Hypothesis

# Enrichment key recording that this hypothesis has had its one deep
# verification. Checkpointed with the hypothesis (see the module
# docstring), so a resume cannot re-fire the wave.
VERIFICATION_MARKER = "deep_verification_issued"

# Bump whenever the deep-verification prompt or schema changes in a way that
# would produce a different answer to the same question. Verifications
# carrying an older version are re-run rather than trusted, since the stored
# probes were produced by a prompt this code no longer sends.
# 2: the verification gained sub-assumption decomposition and
# decontextualization (audit E4) and a fail-closed ``unverified`` verdict
# (audit E9). Moving the node ahead of the tournament did not bump this:
# the prompt and schema are unchanged, only which hypotheses are asked.
DEEP_VERIFICATION_PROMPT_VERSION = 2


def _cited_evidence_identities(hypothesis: Hypothesis) -> list[str]:
    """Return stable identities for the evidence a hypothesis cites.

    Only cited sources count. The evidence context handed to the verifier
    is assembled run-wide, so hashing all of it would make any new article
    anywhere invalidate every hypothesis's fingerprint and re-verify the
    whole leaderboard for evidence that never mentioned it.
    """
    identities = set()
    for key, source in (hypothesis.citation_map or {}).items():
        source = source if isinstance(source, dict) else {}
        identity = (
            source.get("source_id")
            or source.get("doi")
            or source.get("url")
            or source.get("title")
            or key
        )
        identities.add(str(identity))
    return sorted(identities)


def verification_fingerprint(hypothesis: Hypothesis, model_name: str) -> str:
    """Digest the inputs a deep verification would be produced from.

    Covers the hypothesis text, the verifier model, the prompt version, and
    the evidence the hypothesis cites. Two verifications with the same
    fingerprint would be asked the same question against the same material,
    so the stored answer still holds and the call can be skipped.

    Args:
        hypothesis: The hypothesis that would be verified.
        model_name: Verifier model the call would run on.

    Returns:
        A hex digest to compare against the hypothesis's stored value.
    """
    payload = json.dumps(
        {
            "prompt_version": DEEP_VERIFICATION_PROMPT_VERSION,
            "model": model_name,
            "text": " ".join((hypothesis.text or "").split()),
            "evidence": _cited_evidence_identities(hypothesis),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verification_issued(hypothesis: Hypothesis) -> bool:
    """Return whether this hypothesis has already had its one attempt."""
    return bool(hypothesis.enrichments.get(VERIFICATION_MARKER))


def mark_verification_issued(hypothesis: Hypothesis) -> None:
    """Record the verification attempt, before its answer is known."""
    hypothesis.enrichments[VERIFICATION_MARKER] = True


def _needs_verification(hypothesis: Hypothesis, model_name: str) -> bool:
    """Return whether one hypothesis is owed a deep verification now.

    Three conditions, in the order they eliminate the most work: an idea
    barred from the tournament has nothing to guard, an idea that already
    spent its one attempt gets no second, and an idea already carrying a
    verification produced from the inputs it still has needs no repeat.
    """
    if not hypothesis.is_rankable():
        return False
    if verification_issued(hypothesis):
        return False
    return hypothesis.deep_verification_fingerprint != (
        verification_fingerprint(hypothesis, model_name)
    )


def _select_hypotheses_to_verify(
    hypotheses: list[Hypothesis],
    model_name: str,
) -> list[Hypothesis]:
    """Picks every rankable hypothesis still owed its one verification.

    Blanket over the pool rather than top-k by Elo, because verification
    now runs *before* the tournament: there is no Elo ordering to select
    by yet, and the published listing verifies each hypothesis on the way
    into the tournament rather than a slice of it afterwards.

    Args:
        hypotheses: The full hypothesis pool.
        model_name: Verifier model the batch would run on.

    Returns:
        The hypotheses to verify now, in pool order.
    """
    return [
        hypothesis
        for hypothesis in hypotheses
        if _needs_verification(hypothesis, model_name)
    ]
