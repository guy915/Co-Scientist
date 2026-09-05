"""Chunk long evidence into passage-sized units for entailment.

Closes a production finding (run 44e848fb): the pre-ranking claim gate
built one :class:`~app.claims_assessor.EvidencePassage` per article --
title + abstract + full text, up to ``PROMPT_PAPER_MAX_CHARS`` (200,000
chars) -- and called that a "passage". Retrieving the top 5 of those per
claim (``app.claims_assessor.retrieve_passages``) meant every entailment
call carried up to five whole papers: ~600 gate calls averaged 34-46k
prompt tokens each for ~250 tokens of answer, 28M of the run's 29M total
tokens. Worse, because the claim (which changes every call) was rendered
before the evidence (which recurs across calls, see
``app.claim_verifier``), the recurring papers never formed a stable
prompt prefix for provider-side prompt caching -- a 6.9% cache hit rate
on text that should have been near-static across a run (the engine's own
response cache is unaffected by ordering; it keys on the full prompt).
Chunking the evidence side to passage size (so a call carries ~5 passages
of ~1-1.5k chars, not 5 whole papers) and rendering evidence before the
claim fixes both the prompt size and the prefix instability.

The title + abstract stays one whole chunk regardless of length -- it is
already passage-sized and splitting it would only fragment the part of
the record retrieval most reliably matches on. Only a fetched full text
(``article.content``) is chunked, by paragraph, falling back to a
sentence window for a paragraph that alone exceeds the chunk size. A
small character overlap is carried across adjacent chunks so a sentence
split near a boundary is not stranded without its lead-in in every chunk.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence

from app.claims_assessor import _SENTENCE_SPLIT as _SENTENCE_SPLIT
from app.claims_assessor import EvidencePassage

# Passage-sized chunk target (paragraph/sentence-window units are packed up
# to this many characters). Chosen so five retrieved chunks -- the retrieval
# budget below -- read as a handful of dense paragraphs, not five papers.
CHUNK_MAX_CHARS = 1200

# Small overlap carried across adjacent chunks, so a supporting sentence
# split right at a chunk boundary still appears whole in at least one chunk.
# A chunk's true ceiling is therefore CHUNK_MAX_CHARS + CHUNK_OVERLAP_CHARS
# (the overlap prefix plus the joining space), not CHUNK_MAX_CHARS alone.
CHUNK_OVERLAP_CHARS = 150

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

# A chunked passage's id is "<article id>#<chunk index>" (an all-digit
# suffix); an id with no such suffix -- including one that legitimately
# contains "#", e.g. a private document id -- is already article-level.
_CHUNK_SUFFIX = re.compile(r"#(\d+)$")


def parent_evidence_id(evidence_id: str) -> str:
    """Recover an article's own id from a possibly chunk-qualified one.

    Every consumer that joins a claim-evidence span's ``evidence_id`` back
    to its source evidence row (report rendering, public shares) must
    resolve through this first, since a span located inside a chunked
    passage carries the chunk's id, not the article's.
    """
    match = _CHUNK_SUFFIX.search(evidence_id)
    return evidence_id[: match.start()] if match else evidence_id


def _split_long_unit(unit: str, max_chars: int) -> list[str]:
    """Split one paragraph too long for one chunk into sentence windows."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(unit) if s.strip()]
    windows: list[str] = []
    for sentence in sentences or [unit]:
        if len(sentence) <= max_chars:
            windows.append(sentence)
        else:
            # A single sentence still over the limit (dense, unpunctuated
            # text) is hard-sliced -- the last resort, not the common case.
            windows.extend(
                sentence[i : i + max_chars]
                for i in range(0, len(sentence), max_chars)
            )
    return windows


def _pack_units(units: Sequence[str], max_chars: int) -> list[str]:
    """Greedily pack ordered text units into chunks no larger than max_chars."""
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = unit
    if current:
        chunks.append(current)
    return chunks


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Prefix each chunk but the first with a tail of the previous one."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    overlapped = [chunks[0]]
    for previous, current in itertools.pairwise(chunks):
        overlapped.append(f"{previous[-overlap:]} {current}".strip())
    return overlapped


def chunk_text(
    text: str,
    *,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Split ``text`` into paragraph/sentence-window chunks of ~max_chars.

    Paragraphs (blank-line separated) are packed greedily up to
    ``max_chars``; a paragraph longer than that on its own is split by
    sentence, and a single sentence still too long is hard-sliced.
    """
    stripped = text.strip()
    if not stripped:
        return []
    paragraphs = [
        p.strip() for p in _PARAGRAPH_SPLIT.split(stripped) if p.strip()
    ] or [stripped]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(_split_long_unit(paragraph, max_chars))
    return _add_overlap(_pack_units(units, max_chars), overlap)


def chunk_evidence_passage(
    article_id: str,
    *,
    head_text: str,
    body_text: str,
    source: str,
    url: str,
) -> list[EvidencePassage]:
    """Build one article's evidence passages, chunked to passage size.

    ``head_text`` (title + abstract) is always kept whole as its own
    chunk -- see the module docstring. Only a non-empty ``body_text``
    (fetched full text) is chunked; when there is none, this returns
    exactly the one passage the caller had before chunking existed, under
    the article's own id (never a ``#0``-suffixed one), so an
    abstract-only article is unchanged.

    Args:
        article_id: The parent article/evidence row's own id.
        head_text: Title + abstract, already joined by the caller.
        body_text: Fetched full text, or empty when none was fetched.
        source: Provenance source name, carried onto every chunk.
        url: Provenance URL, carried onto every chunk.

    Returns:
        One or more :class:`EvidencePassage` objects, each carrying
        ``article_id`` as either its bare ``evidence_id`` (single chunk)
        or the parent of a ``#<index>``-suffixed one (multiple chunks).
    """
    head = head_text.strip()
    all_chunks = ([head] if head else []) + chunk_text(body_text)
    if len(all_chunks) <= 1:
        return [
            EvidencePassage(
                evidence_id=article_id,
                text=all_chunks[0] if all_chunks else "",
                source=source,
                url=url,
            )
        ]
    return [
        EvidencePassage(
            evidence_id=f"{article_id}#{i}", text=chunk, source=source, url=url
        )
        for i, chunk in enumerate(all_chunks)
    ]
