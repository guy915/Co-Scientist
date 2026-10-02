"""Recover PDF headings from bookmarks, numbering, then font styles.

Signals are ranked across the whole document, with bookmarks taking
precedence. Unmatched lines retain their extracted text. The helpers use
plain data; only the page style collector requires pypdf's visitor API.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Hashable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, TypeVar

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


# A confident match must clear this similarity ratio (0..1). Below it, a
# coincidentally similar line is worse than leaving the bookmark unmatched.
_MATCH_THRESHOLD = 0.72

# A leading numbering marker, stripped before comparison so a bookmark
# titled "Background" still matches an on-page "1.1 Background".
_LEADING_MARKER = re.compile(
    r"^\s*(?:\(?[0-9]+(?:\.[0-9]+)*[).]?|\(?[A-Za-z]{1,2}[).])[\s.:)\-]*"
)


def _norm(text: str) -> str:
    """Lower-case, collapse whitespace, and trim outer punctuation."""
    collapsed = re.sub(r"\s+", " ", text.lower()).strip()
    return re.sub(r"^[\W_]+|[\W_]+$", "", collapsed)


def _match_score(line: str, title: str) -> float:
    """Similarity in 0..1, comparing both strings with and without a marker."""
    variants_a = {_norm(line), _norm(_LEADING_MARKER.sub("", line))} - {""}
    variants_b = {_norm(title), _norm(_LEADING_MARKER.sub("", title))} - {""}
    best = 0.0
    for a in variants_a:
        for b in variants_b:
            best = max(best, SequenceMatcher(None, a, b).ratio())
            if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
                best = max(best, 0.92)
    return best


def _best_match(title: str, lines: list[str], claimed: set[int]) -> int | None:
    best_index: int | None = None
    best_score = _MATCH_THRESHOLD
    for index, line in enumerate(lines):
        if index in claimed:
            continue
        score = _match_score(line, title)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def raw_bookmark_matches(
    outline: list[tuple[str, int]], lines: list[str]
) -> dict[int, int]:
    """Match each bookmark to at most one line; depths are not yet compressed.

    Each line is claimed by at most one bookmark (first confident match
    wins, in outline order), so two similarly-titled bookmarks cannot both
    land on the same line.
    """
    claimed: set[int] = set()
    matches: dict[int, int] = {}
    for title, depth in outline:
        if not title.strip():
            continue
        index = _best_match(title, lines, claimed)
        if index is not None:
            claimed.add(index)
            matches[index] = depth
    return matches


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


# Sizes within this relative tolerance of each other collapse into one
# cluster, so measurement jitter cannot manufacture a spurious heading
# level between two lines set in the same nominal size.
_SIZE_TOLERANCE = 0.08

# A heading candidate line must be short: a long line at a bigger size is
# more likely a pull quote or a table cell than a section title.
MAX_HEADING_CHARS = 120


@dataclass(frozen=True)
class LineStyle:
    """The visual style of one candidate heading line."""

    size: float
    bold: bool
    all_caps: bool


def _is_all_caps(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return len(letters) >= 4 and all(char.isupper() for char in letters)


def _is_bold(font_dict: Any) -> bool:
    """Guess boldness from the font's own name (no embedded-font parsing).

    Standard and subsetted PDF fonts alike carry their weight in the
    ``/BaseFont`` name (``Helvetica-Bold``, ``ABCDEF+Arial-BoldMT``), so a
    substring check covers both without needing the font's descriptor.
    """
    if not isinstance(font_dict, dict):
        return False
    base_font = str(font_dict.get("/BaseFont", ""))
    lowered = base_font.lower()
    return "bold" in lowered or "black" in lowered or "heavy" in lowered


def _effective_size(font_size: float, tm_matrix: list[float]) -> float:
    """Font size actually rendered, after the text matrix's own scaling.

    A generator that sets ``Tf 1`` and scales through ``Tm`` instead would
    report every run at size 1.0 if the raw ``Tf`` value were trusted, so
    the vertical scale of the text matrix is folded in.
    """
    scale = math.hypot(tm_matrix[1], tm_matrix[3])
    return font_size * (scale or 1.0)


class _LineCollector:
    r"""Groups pypdf's per-run visitor callbacks into per-line style votes.

    A run boundary (font change, positioning op) does not by itself end a
    line -- only an embedded ``"\n"`` does, which pypdf appends to the run
    text that precedes a detected line break.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, float, bool]] = []
        self._text = ""
        self._max_size = 0.0
        self._bold_chars = 0
        self._plain_chars = 0

    def _flush_line(self) -> None:
        if self._text.strip():
            bold = self._bold_chars >= self._plain_chars
            self.lines.append((self._text, self._max_size, bold))
        self._text = ""
        self._max_size = 0.0
        self._bold_chars = 0
        self._plain_chars = 0

    def __call__(
        self,
        text: str,
        _cm_matrix: list[float],
        tm_matrix: list[float],
        font_dict: Any,
        font_size: float,
    ) -> None:
        size = _effective_size(font_size, tm_matrix)
        bold = _is_bold(font_dict)
        segments = text.split("\n")
        for index, segment in enumerate(segments):
            if segment:
                self._text += segment
                self._max_size = max(self._max_size, size)
                if bold:
                    self._bold_chars += len(segment)
                else:
                    self._plain_chars += len(segment)
            if index < len(segments) - 1:
                self._flush_line()


