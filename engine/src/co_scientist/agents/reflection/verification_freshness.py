"""Deciding which hypotheses still need deep verification.

Deep verification used to re-run on whatever leader lacked probes. That
proxy cannot tell a stale verification from a current one: a hypothesis
kept whatever verdict it was first given for the rest of the run even
after the evidence under it moved, and only evolution rewriting its text
ever cleared it.

Instead each stored verification records a fingerprint of what produced it
-- the hypothesis text, the verifier model, the prompt version, and the
evidence the hypothesis cites. A leader whose fingerprint still matches is
reused; one whose inputs moved, or which was only just promoted into the
top-k and has no fingerprint at all, is verified.
"""

import hashlib
import json

from co_scientist.constants import DEEP_VERIFICATION_TOP_K
from co_scientist.models import Hypothesis, rank_by_elo

# Bump whenever the deep-verification prompt or schema changes in a way that
# would produce a different answer to the same question. Verifications
# carrying an older version are re-run rather than trusted, since the stored
# probes were produced by a prompt this code no longer sends.
# 2: the verification gained sub-assumption decomposition and
# decontextualization (audit E4) and moved to post-tournament leaders with
# a fail-closed ``unverified`` verdict (audit E9).
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


def _select_hypotheses_to_verify(
    hypotheses: list[Hypothesis],
    model_name: str,
) -> list[Hypothesis]:
    """Picks the current Elo leaders whose verification is stale or missing.

    A leader is re-verified when the inputs behind its stored probes have
    changed -- its text was rewritten, the verifier model or prompt moved,
    or evidence it cites arrived -- and skipped when they have not. A newly
    promoted leader has no stored fingerprint at all, so it is always
    verified.

    This replaces testing whether probes exist. That proxy could not tell a
    stale verification from a current one: a hypothesis kept whatever
    verdict it was first given for the rest of the run, even after the
    evidence under it changed, and only evolution rewriting its text
    cleared it.

    Args:
        hypotheses: The full hypothesis pool.
        model_name: Verifier model the batch would run on.

    Returns:
        Top-k-by-Elo hypotheses needing verification, in rank order.
    """
    ranked = rank_by_elo(hypotheses)
    top_k = ranked[:DEEP_VERIFICATION_TOP_K]
    return [
        hypothesis
        for hypothesis in top_k
        if hypothesis.deep_verification_fingerprint
        != verification_fingerprint(hypothesis, model_name)
    ]
