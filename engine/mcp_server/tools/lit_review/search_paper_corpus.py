"""Search a local corpus of the research group's own papers.

Unlike the other tools here, this one queries sanitized full text sitting on
disk rather than a remote API. The corpus is built offline by the viewer's
`app.corpus_ingest` and mounted into this service; when it is absent the tool
reports so rather than failing, and the agent falls back to PubMed.

The retrieval is a self-contained BM25-style scorer. That duplicates a little
arithmetic from the viewer's `app.paper_corpus`, which is deliberate: this is
a separately installable service that must not take a dependency on the web
application, and the alternative -- a network hop back into the app -- would
make literature search depend on the caller that invoked it.
"""

import json
import logging
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CORPUS_ENV_VAR = "SBI_CORPUS_DIR"

_TOKEN = re.compile(r"[a-z0-9]+")

# Kept in step with app/app/paper_corpus.py: passages must be big enough to
# carry an argument and small enough that several fit in one prompt.
_TARGET_CHUNK_CHARS = 450 * 4


def _tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens (length > 2) for retrieval scoring."""
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 2]


def _paragraphs(text: str) -> list[str]:
    """Group sanitized lines into paragraphs on sentence boundaries."""
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


def _chunk(title: str, text: str) -> list[tuple[str, str]]:
    """Split one paper into (title, passage) pairs."""
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    size = 0
    for paragraph in _paragraphs(text):
        if size and size + len(paragraph) > _TARGET_CHUNK_CHARS:
            chunks.append((title, " ".join(current)))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph)
    if current:
        chunks.append((title, " ".join(current)))
    return chunks


@lru_cache(maxsize=1)
def _index() -> tuple[list[tuple[str, str]], dict[str, float]]:
    """Load, chunk, and index the corpus once per process.

    Returns:
        The passages as (title, text) pairs, and the per-term idf weights.
        Both are empty when no corpus is installed.
    """
    root = Path(os.environ.get(CORPUS_ENV_VAR, ""))
    if not root or not root.is_dir():
        logger.info("No paper corpus configured at %s", CORPUS_ENV_VAR)
        return [], {}

    passages: list[tuple[str, str]] = []
    for path in sorted(root.iterdir()):
        if path.suffix not in (".md", ".txt"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            continue
        first = text.lstrip().split("\n", 1)[0].strip()
        title = first[2:].strip() if first.startswith("# ") else path.stem
        passages.extend(_chunk(title, text))

    df: Counter[str] = Counter()
    for _, body in passages:
        df.update(set(_tokenize(body)))
    n = len(passages) or 1
    idf = {term: math.log(1 + n / (1 + c)) for term, c in df.items()}
    logger.info("Indexed %d passages from %s", len(passages), root)
    return passages, idf


def search_paper_corpus(query: str, max_passages: int = 5) -> str:
    """Searches the research group's own published papers.

    Args:
        query: Free-text search terms. Technical vocabulary works best, since
            scoring rewards terms that are rare across the corpus.
        max_passages: Maximum number of passages to return.

    Returns:
        A JSON object keyed by passage id, each with the source paper's title
        and the matching text. Empty when no corpus is installed or nothing
        matched.
    """
    passages, idf = _index()
    if not passages:
        return json.dumps({})

    terms = _tokenize(query)
    scored: list[tuple[float, int]] = []
    for position, (_, body) in enumerate(passages):
        tokens = _tokenize(body)
        counts = Counter(tokens)
        length = len(tokens) or 1
        score = sum(
            (counts[t] / length) * idf.get(t, 0.0) for t in terms if t in counts
        )
        if score > 0.0:
            scored.append((score, position))

    # Highest score first, then position for a deterministic tie-break.
    scored.sort(key=lambda pair: (-pair[0], pair[1]))

    results = {}
    for score, position in scored[: max(1, max_passages)]:
        title, body = passages[position]
        results[f"corpus-{position:04d}"] = {
            "title": title,
            "abstract": body,
            "score": round(score, 6),
        }
    return json.dumps(results)
