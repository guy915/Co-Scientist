"""Legal/outline numbering inference for PDF heading detection.

Parses a leading numbering marker off a line of text -- ``1.``, ``1.1``,
``PART I``, ``A.``, ``(a)``, ``(i)`` -- and orders the schemes actually
present in a document into contiguous heading levels. This module never
imports ``pypdf``: it works on plain strings so its logic can be tested
without touching a PDF parser at all.

A single-letter marker such as ``I.`` is inherently ambiguous -- it could
be the Roman numeral 1 or the alpha marker for item 9 -- so it is resolved
using whichever unambiguous family (Roman or alpha) the rest of the
document's markers establish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.pdf_heading_levels import compress_to_levels

# Precedence of numbering schemes, highest (outermost) first. ``dotted``
# shares the ``arabic`` rank and is broken by its own segment depth, so
# ``1.`` sits above ``1.1`` without needing a separate family slot.
_FAMILY_ORDER = [
    "part",
    "chapter",
    "article",
    "roman_u",
    "arabic",
    "alpha_u",
    "alpha_l",
    "roman_l",
]

# Single letters that are valid Roman numerals and so ambiguous with a
# plain alpha marker (e.g. "I." could be Roman one or letter nine).
_ROMAN_SINGLES = set("IVXLCDMivxlcdm")

_ROMAN_RE = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_KW_PART = re.compile(r"^(part|title|book)\b", re.IGNORECASE)
_KW_CHAPTER = re.compile(r"^chapter\b", re.IGNORECASE)
_KW_ARTICLE = re.compile(
    r"^(?:(?:article|section|clause|schedule|annex|appendix|rule)\b"
    r"|§+\s*\d)",
    re.IGNORECASE,
)
# Dotted decimal outline (1.1, 1.1.1, ...), terminated by punctuation
# or whitespace so "1.1x" (a unit, not a marker) does not match.
_DOTTED = re.compile(r"^(\d+(?:\.\d+)+)(?:[.)\]\s]|$)")
_ARABIC = re.compile(r"^(\d+)[.)]")
_LETTER = re.compile(r"^\(?\s*([A-Za-z]+)\s*[).]")


@dataclass
class _Marker:
    """A parsed leading numbering marker."""

    family: str
    depth: int = 1  # dotted-decimal segment count; 1 for every other kind
    token: str | None = None  # raw letter token, kept for ambiguity resolution
    ambiguous: bool = False


def _is_roman(token: str) -> bool:
    return bool(token) and _ROMAN_RE.fullmatch(token) is not None


def _classify_letter(token: str) -> _Marker | None:
    """Turn a bare letter token (``A``, ``iv``, ``i``) into a marker."""
    upper = token.isupper()
    if len(token) == 1:
        if token in _ROMAN_SINGLES:
            family = "roman_u" if upper else "roman_l"
            return _Marker(family=family, token=token, ambiguous=True)
        return _Marker(family="alpha_u" if upper else "alpha_l", token=token)
    # A multi-letter token only counts as numbering when it is a genuine
    # Roman numeral; otherwise it is a word ("Summary.") wearing a marker
    # shape by coincidence.
    if _is_roman(token):
        return _Marker(family="roman_u" if upper else "roman_l", token=token)
    return None


def _match_keyword(stripped: str) -> _Marker | None:
    if _KW_PART.match(stripped):
        return _Marker(family="part")
    if _KW_CHAPTER.match(stripped):
        return _Marker(family="chapter")
    if _KW_ARTICLE.match(stripped):
        return _Marker(family="article")
    return None


def _match_dotted(stripped: str) -> _Marker | None:
    match = _DOTTED.match(stripped)
    if match is None:
        return None
    return _Marker(family="dotted", depth=match.group(1).count(".") + 1)


def _match_arabic(stripped: str) -> _Marker | None:
    if _ARABIC.match(stripped):
        return _Marker(family="arabic")
    return None


def _match_letter(stripped: str) -> _Marker | None:
    match = _LETTER.match(stripped)
    if match is None:
        return None
    return _classify_letter(match.group(1))


def _parse_marker(text: str) -> _Marker | None:
    """Extract the leading numbering marker, or None if there is none."""
    stripped = text.strip()
    if not stripped:
        return None
    for classify in (
        _match_keyword,
        _match_dotted,
        _match_arabic,
        _match_letter,
    ):
        marker = classify(stripped)
        if marker is not None:
            return marker
    return None


def _has_unambiguous(markers: list[_Marker | None], family: str) -> bool:
    return any(
        m is not None and not m.ambiguous and m.family == family
        for m in markers
    )


def _resolve_one_ambiguous(
    marker: _Marker, has_roman: bool, has_alpha: bool
) -> None:
    upper = marker.token is not None and marker.token.isupper()
    if has_roman and not has_alpha:
        roman = True
    elif has_alpha and not has_roman:
        roman = False
    else:
        roman = marker.token in ("I", "i")
    marker.family = (
        ("roman_u" if roman else "alpha_u")
        if upper
        else ("roman_l" if roman else "alpha_l")
    )
    marker.ambiguous = False


def _resolve_ambiguous(markers: list[_Marker | None]) -> None:
    """Resolve single-letter Roman/alpha markers using document context.

    A lone ``I.`` reads as Roman when the document also carries an
    unambiguous Roman sibling (``II``, ``III``, ...) and as alpha when it
    carries an unambiguous alpha sibling (``B``, ``F``, ...). With no
    evidence either way, ``I``/``i`` default to Roman (the common legal
    reading) and any other letter defaults to alpha.
    """
    upper_roman = _has_unambiguous(markers, "roman_u")
    upper_alpha = _has_unambiguous(markers, "alpha_u")
    lower_roman = _has_unambiguous(markers, "roman_l")
    lower_alpha = _has_unambiguous(markers, "alpha_l")
    for marker in markers:
        if marker is None or not marker.ambiguous:
            continue
        is_upper = marker.token is not None and marker.token.isupper()
        has_roman = upper_roman if is_upper else lower_roman
        has_alpha = upper_alpha if is_upper else lower_alpha
        _resolve_one_ambiguous(marker, has_roman, has_alpha)


def _family_rank(family: str) -> int:
    key = "arabic" if family == "dotted" else family
    try:
        return _FAMILY_ORDER.index(key)
    except ValueError:
        return len(_FAMILY_ORDER)


def infer_numbering_levels(lines: list[str]) -> dict[int, int]:
    """Map each numbered line's index to a 1-based heading level.

    Levels are compressed from the (family, depth) keys actually present
    in ``lines``, so a document that starts at "1." begins at level 1
    rather than being forced to leave room for an absent "PART" level.
    Lines with no recognizable marker are absent from the result.
    """
    markers = [_parse_marker(line) for line in lines]
    _resolve_ambiguous(markers)

    keys: dict[int, tuple[int, int]] = {
        index: (_family_rank(marker.family), marker.depth)
        for index, marker in enumerate(markers)
        if marker is not None
    }
    return compress_to_levels(keys)