def collect_line_styles(page: Any) -> dict[str, LineStyle]:
    """Map each short candidate line's own text to its rendered style.

    Runs a second, ``visitor_text``-driven extraction pass over the page
    (the layout-mode pass used for the page's actual output text ignores
    ``visitor_text`` entirely). Keyed by the line's stripped text rather
    than position, since the two passes reconstruct lines independently
    and are matched back together by content in the document-wide cascade.
    """
    collector = _LineCollector()
    page.extract_text(visitor_text=collector)
    collector._flush_line()
    styles: dict[str, LineStyle] = {}
    for text, size, bold in collector.lines:
        stripped = text.strip()
        if not stripped or len(stripped) > MAX_HEADING_CHARS:
            continue
        styles.setdefault(
            stripped,
            LineStyle(size=size, bold=bold, all_caps=_is_all_caps(stripped)),
        )
    return styles


def _cluster_sizes(sizes: set[float]) -> dict[float, int]:
    """Group sizes into clusters, largest first; map size -> cluster index."""
    clusters: dict[float, int] = {}
    index = 0
    previous: float | None = None
    for size in sorted(sizes, reverse=True):
        gap = previous - size if previous is not None else 0.0
        if previous is not None and gap > _SIZE_TOLERANCE * previous:
            index += 1
        clusters[size] = index
        previous = size
    return clusters


def rank_heading_styles(
    styles: dict[int, LineStyle], body_size: float
) -> dict[int, int]:
    """Rank lines strictly larger than the body size into heading levels.

    Order: font size first (with near-equal sizes merged), then weight
    (bold above regular), then case (all-caps above mixed) as the
    tie-break within a shared size cluster. A line at or below the body
    size is not a heading candidate at all -- it is caption- or
    footnote-scaled, not emphasized -- and is left out of the result.
    """
    candidates = {
        index: style
        for index, style in styles.items()
        if style.size > body_size
    }
    if not candidates:
        return {}

    clusters = _cluster_sizes({style.size for style in candidates.values()})
    keys = {
        index: (clusters[style.size], not style.bold, not style.all_caps)
        for index, style in candidates.items()
    }
    return compress_to_levels(keys)


# ATX only goes to h3 here: a fourth inferred level is rare enough in a
# scientist's attached paper that flattening it into h3 costs less than
# the added complexity of a deeper cascade would.
_MAX_LEVEL = 3


def _walk_outline(
    reader: Any, items: Any, depth: int, out: list[tuple[str, int, int]]
) -> None:
    """Depth-first walk of pypdf's nested-list outline structure."""
    for item in items:
        if isinstance(item, list):
            _walk_outline(reader, item, depth + 1, out)
            continue
        title = getattr(item, "title", None)
        if not title:
            continue
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:  # a dangling /Dest reference costs one bookmark
            continue
        out.append((str(title), depth, page_index))


