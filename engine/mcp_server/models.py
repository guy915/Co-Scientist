"""Data models for literature review tools."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Article:
    """A literature article with extracted content and metadata."""

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int = 0
    abstract: str | None = None
    content: str | None = None
    source_id: str | None = None
    source: str = "google_scholar"
    pdf_links: list[str] = field(default_factory=list)
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts the article to a dictionary for serialization.

        Returns:
            Dict with all article fields.
        """
        return {
            "title": self.title,
            "url": self.url,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citations": self.citations,
            "abstract": self.abstract,
            "content": self.content,
            "source_id": self.source_id,
            "source": self.source,
            "pdf_links": self.pdf_links,
            "used_in_analysis": self.used_in_analysis,
        }
