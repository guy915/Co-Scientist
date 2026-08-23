"""Tests for the evidence every reflection prompt is shown.

Reflection shows retrieved evidence to a model on three paths: the
full/simulation review cascade, deep verification's opening context, and
the targeted probe evidence retrieved mid-verification. They are asserted
together here because they drifted apart while they were three separate
formatters -- only some of them excluded retracted papers, only some fell
back to an article's fulltext when its abstract was empty, and the
per-source truncation had grown three different values.
"""

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import deep_verification as dv
from tests._state import make_article, make_state


def test_verification_context_excludes_retracted_evidence() -> None:
    """A retracted paper never reaches the deep-verification gate.

    The review cascade already refuses retracted evidence, so a paper the
    reviews would not read must not be what the gate that exists to
    challenge a hypothesis's evidence weighs it against.
    """
    state = make_state(
        articles=[
            make_article(
                "Retracted paper",
                abstract="Withdrawn mechanistic claim.",
                used_in_analysis=True,
                is_retracted=True,
            ),
            make_article(
                "Standing paper",
                abstract="Replicated mechanistic finding.",
                used_in_analysis=True,
            ),
        ]
    )

    context = dv._verification_evidence_context(state)

    assert "Standing paper" in context
    assert "Retracted paper" not in context
    assert "Withdrawn mechanistic claim" not in context


def test_review_context_excludes_retracted_evidence() -> None:
    """The review cascade refuses retracted evidence too."""
    state = make_state(
        articles=[
            make_article(
                "Retracted paper",
                abstract="Withdrawn mechanistic claim.",
                used_in_analysis=True,
                is_retracted=True,
            )
        ]
    )

    assert cr._build_domain_context(state, None) == ""


def test_probe_context_excludes_retracted_evidence() -> None:
    """Targeted probe evidence is filtered by the formatter, not only above.

    Retrieval already drops retracted papers, but the rule belongs
    wherever evidence is handed to a model so a future caller cannot
    reintroduce one by formatting its own list.
    """
    retracted = make_article(
        "Retracted probe hit",
        abstract="Withdrawn mechanistic claim.",
        is_retracted=True,
    )

    assert dv._retrieved_evidence_context([retracted]) == ""


def test_verification_context_falls_back_to_article_fulltext() -> None:
    """An abstract-less source contributes its fulltext, not nothing.

    Retrieval marks an article analyzed on either field, so an abstract-less
    one with real fulltext used to be an empty section in the verification
    prompt while contributing its text to every other reflection prompt.
    """
    state = make_state(
        articles=[
            make_article(
                "Fulltext-only paper",
                abstract="",
                content="Measured a three-fold increase in flux.",
                used_in_analysis=True,
            )
        ]
    )

    context = dv._verification_evidence_context(state)

    assert "Measured a three-fold increase in flux." in context


def test_review_context_falls_back_to_article_fulltext() -> None:
    """The review cascade reads fulltext when the abstract is empty."""
    state = make_state(
        articles=[
            make_article(
                "Fulltext-only paper",
                abstract="",
                content="Measured a three-fold increase in flux.",
                used_in_analysis=True,
            )
        ]
    )

    context = cr._build_domain_context(state, None)

    assert "Measured a three-fold increase in flux." in context


def test_one_source_truncates_the_same_way_on_every_path() -> None:
    """A source's excerpt does not depend on which prompt is asking."""
    abstract = "mechanism " * 500
    state = make_state(
        articles=[
            make_article("Long paper", abstract=abstract, used_in_analysis=True)
        ]
    )

    review = cr._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    assert abstract[:2000] in review
    assert abstract[:2000] in verification


def test_private_sources_get_a_wider_slice_than_public_ones() -> None:
    """Private, scientist-supplied context is quoted at greater length."""
    display = "private finding " * 300
    state = make_state(context_enrichment_sources=[{"display": display}])

    review = cr._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    assert display[:2500] in review
    assert display[:2500] in verification


def test_public_article_citation_markers_are_stripped() -> None:
    """A source's own citations do not reach either reflection prompt.

    Left in, a review or verification model can copy one into its own
    prose -- a real-looking reference attached to a claim the cited
    source never made.
    """
    abstract = "This confirms prior work (Smith et al. 2019) [12]."
    state = make_state(
        articles=[
            make_article(
                "Cited paper", abstract=abstract, used_in_analysis=True
            )
        ]
    )

    review = cr._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    for context in (review, verification):
        assert "(Smith et al. 2019)" not in context
        assert "[12]" not in context


def test_private_source_citation_markers_are_kept() -> None:
    """A scientist-supplied source's own citations are not contamination.

    Unlike a retrieved paper's markers, these are the scientist's
    intentional content, not text a model could mistake for its own.
    """
    display = "See our finding (Doe et al. 2020) for the full protocol."
    state = make_state(context_enrichment_sources=[{"display": display}])

    verification = dv._verification_evidence_context(state)

    assert "(Doe et al. 2020)" in verification


def test_building_context_leaves_the_article_abstract_unchanged() -> None:
    """Stripping is for the prompt copy only, never for storage."""
    original = "This confirms prior work (Smith et al. 2019) [12]."
    article = make_article(
        "Cited paper", abstract=original, used_in_analysis=True
    )
    state = make_state(articles=[article])

    dv._verification_evidence_context(state)

    assert article.abstract == original
