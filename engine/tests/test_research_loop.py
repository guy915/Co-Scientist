from __future__ import annotations

import ast
import dataclasses
import pathlib
import re
from pathlib import Path

import pytest

from co_scientist.agents.generation.citations import format_experiment_plan
from co_scientist.llm.structured.validate import validate_json_schema
from co_scientist.models import Hypothesis
from co_scientist.offline.llm import _fill_schema
from co_scientist.research import (
    CallStatus,
    ResearchBudget,
    StopReason,
    ThreadStatus,
    conduct_research,
)
from co_scientist.schemas.generation import (
    _EXPERIMENT_CRITERION_CHARS,
    _EXPERIMENT_STEP_CHARS,
    GENERATION_SCHEMA,
    MAX_EXPERIMENT_STEPS,
)
from tests._research_fakes import FakeModel, FakeRetrieval, _budget, _hits


def test_breadth_halves_on_descent_and_stops_at_the_floor() -> None:
    budget = ResearchBudget(depth=4, breadth=8, sources=("pubmed",))

    second = budget.descend()
    assert second is not None
    assert (second.depth, second.breadth) == (3, 4)

    third = second.descend()
    assert third is not None
    assert (third.depth, third.breadth) == (2, 2)

    fourth = third.descend()
    assert fourth is not None
    # A one-question level is a lookup; breadth retains its floor.
    assert (fourth.depth, fourth.breadth) == (1, 2)
    assert fourth.descend() is None


def test_max_threads_is_quotable_before_anything_is_spent() -> None:
    budget = ResearchBudget(depth=3, breadth=8, sources=("pubmed",))

    # Follow-ups are pooled per level, so the depth bound is additive.
    assert budget.max_threads() == 14


@pytest.mark.parametrize(
    "kwargs",
    [
        {"depth": 0},
        {"breadth": 0},
        {"concurrency": 0},
        {"hits_per_question": 0},
        {"sources": ()},
    ],
)
def test_a_budget_that_funds_nothing_is_refused(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _budget(**kwargs)


async def test_first_level_is_planned_one_question_per_stance() -> None:
    model = FakeModel(stances=("mechanism", "prior art", "contradictions"))
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="reverse liver fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=3),
    )

    assert result.stances == ("mechanism", "prior art", "contradictions")
    stances_researched = {t.question.stance for t in result.threads}
    assert stances_researched == set(result.stances)


async def test_a_finding_is_identified_by_the_question_that_found_it() -> None:
    """A locator alone cannot identify evidence: its research question is
    part of its identity."""
    model = FakeModel(stances=("mechanism", "prior art"))
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="reverse liver fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2, hits_per_question=1),
    )

    findings = result.findings
    assert len(findings) == 2
    assert {f.locator for f in findings} == {"doc-a"}
    assert {f.span for f in findings} == {"span from doc-a"}
    assert findings[0].id != findings[1].id


async def test_follow_ups_become_the_next_level() -> None:
    model = FakeModel(
        stances=("mechanism",),
        follow_ups_by_question={
            "what does mechanism say about fibrosis?": [
                "which cell type drives it?"
            ]
        },
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=2, breadth=1, breadth_floor=1),
    )

    assert result.levels_run == 2
    second_level = [t for t in result.threads if t.depth == 2]
    assert [t.question.text for t in second_level] == [
        "which cell type drives it?"
    ]
    assert second_level[0].question.parent_id is not None


async def test_descent_stops_when_a_whole_level_finds_nothing() -> None:
    question = "what does mechanism say about fibrosis?"
    model = FakeModel(
        stances=("mechanism",),
        barren={question},
        follow_ups_by_question={question: ["a question from nothing"]},
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=3, breadth=1, breadth_floor=1),
    )

    assert result.stop_reason is StopReason.NO_RESULTS
    assert result.levels_run == 1
    assert model.extracted == [question]


async def test_overflow_questions_are_declined_not_dropped() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2),
        seed_questions=["q1", "q2", "q3", "q4"],
    )

    declined = result.declined()
    assert [t.question.text for t in declined] == ["q3", "q4"]
    assert all(t.retry_breadth == 4 for t in declined)
    assert all(t.note for t in declined)
    assert all(t.depth == 1 for t in declined)
    assert model.extracted == ["q1", "q2"]


async def test_one_unreachable_source_does_not_veto_the_others() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval(
        hits_by_source={"corpus": _hits("doc-a")},
        failing_sources={"pubmed"},
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=1, sources=("pubmed", "corpus")),
        seed_questions=["q1"],
    )

    by_source = {call.source: call for call in result.calls}
    assert by_source["pubmed"].status is CallStatus.FAILED
    assert by_source["pubmed"].error
    assert by_source["corpus"].status is CallStatus.OK
    assert len(result.findings) == 1


async def test_results_the_budget_refused_are_recorded_as_refused() -> None:
    """Replay needs the record of seen-but-unread results, not only accepted
    evidence."""
    model = FakeModel()
    retrieval = FakeRetrieval(
        {
            "pubmed": _hits("doc-a", "doc-b"),
            "corpus": _hits("doc-c", "doc-d"),
        }
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(
            depth=1,
            breadth=1,
            hits_per_question=2,
            sources=("pubmed", "corpus"),
        ),
        seed_questions=["q1"],
    )

    by_source = {call.source: call for call in result.calls}
    assert by_source["pubmed"].admitted == ("doc-a", "doc-b")
    assert by_source["pubmed"].dropped == ()
    assert by_source["corpus"].admitted == ()
    assert by_source["corpus"].dropped == ("doc-c", "doc-d")


