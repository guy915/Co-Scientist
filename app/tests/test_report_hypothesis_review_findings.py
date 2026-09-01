"""Unit coverage for the two review-derived hypothesis subsections.

``_render_hypothesis_verdict`` (R14-15, the display-only Go/No-Go framing)
and ``_render_hypothesis_simulation_review`` (R14-22, the numbered failure
points) both read ``detail_json`` off the drained review rows. These pin
each function's populated/absent/malformed behavior directly, complementing
the full end-to-end pin in ``test_report_hypothesis_entry_rendering.py``.
"""

import json

from app.report_markdown_hypothesis import (
    _render_hypothesis_simulation_review,
    _render_hypothesis_verdict,
    _reviews_by_hypothesis,
)


def _review(agent: str, detail: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {"hypothesis_id": "h1", "reviewer_agent": agent}
    if detail is not None:
        row["detail_json"] = json.dumps(detail)
    return row


# ---------------------------------------------------------------------------
# _render_hypothesis_verdict (R14-15)
# ---------------------------------------------------------------------------


def test_verdict_renders_both_fields_when_present() -> None:
    reviews = [
        _review(
            "full_review",
            {"go_no_go": "Go — pursue validation.", "time_to_verdict": "Short"},
        )
    ]
    assert _render_hypothesis_verdict(reviews) == [
        "**Verdict:** Go — pursue validation.",
        "",
        "**Time to Verdict:** Short",
        "",
    ]


def test_verdict_prefers_recurrent_over_full() -> None:
    reviews = [
        _review("full_review", {"go_no_go": "stale framing"}),
        _review("recurrent_review", {"go_no_go": "fresh framing"}),
    ]
    lines = _render_hypothesis_verdict(reviews)
    assert lines[0] == "**Verdict:** fresh framing"


def test_verdict_omits_entirely_when_no_review_row() -> None:
    assert _render_hypothesis_verdict([]) == []


def test_verdict_omits_entirely_when_detail_json_absent() -> None:
    """A run whose reviews predate this column carries no ``detail_json``."""
    reviews = [{"hypothesis_id": "h1", "reviewer_agent": "full_review"}]
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_renders_only_the_field_present() -> None:
    reviews = [_review("full_review", {"time_to_verdict": "2-3 months"})]
    assert _render_hypothesis_verdict(reviews) == [
        "**Time to Verdict:** 2-3 months",
        "",
    ]


def test_verdict_degrades_on_malformed_json() -> None:
    reviews = [{"hypothesis_id": "h1", "reviewer_agent": "full_review",
                "detail_json": "{not valid json"}]
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_degrades_when_detail_json_is_not_an_object() -> None:
    reviews = [_review("full_review", None)]
    reviews[0]["detail_json"] = json.dumps(["go", "short"])
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_coerces_non_string_field_values() -> None:
    detail = {"go_no_go": 42, "time_to_verdict": None}
    reviews = [_review("full_review", detail)]
    assert _render_hypothesis_verdict(reviews) == [
        "**Verdict:** 42",
        "",
    ]


# ---------------------------------------------------------------------------
# _render_hypothesis_simulation_review (R14-22)
# ---------------------------------------------------------------------------


def test_simulation_review_renders_numbered_points_and_decisive_step() -> None:
    reviews = [
        _review(
            "simulation_review",
            {
                "failure_points": [
                    "Off-target editing risk.",
                    "Delivery inefficiency.",
                ],
                "decisive_step": "Step 4: vector reaches target tissue.",
            },
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "1. **Failure point:** Off-target editing risk.",
        "2. **Failure point:** Delivery inefficiency.",
        "",
        "**Decisive step:** Step 4: vector reaches target tissue.",
        "",
    ]


def test_simulation_review_omits_when_mechanism_holds() -> None:
    """No failure points and no decisive step is the schema's sound case."""
    reviews = [_review("simulation_review", {})]
    assert _render_hypothesis_simulation_review(reviews) == []


def test_simulation_review_omits_when_no_review_row() -> None:
    assert _render_hypothesis_simulation_review([]) == []


def test_simulation_review_renders_decisive_step_alone() -> None:
    reviews = [
        _review("simulation_review", {"decisive_step": "Step 1: binding."})
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "**Decisive step:** Step 1: binding.",
        "",
    ]


def test_simulation_review_degrades_when_failure_points_not_a_list() -> None:
    reviews = [
        _review(
            "simulation_review",
            {"failure_points": "a single string", "decisive_step": "Step 2."},
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "**Decisive step:** Step 2.",
        "",
    ]


def test_simulation_review_skips_blank_points() -> None:
    reviews = [
        _review(
            "simulation_review",
            {"failure_points": ["", "   ", "A real point."]},
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "1. **Failure point:** A real point.",
        "",
    ]


# ---------------------------------------------------------------------------
# _reviews_by_hypothesis: the grouping that scopes reviews per hypothesis
# before either renderer above ever sees them.
# ---------------------------------------------------------------------------


def test_reviews_by_hypothesis_keeps_each_hypothesis_separate() -> None:
    reviews = [
        _review("simulation_review", {"decisive_step": "for h1"}),
        {
            "hypothesis_id": "h2",
            "reviewer_agent": "simulation_review",
            "detail_json": json.dumps({"decisive_step": "for h2"}),
        },
    ]
    grouped = _reviews_by_hypothesis(reviews)
    assert [r["hypothesis_id"] for r in grouped["h1"]] == ["h1"]
    assert [r["hypothesis_id"] for r in grouped["h2"]] == ["h2"]
    # A hypothesis id absent from the run's reviews is simply absent from
    # the mapping -- callers guard with .get(hyp_id, []), not a KeyError.
    assert "h3" not in grouped
