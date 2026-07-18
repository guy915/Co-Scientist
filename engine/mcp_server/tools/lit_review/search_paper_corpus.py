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

# Also kept in step with app/app/paper_corpus.py's MIN_TOP_SCORE. Common
# words match weakly almost everywhere, so without a floor an agent asking
# "has this group studied X?" always gets passages back and may conclude they
# did. Measured on the real corpus: genuine questions top out at 0.28-0.36,
# a nonsense query at 0.035.
_MIN_TOP_SCORE = 0.05


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


def _split_oversized(paragraphs: list[str], budget: int) -> list[str]:
    """Break any paragraph larger than the budget on sentence boundaries.

    Kept in step with `app.paper_corpus`. Without it a passage is only as
    small as the largest paragraph, so a flattened table -- or any paper
    whose body arrives as one long line -- yields a single passage that is
    effectively the whole paper, defeating the point of searching passages.
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


def _chunk(title: str, text: str) -> list[tuple[str, str]]:
    """Split one paper into (title, passage) pairs."""
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    size = 0
    for paragraph in _split_oversized(_paragraphs(text), _TARGET_CHUNK_CHARS):
        if size and size + len(paragraph) > _TARGET_CHUNK_CHARS:
            chunks.append((title, " ".join(current)))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph)
    if current:
        chunks.append((title, " ".join(current)))
    return chunks


@lru_cache(maxsize=1)
def _index() -> tuple[list[tuple[str, str, str]], dict[str, float]]:
    """Load, chunk, and index the corpus once per process.

    Returns:
        The passages as (paper_id, title, text) triples, and the per-term idf
        weights. Both are empty when no corpus is installed. The paper_id is
        carried so a search hit can be followed by `fetch_paper`.
    """
    root = Path(os.environ.get(CORPUS_ENV_VAR, ""))
    if not root or not root.is_dir():
        logger.info("No paper corpus configured at %s", CORPUS_ENV_VAR)
        return [], {}

    passages: list[tuple[str, str, str]] = []
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
        passages.extend(
            (path.stem, chunk_title, body)
            for chunk_title, body in _chunk(title, text)
        )

    df: Counter[str] = Counter()
    for _, _, body in passages:
        df.update(set(_tokenize(body)))
    n = len(passages) or 1
    idf = {term: math.log(1 + n / (1 + c)) for term, c in df.items()}
    logger.info("Indexed %d passages from %s", len(passages), root)
    return passages, idf


def fetch_paper(paper_id: str) -> str:
    """Fetches one paper from the group's corpus in full.

    The natural follow-up to `search_paper_corpus`: search locates the paper
    and the relevant passage, this reads the whole thing when a passage is
    not enough to settle the question.

    Args:
        paper_id: The `paper_id` from a search result.

    Returns:
        A JSON object with the paper's title and complete sanitized text, or
        an empty object when the id is unknown or no corpus is installed.
    """
    root = Path(os.environ.get(CORPUS_ENV_VAR, ""))
    if not root or not root.is_dir():
        return json.dumps({})
    # Resolve inside the corpus directory and confirm the result is still
    # within it, so a crafted id cannot walk out into the filesystem.
    for suffix in (".md", ".txt"):
        path = (root / f"{paper_id}{suffix}").resolve()
        if not path.is_file() or root.resolve() not in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        first = text.lstrip().split("\n", 1)[0].strip()
        title = first[2:].strip() if first.startswith("# ") else path.stem
        return json.dumps(
            {paper_id: {"title": title, "content": text, "source_id": paper_id}}
        )
    logger.info("No paper in corpus with id %s", paper_id)
    return json.dumps({})


def search_paper_corpus(query: str, max_passages: int = 5) -> str:
    """Searches the research group's own published papers.

    Args:
        query: Free-text search terms. Technical vocabulary works best, since
            scoring rewards terms that are rare across the corpus.
        max_passages: Maximum number of passages to return.

    Returns:
        A JSON object keyed by passage id, each with the source paper's title,
        the matching text, and the `paper_id` to pass to `fetch_paper` for the
        full text. Empty when no corpus is installed or nothing matched.
    """
    passages, idf = _index()
    if not passages:
        return json.dumps({})

    terms = _tokenize(query)
    scored: list[tuple[float, int]] = []
    for position, (_, _, body) in enumerate(passages):
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

    # Judge the whole result by its best passage: a weak top score means the
    # query found nothing, not that it found many mediocre things.
    if not scored or scored[0][0] < _MIN_TOP_SCORE:
        return json.dumps({})

    results = {}
    for score, position in scored[: max(1, max_passages)]:
        paper_id, title, body = passages[position]
        results[f"corpus-{position:04d}"] = {
            "title": title,
            "abstract": body,
            "paper_id": paper_id,
            "score": round(score, 6),
        }
    return json.dumps(results)
