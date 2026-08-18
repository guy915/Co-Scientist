"""Locating a hunk's anchor in a file, and the two rules that govern it.

**A ladder, not a score.** Matching descends four rungs -- exact, then
ignoring trailing whitespace, then ignoring leading and trailing
whitespace, then normalizing the Unicode punctuation a model is prone to
substitute for ASCII. Each rung is a defined equivalence, so a match at
any rung means "these lines are the same modulo a stated difference".
That is very different from a similarity threshold, which answers "close
enough" and has no principled value.

**A cursor, not a best match.** Hunks are applied in file order and each
search begins where the previous one ended. Ambiguity is therefore
resolved by position rather than by picking the "best" of several
candidates: when a file contains the same three lines in four places, the
first hunk takes the first occurrence and the second takes the second,
which is what the patch's own ordering already said. Scoring would have
to break that tie some other way, and any way it breaks it is a guess.
"""

import unicodedata
from dataclasses import dataclass

# Characters a model substitutes for their ASCII equivalents, usually via
# a smart-quotes pass somewhere upstream. Normalizing these is what stops
# a correct edit failing because a quote changed shape in transit.
_PUNCTUATION_EQUIVALENTS = {
    # Written as escapes, not literals: these are precisely the
    # characters that are hard to tell apart on sight, which is why they
    # need folding in the first place.
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201a": "'",  # single low-9 quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u201e": '"',  # double low-9 quotation mark
    "\u2032": "'",  # prime
    "\u2033": '"',  # double prime
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u00a0": " ",  # no-break space
    "\u2026": "...",  # horizontal ellipsis
}


def _normalize_punctuation(text: str) -> str:
    """Folds look-alike Unicode punctuation to its ASCII equivalent."""
    folded = unicodedata.normalize("NFC", text)
    for source, target in _PUNCTUATION_EQUIVALENTS.items():
        folded = folded.replace(source, target)
    return folded


# The ladder, most exact first. Each entry is a canonicalization applied
# to both sides before comparison; equality under it defines that rung.
_LADDER = (
    ("exact", lambda line: line),
    ("trailing-whitespace", lambda line: line.rstrip()),
    ("surrounding-whitespace", lambda line: line.strip()),
    (
        "unicode-punctuation",
        lambda line: _normalize_punctuation(line).strip(),
    ),
)


@dataclass(frozen=True)
class SeekResult:
    """Where an anchor was found, and how exactly it matched.

    Attributes:
        start: Index of the first matching line.
        end: Index one past the last matching line.
        rung: Which ladder rung matched, for reporting. An edit that
            only applied after whitespace folding is worth being able to
            say so.
    """

    start: int
    end: int
    rung: str


def _matches_at(
    lines: list[str],
    anchor: tuple[str, ...],
    index: int,
    canonicalize: object,
) -> bool:
    """Reports whether the anchor matches at index under one rung."""
    fold = canonicalize  # narrowed by the caller; kept callable-typed
    assert callable(fold)
    return all(
        fold(lines[index + offset]) == fold(text)
        for offset, text in enumerate(anchor)
    )


def _first_match_on_rung(
    lines: list[str],
    anchor: tuple[str, ...],
    start: int,
    rung: str,
    fold: object,
) -> SeekResult | None:
    """Scans for the anchor under a single ladder rung."""
    last = len(lines) - len(anchor)
    for index in range(start, last + 1):
        if _matches_at(lines, anchor, index, fold):
            return SeekResult(index, index + len(anchor), rung)
    return None


def seek_anchor(
    lines: list[str], anchor: tuple[str, ...], start: int = 0
) -> SeekResult | None:
    """Finds a hunk's anchor at or after ``start``.

    Args:
        lines: The file's lines, without terminators.
        anchor: The context and removal lines the hunk expects.
        start: Index to search from -- the monotonic cursor, which is
            what makes repeated identical blocks resolve in order.

    Returns:
        Where the anchor matched, or None if no rung matched anywhere at
        or after ``start``.
    """
    if not anchor:
        return SeekResult(start, start, "empty")
    if len(lines) - len(anchor) < start:
        return None

    # Rung-major: a whole-file scan at an exact match is preferred over
    # a nearer approximate one, so a file containing both is edited at
    # the place that genuinely matches.
    for rung, fold in _LADDER:
        found = _first_match_on_rung(lines, anchor, start, rung, fold)
        if found is not None:
            return found
    return None
