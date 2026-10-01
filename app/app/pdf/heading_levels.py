"""Shared helper for the heading cascade: compress raw ranks to levels.

Every signal in the cascade -- numbering families, bookmark depths, style
clusters -- ends the same way: take whichever raw, sortable rank each
candidate line actually got, and turn the *distinct* ranks present into
contiguous 1-based heading levels. A document that only ever reaches two
of a five-tier numbering scheme should get levels 1 and 2, not 1 and 4.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import TypeVar

_Key = TypeVar("_Key", bound=Hashable)
_Rank = TypeVar("_Rank", bound=Hashable)


def compress_to_levels(raw: dict[_Key, _Rank]) -> dict[_Key, int]:
    """Map each key's raw rank to a contiguous 1-based level.

    ``_Rank`` values must be mutually orderable (an int depth, a
    ``(family_rank, depth)`` tuple, a ``(cluster, bold, caps)`` tuple --
    every rank type this cascade actually produces).
    """
    if not raw:
        return {}
    # _Rank is bound to Hashable, not Comparable -- mypy cannot see that
    # every rank type this cascade actually produces (int, and tuples of
    # int/bool) supports ordering, though all of them do.
    ordered = sorted(set(raw.values()))  # type: ignore[type-var]
    rank_to_level = {rank: level for level, rank in enumerate(ordered, start=1)}
    return {key: rank_to_level[rank] for key, rank in raw.items()}
