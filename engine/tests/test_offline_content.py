"""Tests for the offline backend's leaf-text generation.

The content is cosmetic -- offline runs exercise the pipeline, they do not
produce findings -- but a demo or e2e run is what a reader judges the
product's output by, so these pin the properties that make it readable:
it is about the run's subject, it varies by field, and it never mines its
own output as if it were subject matter.
"""

import random

import pytest

from co_scientist.offline.content import (
    _CRITIQUE_TEMPLATES,
    _EXPERIMENT_TEMPLATES,
    _GENERATED_VOCABULARY,
    _GO_NO_GO_TEMPLATES,
    _PHASE_LABEL_TEMPLATES,
    _RECOMMENDED_IDEA_TEMPLATES,
    _SCOPE_CLAUSES,
    _TIME_ESTIMATE_TEMPLATES,
    _goal_text,
    leaf_text,
    subject_terms,
)

_GOAL_PROMPT = """# Generation Agent

The overarching objective is to develop a novel hypothesis.

Research Goal: What mechanisms drive antibiotic resistance in
Staphylococcus aureus biofilms?

Criteria for a high-quality hypothesis:
Run setup:
- Focus: Balance -- weigh evidence, novelty and feasibility evenly.
- Requirements: cite sources in author-year form.
"""


def test_the_goal_span_stops_before_the_surrounding_boilerplate() -> None:
    """Only the goal is scanned, not the template it is embedded in.

    A goal is one or two sentences inside a prompt that is mostly
    scaffolding, so an unbounded scan is dominated by the scaffolding:
    offline runs came out talking about "author-year" and "requirements"
    whatever they were actually about.
    """
    span = _goal_text(_GOAL_PROMPT)

    assert "antibiotic resistance" in span
    assert "author-year" not in span
    assert "Requirements" not in span


def test_terms_come_from_the_goal() -> None:
    """The run's own subject drives the vocabulary."""
    terms = subject_terms(_GOAL_PROMPT)

    assert "antibiotic" in terms
    assert "biofilms" in terms
    assert "requirements" not in terms


def test_a_prompt_with_no_goal_falls_back_rather_than_inventing() -> None:
    """With nothing to ground on, generic terms beat prompt scaffolding."""
    terms = subject_terms("Some text with no labelled goal at all here.")

    assert "pathway flux" in terms


def test_generated_text_is_never_mined_as_subject_matter() -> None:
    """This module must not feed on its own output.

    The evolution prompt hands back a parent hypothesis this module wrote,
    so without the exclusion the vocabulary compounds on itself and
    produces "Sustained modulation of modulation suppresses conditions".
    """
    rng = random.Random(0)
    generated = leaf_text(rng, 1, "statement", ("resistance", "biofilms"))

    terms = subject_terms(f"Original Hypothesis: {generated}")

    assert not set(terms) & _GENERATED_VOCABULARY


def _openings(templates: tuple[str, ...]) -> set[str]:
    """Every way a family can begin, for the fixed terms below."""
    return {
        f"{filled[:1].upper()}{filled[1:]}"
        for template in templates
        for a, b in (("resistance", "biofilms"), ("biofilms", "resistance"))
        for filled in (template.format(term_a=a, term_b=b),)
    }


@pytest.mark.parametrize(
    ("field", "family", "foreign"),
    [
        ("experimental_context", _EXPERIMENT_TEMPLATES, _CRITIQUE_TEMPLATES),
        ("constructive_feedback", _CRITIQUE_TEMPLATES, _EXPERIMENT_TEMPLATES),
    ],
    ids=["experiment_reads_as_a_protocol", "feedback_reads_as_a_critique"],
)
def test_leaves_vary_by_the_field_they_land_in(
    field: str, family: tuple[str, ...], foreign: tuple[str, ...]
) -> None:
    """One sentence shape across every field renders a run as filler.

    ``_fill_schema`` reaches a title, a mechanism and a reviewer's critique
    through the same code path, so the property name is what distinguishes
    them.

    Asserted as family membership over many draws rather than one phrase at
    one seed. The single-phrase form passed only while that phrase's
    template happened to be the one that seed selected, so widening a family
    broke it without anything being wrong.
    """
    mine, theirs = _openings(family), _openings(foreign)

    for seed in range(200):
        text = leaf_text(
            random.Random(seed), 1, field, ("resistance", "biofilms")
        )
        assert any(text.startswith(opening) for opening in mine), text
        assert not any(text.startswith(opening) for opening in theirs), text


