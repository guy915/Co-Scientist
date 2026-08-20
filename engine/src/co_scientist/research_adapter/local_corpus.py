"""The group's own papers, searched from disk instead of over the network.

This exists because of a premise that turned out to be false. The plan for
degradation assumed the paper corpus could keep a run researching through a
search-server outage. It could not: ``fetch_paper`` is an MCP tool served by
the very server whose availability the gate checks, so when that server is
unreachable the corpus is unreachable with it. Worse, the corpus was never
searchable at all -- the whole catalog is injected into the run's context and
``fetch_paper`` reads one paper by id, which is a reader, not a source.

This module is the missing source: a :class:`RetrievalPort` over the same
directory, reading it directly, so a run whose network sources are all down
still has somewhere to look. It ranks with SQLite's FTS5 rather than a
hand-rolled scorer -- it ships with the standard library, its ``bm25()``
ranking is the one every other local search uses, and a second homegrown
lexical metric in this repo is how the Jaccard incident happened.

Two boundaries this deliberately does not cross:

* **It decides no permissions.** The corpus is one lab's library, and who
  may read it is already settled once, on the app side, by withholding the
  corpus tools from every other audience. :func:`corpus_search_permitted`
  reads that same decision off the registry rather than restating the rule,
  so the two cannot drift apart and a second gate cannot be forgotten.
* **It finds no directory of its own.** Where the corpus lives is the
  caller's fact (``SBI_CORPUS_DIR`` in a deployment, a repository path in a
  checkout), and a default invented here would be right in one of those and
  quietly wrong in the other.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from co_scientist.research import RetrievalError, SourceHit

logger = logging.getLogger(__name__)

# The source id this port answers to. It matches the `source` value the
# corpus tool already stamps on records in tools.yaml, so a finding read
# from disk and one fetched through MCP are attributed identically.
GROUP_CORPUS_SOURCE = "group_corpus"

# The corpus tool whose availability *is* the audience decision. The app
# withholds it from every audience but the corpus one; reading `enabled`
# here reuses that single decision instead of restating its rule.
CORPUS_GATE_TOOL_ID = "paper_corpus_fetch"

# The committed catalog: title, abstract and `paper_id` per paper. It is
# what gets searched. The paper bodies are read only once a hit is admitted.
CATALOG_FILENAME = "catalog.json"

# What `fetch_paper` will serve, kept identical so a hit is always readable.
_CORPUS_SUFFIXES = (".md", ".txt")

# Query terms: FTS5 has its own syntax, and a model-written question is not
# written in it. Words are extracted and OR-ed rather than passed through,
# so an apostrophe or a stray NEAR cannot become a syntax error.
_WORD = re.compile(r"[a-z0-9]+")

# Single characters and two-letter words carry no topic and match half the
# corpus; below this length a term costs more than it discriminates.
_MIN_TERM_LEN = 3

_catalogs: dict[tuple[str, float, int], tuple[dict[str, Any], ...]] = {}


def corpus_search_permitted(registry: Any) -> bool:
    """Whether this run's audience may read the group's papers at all.

    Args:
        registry: The run's ``ToolRegistry``.

    Returns:
        True only when the corpus tool survived the run's disabled-tool
        list, which is exactly the condition under which the app decided
        this audience may see the corpus.
    """
    tool = registry.get_tool(CORPUS_GATE_TOOL_ID) if registry else None
    return bool(tool is not None and tool.enabled)


def corpus_root(configured: str | None) -> Path | None:
    """Resolve a usable corpus directory, or None when there is not one.

    Args:
        configured: The directory the caller resolved, if any.

    Returns:
        The directory, when it exists and holds a catalog; None otherwise.
        A missing corpus is an ordinary state -- most deployments ship no
        corpus at all -- so it is answered, not raised.
    """
    if not configured:
        return None
    root = Path(configured)
    return root if (root / CATALOG_FILENAME).is_file() else None


def load_catalog(root: Path) -> tuple[dict[str, Any], ...]:
    """Read the catalog's papers, cached against the file's own identity.

    Cached on path, mtime and size rather than path alone: the catalog is
    a committed file that a rebuild replaces, and a cache keyed on the
    path would serve the previous build for the life of the process.

    Args:
        root: The corpus directory.

    Returns:
        One entry per paper, in catalog order.
    """
    path = root / CATALOG_FILENAME
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime, stat.st_size)
    if key not in _catalogs:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        papers = loaded.get("papers") if isinstance(loaded, dict) else None
        _catalogs[key] = tuple(papers or ())
    return _catalogs[key]


def local_corpus_for(state: Any) -> LocalCorpusRetrieval | None:
    """Build the corpus port for a run, or None when it has no corpus.

    The two questions this depends on -- may this run read the corpus,
    and is there one -- were both answered once at run setup and left on
    the state, so every caller here is a single field read. A node that
    re-derived either would be the second gate this module exists to
    avoid.

    Args:
        state: The workflow state.

    Returns:
        A port over the run's corpus, or None.
    """
    configured = state.get("local_corpus_dir")
    if not isinstance(configured, str) or not configured:
        return None
    return LocalCorpusRetrieval(Path(configured))


class LocalCorpusRetrieval:
    """Search and read the group's papers from disk, with no network.

    One instance serves one research request, holding its own FTS5 index
    in memory. The index is built on first search rather than at
    construction, so a run that is offered the corpus and never searches
    it pays nothing.

    Attributes:
        sources: Always the single local source, so a caller can extend a
            budget's source list with it the same way it does the MCP
            ones.
    """

    sources: tuple[str, ...] = (GROUP_CORPUS_SOURCE,)

    def __init__(self, root: Path) -> None:
        """Bind one corpus directory.

        Args:
            root: A directory holding ``catalog.json`` and the papers.
        """
        self._root = root
        self._index: sqlite3.Connection | None = None

    def catalog(self) -> tuple[dict[str, Any], ...]:
        """The catalog entries this port searches.

        Exposed because a caller turning a finding into a paper needs the
        title and abstract behind a locator, and the catalog is the only
        record of either -- a corpus hit has no source metadata of its
        own the way a network result does.

        Returns:
            One entry per paper, or empty when the catalog cannot be
            read at all.
        """
        try:
            return load_catalog(self._root)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read the corpus catalog: %s", exc)
            return ()

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Rank the catalog against one query.

        Args:
            query: The query to match, in ordinary words.
            source: Must be this port's source id.
            limit: Most results wanted.

        Returns:
            Hits in FTS5's ``bm25()`` order, best first.

        Raises:
            RetrievalError: This port was asked for another source, the
                terms were all too short to search on, or SQLite has no
                FTS5. The loop records any of them as a failed call.
        """
        if source != GROUP_CORPUS_SOURCE:
            raise RetrievalError(source, "not the local corpus")
        expression = _match_expression(query)
        if not expression:
            raise RetrievalError(source, "no searchable terms in the query")
        rows = self._matches(expression, limit)
        return [
            SourceHit(
                locator=str(row[0]),
                title=str(row[1]),
                snippet=str(row[2] or ""),
                rank=rank,
                # bm25() scores better matches more negative; negate so a
                # larger score means a better hit, as every other source
                # here reports it.
                score=-float(row[3]),
                metadata={"source": GROUP_CORPUS_SOURCE},
            )
            for rank, row in enumerate(rows)
        ]

    async def read(self, *, locator: str) -> str | None:
        """Read one paper in full from disk.

        Args:
            locator: A ``paper_id`` from a hit this port returned.

        Returns:
            The paper's sanitized text, or None when no readable file
            backs the id -- a quarter of the catalog is abstract-only, so
            this is an ordinary outcome and the loop keeps the snippet.
        """
        path = self._paper_path(locator)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read corpus paper %s: %s", locator, exc)
            return None

    def _paper_path(self, locator: str) -> Path | None:
        """Resolve a paper id to a file inside the corpus, or None.

        Every candidate is resolved and confirmed to still sit under the
        corpus directory, so a crafted id cannot walk out of it -- the
        same containment check the MCP reader applies.
        """
        root = self._root.resolve()
        for suffix in _CORPUS_SUFFIXES:
            path = (root / f"{locator}{suffix}").resolve()
            if path.is_file() and root in path.parents:
                return path
        return None

    def _matches(self, expression: str, limit: int) -> list[tuple[Any, ...]]:
        """Run one FTS5 query, returning id, title, abstract and score."""
        index = self._ensure_index()
        try:
            return list(
                index.execute(
                    "SELECT paper_id, title, abstract, bm25(papers) "
                    "FROM papers WHERE papers MATCH ? "
                    "ORDER BY bm25(papers) LIMIT ?",
                    (expression, max(int(limit), 0)),
                )
            )
        except sqlite3.OperationalError as exc:
            raise RetrievalError(GROUP_CORPUS_SOURCE, str(exc)) from exc

    def _ensure_index(self) -> sqlite3.Connection:
        """Build the in-memory index once, on first use.

        Raises:
            RetrievalError: This SQLite build has no FTS5. Reported as a
                failed call rather than crashing the run, since every
                other source is still available.
        """
        if self._index is not None:
            return self._index
        try:
            self._index = _build_index(load_catalog(self._root))
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise RetrievalError(GROUP_CORPUS_SOURCE, str(exc)) from exc
        return self._index


