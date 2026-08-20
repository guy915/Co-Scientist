"""Whether a retrieved span answers the question it was fetched for.

The panel is the artifact under test as much as the runner is: it exists
to separate "on the right topic" from "answers the question", so a check
that it actually contains that separation is worth more than a check
that the arithmetic runs.
"""

from __future__ import annotations

from evaluations.citation_usefulness_eval import (
    _LABELS,
    deterministic_label,
    load_dataset,
    run_deterministic,
    score,
)


def test_every_panel_item_is_well_formed() -> None:
    """A typo in a label would silently shrink the panel."""
    items = load_dataset()["items"]

    assert len(items) >= 12
    assert {item["label"] for item in items} <= set(_LABELS)
    assert len({item["id"] for item in items}) == len(items)
    assert all(item["question"].strip() for item in items)
    assert all(item["span"].strip() for item in items)


def test_the_panel_separates_topic_from_answer() -> None:
    """The case a research loop exists to catch has to be in the panel.

    A span about embryonic expression is squarely on-topic for a question
    about adult expression and answers none of it. Without items like
    that, any word-overlap measure would score well and the metric would
    be measuring nothing.
    """
    items = load_dataset()["items"]
    by_question: dict[str, set[str]] = {}
    for item in items:
        by_question.setdefault(item["question"], set()).add(item["label"])

    assert any(
        {"useful", "useless"} <= labels for labels in by_question.values()
    )


def test_the_lexical_floor_is_a_floor() -> None:
    """Kept as a baseline, never as the answer.

    If this ever scored well it would mean the panel had lost the items
    that distinguish topic from answer, not that lexical coverage had
    become a good judge of relevance.
    """
    report = run_deterministic(load_dataset())

    assert report["judge"] == "deterministic_coverage"
    assert report["metrics"]["n"] == len(load_dataset()["items"])
    assert report["metrics"]["accuracy"] < 0.7


def test_a_span_repeating_the_question_reads_as_useful() -> None:
    """The floor's rule, stated so a threshold change is deliberate."""
    question = "Is the receptor expressed in adult human liver?"

    assert (
        deterministic_label(
            question, "The receptor is expressed in adult human liver."
        )
        == "useful"
    )
    assert (
        deterministic_label(question, "Unrelated prose entirely.") == "useless"
    )


def test_a_useless_span_accepted_as_useful_is_reported() -> None:
    """The rate that matters: keeping a span that answers nothing."""
    metrics = score([("a", "useless", "useful"), ("b", "useless", "useless")])

    assert metrics["false_useful_rate"] == 0.5
