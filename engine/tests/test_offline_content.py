"""Tests for the offline backend's leaf-text generation.

The content is cosmetic -- offline runs exercise the pipeline, they do not
produce findings -- but a demo or e2e run is what a reader judges the
product's output by, so these pin the properties that make it readable:
it is about the run's subject, it varies by field, and it never mines its
own output as if it were subject matter.
"""

import random

import pytest

from co_scientist.offline_content import (
    _GENERATED_VOCABULARY,
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


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("experimental_context", "Titrate"),
        ("constructive_feedback", "under-specified"),
    ],
    ids=["experiment_reads_as_a_protocol", "feedback_reads_as_a_critique"],
)
def test_leaves_vary_by_the_field_they_land_in(
    field: str, expected: str
) -> None:
    """One sentence shape across every field renders a run as filler.

    ``_fill_schema`` reaches a title, a mechanism and a reviewer's critique
    through the same code path, so the property name is what distinguishes
    them.
    """
    text = leaf_text(random.Random(1), 1, field, ("resistance", "biofilms"))

    assert expected in text


def test_identical_inputs_are_byte_identical() -> None:
    """The determinism contract the offline router depends on."""
    args = (1, "statement", ("resistance", "biofilms"))

    assert leaf_text(random.Random(7), *args) == leaf_text(
        random.Random(7), *args
    )