def test_one_goal_yields_many_distinct_token_bags() -> None:
    """A short goal must still give evolution room to differ from its peers.

    The near-duplicate guard compares token *coverage*, so two sentences
    built from the same template with the terms swapped are the same bag of
    words and count as one. That made the reachable count
    ``templates * C(terms, 2)``: measured at 9 bags for the three-term goal
    below, 18 for a four-term goal and 30 for a five-term one. Each evolved
    child is checked against up to fifteen peers, so it had a majority
    chance of matching one and being discarded -- whole offline runs
    finished with every child rejected and no lineage to show, which is
    what a demo renders.

    A short goal is the case that matters, because that is what demos use.
    The floor sits well under what the clause pool actually delivers
    (measured 460 here) so adding a template or a clause can never fail it,
    while removing the independent draw would.

    The end-to-end effect is measured too, at 150 offline runs per arm of
    this goal: the narrow space published no evolved idea in 10 of 150 runs
    and the widened one in 0 of 150 (Fisher one-sided p = 0.0008). That
    comparison is only valid with a cold LLM cache per arm -- run against
    the shared one it reports no difference at all, because the second arm
    is served the first arm's responses. ``tests/test_cache_isolation.py``
    in the app suite is what keeps that from happening silently.
    """
    terms = subject_terms("Research Goal: cardiac fibrosis dynamics\n\n")
    assert len(terms) == 3, terms

    bags = {
        frozenset(
            leaf_text(random.Random(seed), 1, "hypothesis", terms)
            .lower()
            .replace(",", " ")
            .split()
        )
        for seed in range(5000)
    }

    assert len(bags) > 300, len(bags)


@pytest.mark.parametrize(
    ("field", "family"),
    [
        ("go_no_go_recommendation", _GO_NO_GO_TEMPLATES),
        ("time_to_verdict", _TIME_ESTIMATE_TEMPLATES),
        ("time_estimate", _TIME_ESTIMATE_TEMPLATES),
        ("phase_label", _PHASE_LABEL_TEMPLATES),
        ("recommended_idea", _RECOMMENDED_IDEA_TEMPLATES),
    ],
)
def test_standalone_fields_stay_a_short_label(
    field: str, family: tuple[str, ...]
) -> None:
    """The five fields _STANDALONE_TEMPLATES exempts never grow a clause.

    Guards the offline.content fix (docs/decisions/2026-09-02-offline-
    optional-field-reach.md): before it, these fields matched no
    ``_FIELD_TEMPLATES`` fragment, fell through to ``_SUMMARY_TEMPLATES``,
    and grew a trailing ``_SCOPE_CLAUSES`` sentence -- turning "Verdict:"
    or a roadmap phase prefix into a mechanism-argument run-on. Nothing
    else pins the shape: the offline-filler tests that cover these fields
    only assert ``isinstance(str) and truthy``, which the run-on also
    satisfies, so dropping a ``_FIELD_TEMPLATES`` entry or the
    ``_STANDALONE_TEMPLATES`` branch in ``leaf_text`` would regress here
    silently.
    """
    openings = _openings(family)

    for seed in range(50):
        text = leaf_text(
            random.Random(seed), 1, field, ("resistance", "biofilms")
        )
        assert text in openings, text
        assert not any(clause in text for clause in _SCOPE_CLAUSES), text


def test_identical_inputs_are_byte_identical() -> None:
    """The determinism contract the offline router depends on."""
    args = (1, "statement", ("resistance", "biofilms"))

    assert leaf_text(random.Random(7), *args) == leaf_text(
        random.Random(7), *args
    )