async def test_a_failing_thread_does_not_take_the_level_with_it() -> None:
    model = FakeModel(exploding={"q1"})
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2),
        seed_questions=["q1", "q2"],
    )

    by_question = {t.question.text: t for t in result.threads}
    assert by_question["q1"].status is ThreadStatus.FAILED
    assert by_question["q1"].note
    assert by_question["q2"].status is ThreadStatus.OK


async def test_an_unfetchable_document_falls_back_to_its_snippet() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval(
        hits_by_source={"pubmed": _hits("doc-a")},
        unreadable={"doc-a"},
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=1),
        seed_questions=["q1"],
    )

    assert [d.full_text for d in model.documents_seen] == [False]
    assert model.documents_seen[0].text == "snippet doc-a"
    assert len(result.findings) == 1


async def test_the_loop_never_opens_more_threads_than_it_may() -> None:
    model = FakeModel(
        stances=("mechanism", "prior art", "contradictions", "methods"),
        follow_ups_by_question={},
    )
    model.follow_ups_by_question = _Everything(
        ["f1", "f2", "f3", "f4", "f5", "f6"]
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})
    budget = _budget(depth=3, breadth=4)

    result = await conduct_research(
        goal="fibrosis", model=model, retrieval=retrieval, budget=budget
    )

    started = [
        t for t in result.threads if t.status is not ThreadStatus.DECLINED
    ]
    assert len(started) <= budget.max_threads()
    assert result.levels_run == 3
    assert len(started) == 8


def test_the_package_depends_on_nothing_in_this_repo_but_itself() -> None:
    """Adapters cease to be interchangeable if the capability imports its
    caller."""
    package = pathlib.Path(conduct_research.__module__.replace(".", "/"))
    root = pathlib.Path(__file__).parents[1] / "src" / package.parent
    borrowed: set[str] = set()
    for module in sorted(root.glob("*.py")):
        tree = ast.parse(module.read_text(), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                borrowed.add(node.module)
            elif isinstance(node, ast.Import):
                borrowed.update(alias.name for alias in node.names)

    outside = {
        name
        for name in borrowed
        if name.startswith("co_scientist")
        and not name.startswith("co_scientist.research")
    }
    assert not outside


class _Everything(dict):  # type: ignore[type-arg]
    """Fresh questions avoid exercising repeated-question termination instead
    of depth bounds."""

    def __init__(self, value: list[str]) -> None:
        super().__init__()
        self._value = value
        self._asked = 0

    def get(self, key: object, default: object = None) -> list[str]:
        self._asked += 1
        return [f"{text}-{self._asked}" for text in self._value]


async def test_a_question_already_researched_is_not_researched_again() -> None:
    """Repeated questions spend scarce threads and falsely inflate research
    depth."""
    model = FakeModel(
        stances=("mechanism",),
        follow_ups_by_question={
            "seed question": ["seed question", "a new one"]
        },
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=2, breadth=2),
        seed_questions=["seed question"],
    )

    asked = [thread.question.text for thread in result.threads]
    assert asked.count("seed question") == 1
    assert "a new one" in asked


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
    format_experiment_plan({"go_criterion": bad_field})


def test_offline_schema_filler_satisfies_the_experiment_field() -> None:
    """The offline array filler emits one item; a larger minimum rejects
    every generated plan."""
    filled = _fill_schema(GENERATION_SCHEMA["schema"], lambda field: "x")
    validate_json_schema(
        {"hypotheses": [filled["hypotheses"][0]]}, GENERATION_SCHEMA
    )


def test_hypothesis_has_no_go_criterion_fields() -> None:
    """Experiment Go/No-Go criteria are design prose, not review verdicts."""
    field_names = {f.name for f in dataclasses.fields(Hypothesis)}
    assert "go_criterion" not in field_names
    assert "no_go_criterion" not in field_names
    assert "experiment_plan" not in field_names


def test_extreme_no_go_criterion_does_not_change_the_hypothesis_shape() -> None:
    """No reader may treat experiment-plan prose as a gating signal."""
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


# This list covers raw experiment readers outside schema and formatting
# boundaries.
_ALLOWED_READERS = {
    "schemas/generation.py",
}


def test_no_production_module_reads_the_raw_criteria_keys() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src" / "co_scientist"
    pattern = re.compile(r"go_criterion|no_go_criterion")
    offenders = []
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(src_root).as_posix()
        if rel in _ALLOWED_READERS:
            continue
        source = path.read_text(encoding="utf-8")
        if rel == "agents/generation/citations.py":
            formatter = next(
                node
                for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef)
                and node.name == "format_experiment_plan"
            )
            lines = source.splitlines()
            del lines[formatter.lineno - 1 : formatter.end_lineno]
            source = "\n".join(lines)
        if pattern.search(source):
            offenders.append(rel)
    assert offenders == []
