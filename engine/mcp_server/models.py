"""Data models for literature review tools."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Article:
    """A literature article with extracted content and metadata."""

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    # Publication venue, e.g. journal or conference name.
    venue: str | None = None
    # Citation count, when available from the source; 0 if unknown.
    citations: int = 0
    abstract: str | None = None
    # Full extracted text, e.g. markdown from PMC fulltext (see
    # text_extraction.py); None if only metadata/abstract was retrieved.
    content: str | None = None
    # Source-specific identifier (e.g. PubMed ID), independent of url.
    source_id: str | None = None
    # Default reflects this dataclass's shared, multi-source origin; PubMed
    # tools in this server explicitly set "pubmed" via field_mapping.
    source: str = "google_scholar"
    # Direct links to downloadable PDF(s), if the source exposes any.
    pdf_links: list[str] = field(default_factory=list)
    # Set true once an agent has actually consulted this article's content,
    # as opposed to it merely appearing in search results.
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts the article to a dictionary for serialization.

        Returns:
            Dict with all article fields.
        """
        return asdict(self)
