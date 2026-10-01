"""The literature-article record.

Split out of :mod:`co_scientist.models`, which had grown past the
module-size budget. ``Article`` is the one model in that file with no tie
to the hypothesis lifecycle -- it is what a search source returns, not
something the workflow scores or evolves -- so it separates cleanly.

:mod:`co_scientist.models` re-exports ``Article``, so every existing
import site is unaffected.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from co_scientist.models_metrics import _known_field_kwargs


@dataclass
class Article:
    """A literature article with extracted content and metadata.

    Note: In PubMed-only mode, `content` and `pdf_links` are unused.
    Fulltext content is accessed directly by PaperQA from HTML files.
    """

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int = 0
    abstract: str | None = None
    # Unused in PubMed-only mode (PaperQA reads HTML files directly)
    content: str | None = None
    source_id: str | None = None
    source: str = "pubmed"  # default changed to "pubmed" (was "google_scholar")
    doi: str | None = None
    is_retracted: bool = False
    correction_status: str = "current"
    publication_type: str | None = None
    pdf_links: list[str] = field(
        default_factory=list
    )  # unused in PubMed-only mode (HTML-only)
    # Flag indicating if this article was analyzed by the agent
    used_in_analysis: bool = False
    # When the engine retrieved this article (search-phase collection time),
    # distinct from any downstream persistence timestamp a caller stamps on
    # its own copy of the record.
    retrieved_at: float | None = None
    # Hybrid retrieval score (lexical heuristic + model-judged relevance,
    # see search_support.py) and the provenance of how it was produced.
    # None for an article that predates hybrid scoring or was never ranked
    # this way (e.g. a directly fetched corpus paper).
    retrieval_score: float | None = None
    retrieval_rationale: str | None = None
    retriever_version: str | None = None
    # Id of the search call that surfaced this article, when it came from
    # the deep-research phase, so a caller persisting it can say which
    # query found it and which question that query was serving. None for
    # an article the ordinary literature search collected, whose query is
    # not carried on the record.
    retrieval_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        """Rebuild from a ``to_dict`` payload, ignoring unknown keys."""
        return cls(**_known_field_kwargs(cls, data))
