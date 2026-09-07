"""Tests for what the research-overview evidence corpus is made of.

The corpus is the whole prompt of the deep knowledge-base call (F8) --
measured at ~400 tokens per source, ~52,000 tokens on a 132-source
production run -- so its per-source composition is a budget decision, not
a formatting one. These pin the two facts
``research_overview_evidence._EVIDENCE_ABSTRACT_CHARS`` records: the
per-source cap sits above the abstracts real runs retrieve, and the full
text sitting on the same record is deliberately not in the corpus.
"""

from co_scientist.agents.meta_review import research_overview_evidence as ev
from tests._state import make_article


def test_full_text_on_the_record_never_reaches_the_corpus() -> None:
    """A source contributes its abstract, never its downloaded full text.

    ``pubmed_search_with_fulltext`` attaches PMC full text to
    ``Article.content`` for the open-access share of a run's sources
    (157 of 239 analyzed articles, measured over six real runs, averaging
    ~14,000 characters). Sending that instead of the abstract is the
    obvious way to buy the knowledge base more detail and the wrong one:
    the corpus is already nearly the whole prompt of a call whose answer
    is budgeted at ``KNOWLEDGE_BASE_MAX_TOKENS``, so a full-text corpus
    is an order of magnitude past any context this chain offers.
    """
    articles = [
        make_article(
            title="P1",
            source="pubmed",
            abstract="The abstract as retrieved.",
            content="FULL TEXT BODY " * 2000,
            used_in_analysis=True,
        )
    ]

    corpus = ev._build_evidence_corpus(articles)
    formatted = ev._format_evidence_corpus(corpus)

    entry = next(iter(corpus.values()))
    assert entry["abstract"] == "The abstract as retrieved."
    assert "content" not in entry
    assert "FULL TEXT BODY" not in formatted


def test_the_cap_passes_a_real_abstract_through_whole() -> None:
    """The per-source cap trims a tail, and only a tail.

    Real retrieved abstracts average ~1,590 characters and only two of
    239 exceeded this cap, by 80 and 306 characters. An abstract at the
    long end of that distribution must therefore arrive intact -- if a
    later edit lowers the cap into the distribution, the corpus starts
    losing the end of ordinary abstracts silently.
    """
    long_real_abstract = "a" * 2596
    over_cap = "b" * (ev._EVIDENCE_ABSTRACT_CHARS + 306)
    articles = [
        make_article(
            title="P1", abstract=long_real_abstract, used_in_analysis=True
        ),
        make_article(title="P2", abstract=over_cap, used_in_analysis=True),
    ]

    entries = list(ev._build_evidence_corpus(articles).values())

    assert entries[0]["abstract"] == long_real_abstract
    assert len(entries[1]["abstract"]) == ev._EVIDENCE_ABSTRACT_CHARS
