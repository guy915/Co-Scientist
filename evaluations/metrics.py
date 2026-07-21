"""Reproducible hypothesis-quality metrics.

Pure, deterministic metric functions over a hypothesis pool: hypothesis
*diversity* and the *generation-vs-evolution yield/diversity* split. These do
not use the engine's own Elo as ground truth, which would be circular; they
measure the pool's textual spread and where hypotheses came from, which the
Supervisor's summary statistics and the scaling/ablation harnesses consume.

Elo-versus-known-answer calibration and test-time-compute scaling curves need an
appropriately licensed question set and/or provider credentials and are recorded
as external gaps in the ledger; these tractable, offline metrics are the pieces
that run in CI with no LLM.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any


def _tokens(text: str) -> frozenset[str]:
    """Content tokens (length > 3) for the textual-distance signal."""
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _jaccard(a: str, b: str) -> float:
    """Jaccard token overlap of two texts in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def hypothesis_diversity(texts: Sequence[str]) -> float:
    """Return the mean pairwise textual distinctness of a hypothesis pool.

    Distinctness is ``1 - jaccard`` averaged over all unordered pairs, so 1.0
    means every hypothesis is lexically disjoint and 0.0 means they are
    identical. A pool with fewer than two hypotheses has no pairs; its
    diversity is defined as 0.0.

    Args:
        texts: The hypothesis texts.

    Returns:
        Mean pairwise distinctness in [0, 1].
    """
    if len(texts) < 2:
        return 0.0
    distances = [
        1.0 - _jaccard(a, b) for a, b in itertools.combinations(texts, 2)
    ]
    return round(sum(distances) / len(distances), 4)


def generation_vs_evolution_yield(
    hypotheses: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Split a pool into generation vs evolution and report yield + diversity.

    Each hypothesis dict carries an ``origin`` ("generation"/"evolution"/
    "scientist_manual") and ``text``. Yield is the count from each origin;
    diversity is the pool-diversity metric within each origin group. This is
    the observable Google's Supervisor weights (relative effectiveness of
    generation vs. evolution, SSR §4) rendered as a reproducible metric.

    Args:
        hypotheses: Serialized hypotheses (``origin`` + ``text``).

    Returns:
        A report with per-origin counts, per-origin diversity, and the overall
        pool diversity.
    """
    by_origin: dict[str, list[str]] = {}
    for hyp in hypotheses:
        origin = str(hyp.get("origin", "generation"))
        by_origin.setdefault(origin, []).append(str(hyp.get("text", "")))

    return {
        "counts": {origin: len(texts) for origin, texts in by_origin.items()},
        "diversity_by_origin": {
            origin: hypothesis_diversity(texts)
            for origin, texts in by_origin.items()
        },
        "overall_diversity": hypothesis_diversity(
            [str(h.get("text", "")) for h in hypotheses]
        ),
        "n": len(hypotheses),
    }
