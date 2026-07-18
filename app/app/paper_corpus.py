"""The SBI/UCD paper corpus: sanitation, chunking, and retrieval.

The lab's papers extract to roughly 330k tokens of raw `pdftotext` output,
about 30% of which is references, page furniture, and figure/equation glyphs
fragmented into single letters. Even sanitized the corpus is far too large to
inject anywhere, so it is reached by retrieval rather than by injection.

Two design choices are worth stating, because both look like shortcuts and
neither is:

Chunks are documents. A whole paper is ~22k tokens, so retrieving one is no
better than injecting it. Splitting each paper into passage-sized
`CorpusDocument`s means the existing `KeywordCorpusRetriever` -- already
BM25-style, deterministic, and offline -- retrieves passages with no new
retrieval code and no new dependency.

Keyword scoring, not embeddings. This corpus is jargon-dense (STV, DPD,
BMRA, trametinib, SH-SY5Y, PLX8394) and queries share that vocabulary, which
is the regime where term-frequency scoring is strongest and where the
vocabulary mismatch embeddings solve is mildest. `CorpusRetriever` remains
the seam: a vector backend can replace this without touching callers.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from collections import Counter
from pathlib import Path

from app.run_corpus import (
    CorpusDocument,
    KeywordCorpusRetriever,
    RetrievedDocument,
)

logger = logging.getLogger(__name__)

# Where sanitized papers live. Kept outside the package (and out of git) by
# default: the corpus is publisher-copyrighted full text and this repository
# is public. Override to point at a mounted volume in a deployment.
CORPUS_ENV_VAR = "SBI_CORPUS_DIR"
_DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "corpus" / "sbi_ucd"

# A passage large enough to carry an argument, small enough that several fit
# in a prompt beside everything else a call already carries.
TARGET_CHUNK_TOKENS = 450
_CHARS_PER_TOKEN = 4

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


def _paragraphs(text: str) -> list[str]:
    """Group sanitized lines into paragraphs.

    Sanitation drops blank lines, so paragraphs are re-derived: a line that
    does not end mid-sentence closes the one being built.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        current.append(line)
        if line.endswith((".", "?", "!")):
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _split_oversized(paragraphs: list[str], budget: int) -> list[str]:
    """Break any paragraph larger than the budget into sentence-sized parts.

    Without this a passage is only as small as the largest paragraph, and a
    table flattened onto one line would produce a single enormous passage
    that crowds out everything else in the prompt it lands in.
    """
    out: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= budget:
            out.append(paragraph)
            continue
        part: list[str] = []
        size = 0
        for sentence in re.split(r"(?<=[.?!])\s+", paragraph):
            if size and size + len(sentence) > budget:
                out.append(" ".join(part))
                part, size = [], 0
            part.append(sentence)
            size += len(sentence) + 1
        if part:
            out.append(" ".join(part))
    return out


def chunk_paper(
    paper_id: str,
    title: str,
    text: str,
    target_tokens: int = TARGET_CHUNK_TOKENS,
) -> list[CorpusDocument]:
    """Split one sanitized paper into passage-sized corpus documents.

    Splits on paragraph boundaries rather than a fixed character count, so a
    retrieved passage is a complete argument rather than a window that starts
    and stops mid-sentence.

    Args:
        paper_id: Stable identifier for the paper, used to build chunk ids.
        title: The paper's title, carried on every chunk so a hit is
            attributable without a second lookup.
        text: The paper's sanitized text.
        target_tokens: Approximate size to grow each chunk toward.

    Returns:
        One `CorpusDocument` per passage, in document order.
    """
    budget = target_tokens * _CHARS_PER_TOKEN
    chunks: list[CorpusDocument] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        if not current:
            return
        index = len(chunks)
        chunks.append(
            CorpusDocument(
                doc_id=f"{paper_id}#{index:03d}",
                title=title,
                text=" ".join(current),
                source="sbi_corpus",
            )
        )

    for paragraph in _split_oversized(_paragraphs(text), budget):
        if size and size + len(paragraph) > budget:
            flush()
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph)
    flush()
    return chunks