def _build_index(papers: Sequence[dict[str, Any]]) -> sqlite3.Connection:
    """Index a catalog's titles and abstracts for ranked matching.

    Args:
        papers: Catalog entries.

    Returns:
        An in-memory connection holding the populated FTS5 table.
    """
    index = sqlite3.connect(":memory:")
    index.execute(
        "CREATE VIRTUAL TABLE papers USING fts5("
        "paper_id UNINDEXED, title, abstract)"
    )
    index.executemany(
        "INSERT INTO papers (paper_id, title, abstract) VALUES (?, ?, ?)",
        [
            (
                str(paper.get("paper_id") or ""),
                str(paper.get("title") or ""),
                str(paper.get("abstract") or ""),
            )
            for paper in papers
            if paper.get("paper_id")
        ],
    )
    index.commit()
    return index


def _match_expression(query: str) -> str:
    """Turn a written question into an FTS5 expression it will accept.

    Every word is quoted and the set is OR-ed: a research question is a
    sentence, and requiring all of its words would match nothing while
    ranking already handles which matches are best.

    Args:
        query: The query as written.

    Returns:
        An FTS5 MATCH expression, or an empty string when nothing in the
        query was long enough to search on.
    """
    terms = {
        word
        for word in _WORD.findall(query.lower())
        if len(word) >= _MIN_TERM_LEN
    }
    return " OR ".join(f'"{term}"' for term in sorted(terms))
