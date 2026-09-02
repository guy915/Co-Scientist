"""Tests for format_experiment_plan (R14-20).

Covers the populated shape (numbered steps + separately bolded Go/No-Go
lines), every degraded input shape the json_object downgrade can hand it
(missing, a bare string, a partial dict, an over-long steps list), and the
no-gate guarantee: nothing in this codebase can read go_criterion/
no_go_criterion as a decision, because Hypothesis carries no such field --
format_experiment_plan is the one place the structured response is ever
inspected before it collapses into plain prose.
"""

import dataclasses
import re
from pathlib import Path

import pytest

from co_scientist.agents.generation.experiment_plan import (
    format_experiment_plan,
)
from co_scientist.llm_json import validate_json_schema
from co_scientist.models import Hypothesis
from co_scientist.offline_schema_fill import _fill_schema
from co_scientist.schemas.generation import (
    _EXPERIMENT_CRITERION_CHARS,
    _EXPERIMENT_STEP_CHARS,
    GENERATION_SCHEMA,
    MAX_EXPERIMENT_STEPS,
)


def test_populated_plan_renders_numbered_steps_and_bolded_criteria() -> None:
    text = format_experiment_plan(
        {
            "steps": [
                "Script the pipeline end to end.",
                "Calibrate against a ground-truth panel.",
                "Compare against an outgroup control.",
                "Run the Go/No-Go initial experiment.",
            ],
            "go_criterion": "AUC >= 0.8 on the held-out set.",
            "no_go_criterion": "AUC < 0.6 on the held-out set.",
        }
    )
    assert text == (
        "1. Script the pipeline end to end.\n"
        "2. Calibrate against a ground-truth panel.\n"
        "3. Compare against an outgroup control.\n"
        "4. Run the Go/No-Go initial experiment.\n"
        "**Go:** AUC >= 0.8 on the held-out set.\n"
        "**No-Go:** AUC < 0.6 on the held-out set."
    )


def test_missing_value_falls_back() -> None:
    assert format_experiment_plan(None, fallback="prior text") == "prior text"


def test_missing_value_with_no_fallback_is_none() -> None:
    assert format_experiment_plan(None) is None


def test_plain_string_passes_through_unchanged() -> None:
    """A model that ignored the structure (old free-text shape) survives."""
    assert (
        format_experiment_plan("  a free-text paragraph.  ")
        == "a free-text paragraph."
    )


def test_empty_string_falls_back() -> None:
    assert format_experiment_plan("   ", fallback="prior") == "prior"


def test_non_dict_non_string_falls_back() -> None:
    assert format_experiment_plan(42, fallback="prior") == "prior"
    assert format_experiment_plan([1, 2, 3], fallback="prior") == "prior"


def test_empty_dict_falls_back() -> None:
    assert format_experiment_plan({}, fallback="prior") == "prior"


def test_dict_missing_criteria_renders_steps_only() -> None:
    text = format_experiment_plan({"steps": ["Only one step."]})
    assert text == "1. Only one step."


def test_dict_missing_steps_renders_criteria_only() -> None:
    text = format_experiment_plan(
        {"go_criterion": "Pass if X.", "no_go_criterion": "Fail if Y."}
    )
    assert text == "**Go:** Pass if X.\n**No-Go:** Fail if Y."


def test_steps_not_a_list_degrades_to_no_steps() -> None:
    text = format_experiment_plan(
        {"steps": "not a list", "go_criterion": "Pass if X."}
    )
    assert text == "**Go:** Pass if X."


def test_non_string_step_items_are_skipped_or_stringified() -> None:
    text = format_experiment_plan({"steps": ["real step", None, ""]})
    assert text == "1. real step"


def test_steps_capped_at_max_experiment_steps() -> None:
    steps = [f"step {i}" for i in range(MAX_EXPERIMENT_STEPS + 5)]
    text = format_experiment_plan({"steps": steps})
    assert text is not None
    assert text.count("\n") == MAX_EXPERIMENT_STEPS - 1
    assert f"{MAX_EXPERIMENT_STEPS}. step {MAX_EXPERIMENT_STEPS - 1}" in text
    assert f"step {MAX_EXPERIMENT_STEPS}" not in text


