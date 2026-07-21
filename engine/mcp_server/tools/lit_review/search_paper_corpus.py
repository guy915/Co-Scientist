"""Fetch one of the research group's own papers in full from local disk.

Unlike the other tools here, this reads sanitized full text sitting on disk
rather than querying a remote API. The corpus is built offline by the viewer's
`app.corpus_ingest` and mounted into this service; when it is absent the tool
reports so rather than failing, and the agent falls back to PubMed.

The group's papers are not searched here: the whole catalog (title + abstract
of every paper) is injected into the run's context by the app, so the model
already knows what each paper is and picks which to read in full by
`paper_id`. This module is only the reader for that follow-up.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CORPUS_ENV_VAR = "SBI_CORPUS_DIR"

# The file types fetch_paper can serve. Anything counting or listing the
# corpus must use the same set, or its numbers drift from what the reader
# actually serves.
_CORPUS_SUFFIXES = (".md", ".txt")


def count_corpus_papers(root: Path) -> int:
    """Counts the papers ``fetch_paper`` could serve from ``root``.

    Args:
        root: The corpus directory.

    Returns:
        The number of corpus files with a servable suffix.
    """
    return sum(1 for path in root.iterdir() if path.suffix in _CORPUS_SUFFIXES)


def fetch_paper(paper_id: str) -> str:
    """Fetches one paper from the group's corpus in full.

    The follow-up to the injected paper catalog: the catalog gives the model
    every paper's title, abstract, and `paper_id`, and this reads the whole
    text of one when its abstract is not enough to settle the question.

    Args:
        paper_id: The `paper_id` from the injected catalog.

    Returns:
        A JSON object with the paper's title and complete sanitized text, or
        an empty object when the id is unknown or no corpus is installed.
    """
    root = Path(os.environ.get(CORPUS_ENV_VAR, ""))
    if not root.is_dir():
        return json.dumps({})
    # Resolve inside the corpus directory and confirm the result is still
    # within it, so a crafted id cannot walk out into the filesystem.
    for suffix in _CORPUS_SUFFIXES:
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
