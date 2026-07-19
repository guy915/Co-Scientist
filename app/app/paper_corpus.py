"""The SBI/UCD paper corpus: sanitation and the injected paper catalog.

The lab's papers extract to roughly 330k tokens of raw `pdftotext` output,
about 30% of which is references, page furniture, and figure/equation glyphs
fragmented into single letters. `sanitize` cleans one paper for storage; the
sanitized papers live on disk and the MCP `fetch_paper` tool reads any one of
them in full on demand.

The corpus reaches a run through a small, always-present catalog rather than
through retrieval: the title and abstract of every paper are injected into
the run's context (see `format_catalog`), so the model always knows the whole
of the group's library and can decide, from each abstract, which papers to
pull in full with `fetch_paper`. The catalog is a committed, reviewable file
(`catalog.json`) built offline from verified metadata, so nothing about which
papers exist or what they claim is decided at runtime.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import os
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

# Where sanitized papers live: `corpus/sbi_ucd` at the repository root, which
# is `app/app/paper_corpus.py` -> app/app -> app -> root. Override to point at
# a mounted copy in a deployment that does not ship the repository tree.
CORPUS_ENV_VAR = "SBI_CORPUS_DIR"
_DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus" / "sbi_ucd"

# The committed catalog: one entry per paper with its title, abstract, and the
# `paper_id` that `fetch_paper` takes. Built offline by
# `app/dev/build_catalog.py` from hand-verified metadata and reviewed before it
# ships, so runtime never derives an abstract from the messy sanitized text.
# That script is also where a new paper gets added; it records each abstract's
# provenance and refuses to write if catalog and corpus directory disagree.
CATALOG_FILENAME = "catalog.json"

# Everything from these headings to the end of the paper is back matter: the
# reference list alone is 21% of the corpus, and none of it states a finding.
# Trailing words are allowed because journals vary ("REFERENCES AND NOTES"),
# but the line must be short, so a sentence mentioning acknowledgements in
# passing does not truncate a paper.
_TAIL_HEADINGS = re.compile(
    r"^\s*(references|bibliography|literature cited|acknowledge?ments?"
    r"|author contributions?|competing interests?|conflicts? of interest"
    r"|declarations? of interests?|data availability|supplementary"
    r"\s+(information|material|methods|figures?|tables?))\b[\w\s&]{0,24}:?\s*$",
    re.IGNORECASE,
)

# Some journals print no heading at all -- the PNAS bibliography simply
# begins "1. Smolen, P., ... (1998)". A numbered line that also carries a
# year is the signature; requiring a year keeps numbered method steps out.
_CITATION_LINE = re.compile(r"^(\[\d{1,3}\]|\d{1,3}[.)])\s+[A-Z]")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")

# How dense citation-looking lines must be before we call it a bibliography.
# Long entries wrap onto continuation lines that match nothing, which dilutes
# any window, so the bar is under half and the run start is then recovered by
# walking backwards.
_CITATION_WINDOW = 12
_CITATION_MIN_HITS = 5

# How many consecutive non-citation lines end a backwards walk. Wrapped
# entries span two or three lines; prose runs longer than that.
_CITATION_MAX_GAP = 3

# Journal furniture repeats once per page ("OPEN ACCESS", the running DOI).
# A line recurring this often is boilerplate, not prose.
_FURNITURE_MIN_REPEATS = 4

# A word split across a line break by the typesetter: "resis-\ntance".
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")

_SENTENCE_END = (".", ",", ";", ":", "?", "!")


@dataclasses.dataclass(frozen=True)
class SanitationReport:
    """What sanitizing one paper removed, for logging and tests."""

    kept_chars: int
    dropped_chars: int

    @property
    def kept_fraction(self) -> float:
        """Share of the original text retained, 0.0 when nothing came in."""
        total = self.kept_chars + self.dropped_chars
        return self.kept_chars / total if total else 0.0


def _is_fragment(line: str) -> bool:
    """True for a line that is figure/equation debris rather than prose.

    `pdftotext` renders positioned glyphs one per line, so the cSTAR methods
    figure arrives as "ST", "V", "Hyperplane" on separate lines. Short lines
    that do not end in punctuation are the signature; a genuine short line of
    prose almost always closes with one.
    """
    return len(line) < 25 and not line.endswith(_SENTENCE_END)


def _looks_like_citation(line: str) -> bool:
    """True for a line shaped like a numbered bibliography entry."""
    return bool(_CITATION_LINE.match(line) and _YEAR.search(line))


def _bibliography_start(lines: list[str]) -> int:
    """Index where an unheaded bibliography begins, or len(lines).

    Scans for the first window in which citation-shaped lines dominate. A
    single numbered line proves nothing -- a methods list looks the same --
    but seven in twelve is a reference list.
    """
    flags = [_looks_like_citation(line.strip()) for line in lines]
    for start in range(len(lines)):
        if not flags[start]:
            continue
        window = flags[start : start + _CITATION_WINDOW]
        if sum(window) < _CITATION_MIN_HITS:
            continue
        # The window proves a bibliography is here, but its first entries may
        # have wrapped and diluted every earlier window. Walk back over the
        # continuation lines to the entry the list actually starts on.
        cut, gap, index = start, 0, start - 1
        while index >= 0 and gap <= _CITATION_MAX_GAP:
            if flags[index]:
                cut, gap = index, 0
            else:
                gap += 1
            index -= 1
        return cut
    return len(lines)


def sanitize(raw: str) -> tuple[str, SanitationReport]:
    """Strip references, back matter, page furniture, and figure debris.

    Args:
        raw: The text of one paper as produced by `pdftotext`.

    Returns:
        The sanitized text and a report of how much survived.
    """
    original = len(raw)
    # Rejoin words the typesetter split across lines before anything else, so
    # later steps see whole tokens and retrieval indexes real words.
    text = _HYPHEN_BREAK.sub(r"\1\2", raw)
    lines = text.split("\n")

    repeated = {
        line.strip()
        for line, count in Counter(ln.strip() for ln in lines).items()
        if count >= _FURNITURE_MIN_REPEATS and 8 < len(line.strip()) < 120
    }

    # Back matter ends the paper at whichever comes first: a heading that
    # names it, or the point where citations take over without one.
    cutoff = _bibliography_start(lines)

    kept: list[str] = []
    for index, line in enumerate(lines):
        if index >= cutoff:
            break
        stripped = line.strip()
        if _TAIL_HEADINGS.match(stripped):
            break
        if not stripped or stripped in repeated or _is_fragment(stripped):
            continue
        kept.append(stripped)

    body = "\n".join(kept)
    return body, SanitationReport(len(body), original - len(body))


def corpus_dir() -> Path:
    """Return the configured corpus directory."""
    override = os.environ.get(CORPUS_ENV_VAR)
    return Path(override) if override else _DEFAULT_CORPUS_DIR


# The corpus is one lab's library, so it is offered to that lab only. Other
# audiences neither see the catalog nor may fetch a paper: a non-corpus
# audience must not read another group's library at all.
CORPUS_AUDIENCE = "sbi_ucd"

# The engine reaches the corpus in full through this MCP tool. Withholding it
# from other audiences is the second half of the gate; the first is simply not
# injecting the catalog for them (see `catalog_context`).
CORPUS_FETCH_TOOL_ID = "paper_corpus_fetch"
CORPUS_TOOL_IDS = (CORPUS_FETCH_TOOL_ID,)


@dataclasses.dataclass(frozen=True)
class CatalogPaper:
    """One paper in the injected catalog: what the model sees at a glance."""

    paper_id: str
    title: str
    abstract: str


@functools.cache
def load_catalog(directory: Path | None = None) -> tuple[CatalogPaper, ...]:
    """Load the committed paper catalog, or an empty tuple when absent.

    The catalog is static, so it is read and cached once. An absent or
    malformed file yields an empty catalog rather than raising: a deployment
    without the corpus is the normal keyless/non-SBI state, not an error.

    Args:
        directory: Where the corpus (and its `catalog.json`) live. Defaults to
            the configured corpus directory. Passed only by tests installing a
            different corpus; production always uses the default.

    Returns:
        The catalog papers in file order, or an empty tuple.
    """
    root = directory or corpus_dir()
    path = root / CATALOG_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("no readable paper catalog at %s: %s", path, exc)
        return ()
    papers: list[CatalogPaper] = []
    for item in raw.get("papers", []):
        paper_id = str(item.get("paper_id") or "").strip()
        title = str(item.get("title") or "").strip()
        abstract = str(item.get("abstract") or "").strip()
        if paper_id and title and abstract:
            papers.append(CatalogPaper(paper_id, title, abstract))
    logger.debug("loaded %d catalog papers from %s", len(papers), path)
    return tuple(papers)


def format_catalog(papers: tuple[CatalogPaper, ...]) -> str:
    """Render the catalog as a prompt block, or empty when there are none.

    Each entry prints its `paper_id` so the model can pass it to `fetch_paper`;
    the header names that follow-up explicitly, since the catalog is now the
    only place those ids are advertised.

    Args:
        papers: The catalog papers to render.

    Returns:
        A titled block listing every paper's title, id, and abstract, or an
        empty string when the catalog is empty.
    """
    if not papers:
        return ""
    lines = [
        "## The research group's own papers",
        "",
        "These are the group's published papers. The title and abstract of "
        "every paper are below. When an abstract shows a paper is relevant, "
        "call `fetch_paper(paper_id=...)` to read its full text; the "
        "`paper_id` for each is given in parentheses.",
        "",
    ]
    for paper in papers:
        lines.append(f"- **{paper.title}** (paper_id: `{paper.paper_id}`)")
        lines.append(f"  {paper.abstract}")
    return "\n".join(lines)


def catalog_context(
    audience: str | None,
    *,
    enabled: bool = True,
    directory: Path | None = None,
) -> str:
    """Return the injected catalog block for a run, gated by audience+toggle.

    The audience gate dominates the toggle: only the corpus audience ever
    receives the catalog, so a forged ``enable_paper_corpus`` on a non-SBI run
    cannot pull another lab's library into context. Within that audience the
    toggle lets a run opt out.

    Args:
        audience: The run or question's self-declared audience.
        enabled: The run's corpus connector toggle. Ignored for non-corpus
            audiences, which never receive the catalog regardless.
        directory: Optional corpus directory override (tests).

    Returns:
        The formatted catalog block, or an empty string when the audience has
        no corpus, the toggle is off, or no catalog is installed.
    """
    if audience != CORPUS_AUDIENCE or not enabled:
        return ""
    return format_catalog(load_catalog(directory))


def disabled_tools_for(
    audience: str | None, *, enabled: bool = True
) -> list[str]:
    """Return the corpus tool ids to withhold from a run's tool registry.

    `fetch_paper` reaches the corpus on the agent's own initiative during
    drafting, validation, and reflection, so the audience gate has to be
    applied to it directly and not only to the injected catalog. As with the
    catalog, the audience gate dominates: a non-corpus audience always has the
    tool withheld; the corpus audience may additionally withhold it by turning
    the connector off.

    Args:
        audience: The run's self-declared audience.
        enabled: The run's corpus connector toggle. Only consulted for the
            corpus audience.

    Returns:
        An empty list when the corpus tool should stay available, the corpus
        tool ids otherwise, to be passed as the engine's `disable_tools`.
    """
    if audience == CORPUS_AUDIENCE and enabled:
        return []
    return list(CORPUS_TOOL_IDS)