def flatten_outline(reader: Any) -> list[tuple[str, int, int]]:
    """Flatten ``reader.outline`` into (title, nesting depth, page index).

    Raises whatever ``reader.outline`` itself raises (including on a
    reader that carries no such attribute at all) -- the caller is
    responsible for the fail-soft boundary around the whole cascade.
    """
    outline = reader.outline
    if not outline:
        return []
    out: list[tuple[str, int, int]] = []
    _walk_outline(reader, outline, 1, out)
    return out


def _pool_bookmark_levels(
    outline: list[tuple[str, int, int]], lines_per_page: list[list[str]]
) -> dict[tuple[int, int], int]:
    """Match bookmarks per page, then compress raw depths once, globally."""
    raw: dict[tuple[int, int], int] = {}
    for page_index, lines in enumerate(lines_per_page):
        page_outline = [
            (title, depth)
            for title, depth, page in outline
            if page == page_index
        ]
        if not page_outline:
            continue
        matches = raw_bookmark_matches(page_outline, lines)
        for line_index, depth in matches.items():
            raw[(page_index, line_index)] = depth
    return compress_to_levels(raw)


def _pool_numbering_levels(
    lines_per_page: list[list[str]],
) -> dict[tuple[int, int], int]:
    positions = [
        (page_index, line_index, line.strip())
        for page_index, lines in enumerate(lines_per_page)
        for line_index, line in enumerate(lines)
        if line.strip() and len(line.strip()) <= MAX_HEADING_CHARS
    ]
    levels = infer_numbering_levels([text for *_, text in positions])
    return {
        (positions[i][0], positions[i][1]): level for i, level in levels.items()
    }


def _pool_style_levels(
    pages: list[Any], lines_per_page: list[list[str]]
) -> dict[tuple[int, int], int]:
    per_page_styles = [collect_line_styles(page) for page in pages]
    all_sizes: list[float] = []
    for styles in per_page_styles:
        all_sizes.extend(style.size for style in styles.values())
    if not all_sizes:
        return {}
    body_size = Counter(round(size, 1) for size in all_sizes).most_common(1)[0][
        0
    ]
    candidates = [
        ((page_index, line_index), style)
        for page_index, lines in enumerate(lines_per_page)
        for line_index, line in enumerate(lines)
        if (style := per_page_styles[page_index].get(line.strip())) is not None
    ]
    ranked = rank_heading_styles(
        {index: style for index, (_, style) in enumerate(candidates)}, body_size
    )
    return {candidates[index][0]: level for index, level in ranked.items()}


def _combine_levels(
    bookmark: dict[tuple[int, int], int],
    numbering: dict[tuple[int, int], int],
    style: dict[tuple[int, int], int],
) -> dict[tuple[int, int], int]:
    combined = {**style, **numbering, **bookmark}
    return {
        key: max(1, min(level, _MAX_LEVEL)) for key, level in combined.items()
    }


def _rewrite_lines(
    lines_per_page: list[list[str]], levels: dict[tuple[int, int], int]
) -> list[str]:
    pages_out = []
    for page_index, lines in enumerate(lines_per_page):
        rewritten = list(lines)
        for line_index, line in enumerate(lines):
            level = levels.get((page_index, line_index))
            if level is not None:
                rewritten[line_index] = "#" * level + " " + line.strip()
        pages_out.append("\n".join(rewritten))
    return pages_out


def apply_heading_markup(
    reader: Any, pages: list[Any], pages_text: list[str]
) -> list[str]:
    """Weave inferred ATX heading markers into per-page extracted text.

    ``pages_text`` is the page text produced by plain extraction, one
    entry per page in ``pages``/``reader.pages`` order. Returns a same-
    length list; a line no signal reaches is copied through unchanged.
    """
    lines_per_page = [text.split("\n") for text in pages_text]
    outline = flatten_outline(reader)
    bookmark_levels = _pool_bookmark_levels(outline, lines_per_page)
    numbering_levels = _pool_numbering_levels(lines_per_page)
    style_levels = _pool_style_levels(pages, lines_per_page)
    levels = _combine_levels(bookmark_levels, numbering_levels, style_levels)
    return _rewrite_lines(lines_per_page, levels)