def corpus_dir() -> Path:
    """Return the configured corpus directory."""
    override = os.environ.get(CORPUS_ENV_VAR)
    return Path(override) if override else _DEFAULT_CORPUS_DIR


def _title_from(path: Path, text: str) -> str:
    """Take the title from a leading markdown heading, else the filename."""
    first = text.lstrip().split("\n", 1)[0].strip()
    if first.startswith("# "):
        return first[2:].strip()
    return path.stem


def load_corpus(directory: Path | None = None) -> list[CorpusDocument]:
    """Load and chunk every sanitized paper in the corpus directory.

    Args:
        directory: Where sanitized `.md`/`.txt` papers live. Defaults to the
            configured corpus directory.

    Returns:
        Every paper's chunks, or an empty list when the corpus is absent --
        which is the normal state of a fresh checkout, not an error.
    """
    root = directory or corpus_dir()
    if not root.is_dir():
        logger.debug("no paper corpus at %s", root)
        return []

    documents: list[CorpusDocument] = []
    for path in sorted(root.iterdir()):
        if path.suffix not in (".md", ".txt"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read corpus paper %s: %s", path, exc)
            continue
        title = _title_from(path, text)
        documents.extend(chunk_paper(path.stem, title, text))
    papers = {d.doc_id.split("#")[0] for d in documents}
    logger.debug(
        "loaded %d passages from %d papers", len(documents), len(papers)
    )
    return documents


def build_retriever(
    directory: Path | None = None,
) -> KeywordCorpusRetriever | None:
    """Build a retriever over the paper corpus, or None when it is absent.

    Args:
        directory: Optional corpus directory override.

    Returns:
        A retriever, or None when no papers are installed so callers can skip
        retrieval entirely rather than querying an empty index.
    """
    documents = load_corpus(directory)
    return KeywordCorpusRetriever(documents) if documents else None


# The corpus is one lab's library, so it is offered to that lab only. Other
# audiences retrieve nothing rather than seeing another group's unpublished
# reading of the field.
CORPUS_AUDIENCE = "sbi_ucd"

# How many passages each surface takes. Chat can afford more because it makes
# one call; the run path's passages ride the literature channel into planning
# and query generation, where they compete with the goal itself.
CHAT_PASSAGES = 6
RUN_PASSAGES = 4

_cached_retriever: KeywordCorpusRetriever | None = None
_cache_loaded = False


def _retriever() -> KeywordCorpusRetriever | None:
    """Return the process-wide retriever, indexing the corpus on first use.

    The corpus is static, so it is indexed once. `_cache_loaded` distinguishes
    "not yet built" from "built and there is no corpus", so an absent corpus
    is not re-scanned on every request.
    """
    global _cached_retriever, _cache_loaded
    if not _cache_loaded:
        _cached_retriever = build_retriever()
        _cache_loaded = True
    return _cached_retriever


def reset_cache() -> None:
    """Drop the cached index. For tests that install a different corpus."""
    global _cached_retriever, _cache_loaded
    _cached_retriever, _cache_loaded = None, False


def retrieve_for(
    audience: str | None, query: str, k: int
) -> list[RetrievedDocument]:
    """Retrieve corpus passages for an audience, if it has a corpus.

    Args:
        audience: The run or question's self-declared audience.
        query: Free text to search with -- a user's question or a run's goal.
        k: Maximum passages to return.

    Returns:
        The best passages, or an empty list when the audience has no corpus,
        the corpus is not installed, or nothing matched.
    """
    if audience != CORPUS_AUDIENCE or not query.strip():
        return []
    retriever = _retriever()
    if retriever is None:
        return []
    return retriever.retrieve(query, k=k)


def format_passages(hits: list[RetrievedDocument]) -> str:
    """Render retrieved passages for a prompt, grouped under their paper.

    Args:
        hits: Retrieval results, already ordered by relevance.

    Returns:
        A block of text naming each source paper above its passage, or an
        empty string when there were no hits.
    """
    if not hits:
        return ""
    lines: list[str] = []
    for hit in hits:
        lines.append(f'From "{hit.document.title}":\n{hit.document.text}')
    return "\n\n".join(lines)
