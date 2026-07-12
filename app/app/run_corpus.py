"""Private per-run document corpus and retrieval (Milestone 7).

Scientists can attach documents / a private publication repository that the
system indexes and searches (SSR §3, §6). This module is the retrieval layer
behind a provider interface: a run-scoped corpus of documents with keyword
retrieval, so an accepted attachment feeds run-scoped retrieval rather than
being a dead connector.

The interface (``CorpusRetriever``) is deliberately small so a vector/hybrid
backend can be dropped in later without changing callers; the default
``KeywordCorpusRetriever`` is deterministic and offline (BM25-style token
scoring) so it runs in CI with no embedding service.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections import Counter
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")

# Evidence `source` value marking a row as a scientist-provided attachment
# (versus retrieved literature), so a run's private corpus is separable.
ATTACHMENT_SOURCE = "attachment"


def _tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens (length > 2) for retrieval scoring."""
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 2]


@dataclasses.dataclass(frozen=True)
class CorpusDocument:
    """One document in a run's private corpus."""

    doc_id: str
    title: str
    text: str
    source: str = "attachment"


@dataclasses.dataclass(frozen=True)
class RetrievedDocument:
    """A retrieval hit with its relevance score."""

    document: CorpusDocument
    score: float


class CorpusRetriever(Protocol):
    """Provider interface for run-scoped document retrieval.

    A keyword implementation ships by default; a vector/hybrid retriever can
    implement the same interface without changing callers.
    """

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        """Return the top-k documents most relevant to the query."""
        ...


class KeywordCorpusRetriever:
    """Deterministic offline keyword (BM25-style) retriever over a corpus.

    Scores documents by summed query-term weights using term frequency and an
    inverse-document-frequency factor, so a term that appears in every document
    contributes little and a distinctive term dominates. No embeddings or
    network — reproducible in CI.
    """

    def __init__(self, documents: list[CorpusDocument]) -> None:
        """Index the corpus documents for keyword retrieval."""
        self._documents = documents
        self._doc_tokens = {d.doc_id: _tokenize(d.text) for d in documents}
        self._tf = {
            doc_id: Counter(tokens)
            for doc_id, tokens in self._doc_tokens.items()
        }
        n = len(documents) or 1
        # Document frequency per term, for the idf weight.
        df: Counter[str] = Counter()
        for tokens in self._doc_tokens.values():
            df.update(set(tokens))
        self._idf = {
            term: math.log(1 + n / (1 + count)) for term, count in df.items()
        }

    def _score(self, query_terms: list[str], doc_id: str) -> float:
        tf = self._tf[doc_id]
        length = len(self._doc_tokens[doc_id]) or 1
        score = 0.0
        for term in query_terms:
            if term in tf:
                score += (tf[term] / length) * self._idf.get(term, 0.0)
        return score

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        """Return the top-k documents most relevant to the query."""
        query_terms = _tokenize(query)
        scored = [
            RetrievedDocument(doc, self._score(query_terms, doc.doc_id))
            for doc in self._documents
        ]
        hits = [r for r in scored if r.score > 0.0]
        # Sort by score desc, then doc_id for a deterministic tie-break.
        hits.sort(key=lambda r: (-r.score, r.document.doc_id))
        return hits[:k]


def corpus_from_evidence(
    evidence_rows: list[dict[str, Any]],
) -> list[CorpusDocument]:
    """Build corpus documents from a run's attachment evidence rows.

    Only rows whose source is an attachment are included, so retrieved
    literature is not mixed into the scientist's private corpus.
    """
    return [
        CorpusDocument(
            doc_id=str(row.get("id")),
            title=str(row.get("title") or ""),
            text=str(row.get("abstract") or ""),
            source=ATTACHMENT_SOURCE,
        )
        for row in evidence_rows
        if row.get("source") == ATTACHMENT_SOURCE
    ]


def engine_context_sources(
    evidence_rows: list[dict[str, Any]],
    research_goal: str,
    *,
    max_documents: int = 20,
    excerpt_chars: int = 6000,
) -> list[dict[str, Any]]:
    """Retrieve private documents and format bounded engine evidence sources."""
    documents = corpus_from_evidence(evidence_rows)
    hits = KeywordCorpusRetriever(documents).retrieve(
        research_goal, k=max_documents
    )
    # If goal vocabulary does not overlap a small scientist corpus, preserve
    # the documents in deterministic order rather than silently discarding
    # explicitly supplied context.
    selected = [hit.document for hit in hits]
    if not selected:
        selected = sorted(documents, key=lambda item: item.doc_id)[
            :max_documents
        ]
    return [
        {
            "display": (
                f"Private scientist source '{document.title}': "
                f"{document.text[:excerpt_chars]}"
            ),
            "tool_id": "private_corpus",
            "source_type": "private_document",
            "data": {
                "document_id": document.doc_id,
                "title": document.title,
                "excerpt": document.text[:excerpt_chars],
                "private": True,
            },
        }
        for document in selected
    ]
