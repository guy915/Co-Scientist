"""Tests for what the research-overview evidence corpus is made of.

The corpus is the whole prompt of the deep knowledge-base call (F8) --
measured at ~400 tokens per source, ~52,000 tokens on a 132-source
production run -- so both its size and its per-source composition are
budget decisions, not formatting ones. These pin the two orthogonal caps
``research_overview_evidence`` records. ``_EVIDENCE_ABSTRACT_CHARS``
bounds how much of each source is sent: it sits above the abstracts real
runs retrieve, and the full text on the same record is deliberately not in
the corpus. ``RESEARCH_OVERVIEW_MAX_SOURCES`` bounds how many sources are
sent at all, since the analyzed set grows every cycle -- and the selection
that applies it must stay round-robin, or the web sources go first.
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
    the corpus is already nearly the whole prompt of the knowledge base's
    own calls, which resend it once per theme, so a full-text corpus
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


def test_the_corpus_is_capped_at_the_measured_source_count() -> None:
    """One source past the cap is dropped, not sent.

    The corpus grows across cycles -- every parsed search result is marked
    ``used_in_analysis`` and deep-verification probes append more articles
    every cycle -- so without a cap the interim overview's prompt grows
    without bound. Production extended run ``bc77950f`` reached 126,975
    prompt tokens and could not be answered.
    """
    articles = [
        make_article(
            title=f"P{index}",
            abstract="An abstract.",
            used_in_analysis=True,
        )
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 1)
    ]

    corpus = ev._build_evidence_corpus(articles)

    assert len(corpus) == ev.RESEARCH_OVERVIEW_MAX_SOURCES


def test_the_capped_corpus_keeps_contiguous_evidence_ids() -> None:
    """Ids stay ``evidence-1..N`` after the cap drops the tail.

    ``_validate_knowledge_base`` resolves the topics the model cited back
    to their source metadata by evidence id, so a gap in the numbering
    silently drops a cited topic's provenance from the report.
    """
    articles = [
        make_article(title=f"P{index}", used_in_analysis=True)
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 25)
    ]

    corpus = ev._build_evidence_corpus(articles)

    expected = [
        f"evidence-{i + 1}" for i in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES)
    ]
    assert list(corpus) == expected
    assert [entry["evidence_id"] for entry in corpus.values()] == expected


def test_every_source_survives_a_corpus_far_over_the_cap() -> None:
    """The cap is applied round-robin, so no source type is dropped whole.

    Selecting the cap's worth of sources by a global ``retrieval_score``
    sort would drop every web result: ``_retrieval_score`` floors web
    articles at a normalized 0.0, so they sort below every indexed paper
    however well they match. Round-robin is what keeps the breadth.
    """
    sources = ("pubmed", "openalex", "web")
    articles = [
        make_article(title=f"{source}-{index}", source=source)
        for index in range(100)
        for source in sources
    ]
    for article in articles:
        article.used_in_analysis = True

    corpus = ev._build_evidence_corpus(articles)

    assert len(corpus) == ev.RESEARCH_OVERVIEW_MAX_SOURCES
    assert {entry["source"] for entry in corpus.values()} == set(sources)


def test_the_capped_selection_is_deterministic() -> None:
    """The same articles select the same corpus every time.

    The selection is positional (round-robin over first-appearance source
    order), never randomized or score-sorted, so a resumed run and its
    checkpoint predecessor build the identical corpus.
    """
    articles = [
        make_article(
            title=f"P{index}",
            source=("pubmed", "openalex", "web")[index % 3],
            used_in_analysis=True,
        )
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 40)
    ]

    first = ev._build_evidence_corpus(articles)
    second = ev._build_evidence_corpus(articles)

    assert first == second
    assert [entry["title"] for entry in first.values()] == [
        entry["title"] for entry in second.values()
    ]
