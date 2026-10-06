"""Textual diversity must not use engine Elo as ground truth; that would be
circular.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def hypothesis_diversity(texts: Sequence[str]) -> float:
    if len(texts) < 2:
        return 0.0
    distances = [
        1.0 - _jaccard(a, b) for a, b in itertools.combinations(texts, 2)
    ]
    return round(sum(distances) / len(distances), 4)