def test_step_text_is_length_capped() -> None:
    long_step = "x" * (_EXPERIMENT_STEP_CHARS + 100)
    text = format_experiment_plan({"steps": [long_step]})
    assert text is not None
    # "1. " prefix plus the capped ("..."-suffixed) step text.
    assert len(text) == 3 + _EXPERIMENT_STEP_CHARS + len("...")
    assert text.endswith("...")


def test_criterion_text_is_length_capped() -> None:
    long_criterion = "y" * (_EXPERIMENT_CRITERION_CHARS + 100)
    text = format_experiment_plan({"go_criterion": long_criterion})
    assert text is not None
    assert len(text) == (
        len("**Go:** ") + _EXPERIMENT_CRITERION_CHARS + len("...")
    )
    assert text.endswith("...")


@pytest.mark.parametrize("bad_field", [123, {"nested": "dict"}, ["a", "b"]])
def test_criteria_of_the_wrong_type_never_crash(bad_field: object) -> None:
    format_experiment_plan({"go_criterion": bad_field})  # must not raise


def test_offline_schema_filler_satisfies_the_experiment_field() -> None:
    """The offline schema filler must be able to satisfy this field.

    _fill_schema fills every array with exactly one item by default;
    the schema was briefly given a minItems: 2 alongside maxItems, and
    an offline-backed run failed schema validation on every generation
    call as a result. maxItems alone (enforced server-side wherever a
    provider honors it, and again defensively by format_experiment_plan)
    is the only bound this field carries.
    """
    filled = _fill_schema(GENERATION_SCHEMA["schema"], lambda field: "x")
    validate_json_schema(
        {"hypotheses": [filled["hypotheses"][0]]}, GENERATION_SCHEMA
    )  # must not raise


# --- No-gate guarantee -------------------------------------------------


def test_hypothesis_has_no_go_criterion_fields() -> None:
    """The criteria cannot be gated on because they don't exist as fields.

    R14-20's Go/No-Go criteria are an experiment *design* detail, not a
    review verdict (never confuse with REVIEW_SCHEMA's
    go_no_go_recommendation, R14-15). format_experiment_plan collapses
    both criteria into Hypothesis.experiment's plain-string prose before
    anything else ever sees them -- there is no structured field left
    for a gate, ranker, or scorer to read.
    """
    field_names = {f.name for f in dataclasses.fields(Hypothesis)}
    assert "go_criterion" not in field_names
    assert "no_go_criterion" not in field_names
    assert "experiment_plan" not in field_names


def test_extreme_no_go_criterion_does_not_change_the_hypothesis_shape() -> None:
    """A dramatic No-Go verdict inside the plan is inert prose, not a signal.

    Nothing reads inside the rendered string looking for "No-Go" -- it is
    plain text on Hypothesis.experiment, the same field a free-text
    paragraph always occupied.
    """
    hypothesis = Hypothesis(
        text="idea",
        experiment=format_experiment_plan(
            {
                "steps": ["Run the pilot."],
                "go_criterion": "Never met.",
                "no_go_criterion": "Always met -- abandon immediately.",
            }
        ),
    )
    assert hypothesis.score == 0.0
    assert hypothesis.review_disposition is None
    assert "No-Go" in (hypothesis.experiment or "")


# Every production module that may read a raw LLM "experiment" response
# dict, outside the two call sites that funnel it through
# format_experiment_plan (agents/generation/citations.py,
# agents/evolution/evolve_results.py) and the schema/formatter definitions
# themselves. A future caller that reaches into go_criterion/
# no_go_criterion directly -- to filter, rank, or score -- would show up
# here.
_ALLOWED_READERS = {
    "schemas/generation.py",
    "agents/generation/experiment_plan.py",
}


def test_no_production_module_reads_the_raw_criteria_keys() -> None:
    """Static guarantee: only the schema + formatter ever name these keys.

    Grepping for the literal key names (rather than reasoning about call
    graphs) is the same style test_tool_param_contract.py uses to pin a
    cross-package contract -- cheap, and it catches a future caller that
    reaches past format_experiment_plan by accident.
    """
    src_root = Path(__file__).resolve().parents[1] / "src" / "co_scientist"
    pattern = re.compile(r"go_criterion|no_go_criterion")
    offenders = []
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(src_root).as_posix()
        if rel in _ALLOWED_READERS:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == []
