"""Tests for evaluating a candidate program.

These run real programs in a real sandbox rather than stubbing the
session, because every interesting case here is about what a *process*
did -- crashed, hung, wrote nothing, wrote nonsense -- and a stub answers
those questions by assumption.

Three of them guard failures that produce a plausible number rather than
an error, which is the failure mode a search cannot detect from inside:
stale metrics scoring a crash, a minimized metric sorted the wrong way,
and a missing score read as zero.
"""

import sys
from pathlib import Path

import pytest

from co_scientist.code_eval import (
    Direction,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStage,
    EvaluationStatus,
    EvaluatorSpec,
    Objective,
    evaluate_variant,
)
from co_scientist.sandbox import sandbox_backend
from co_scientist.workspace import WorkspaceSession

_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)

pytestmark = [_requires_sandbox, pytest.mark.asyncio]


def _spec(
    *stages: EvaluationStage, direction: Direction = Direction.MAXIMIZE
) -> EvaluatorSpec:
    """Builds a spec optimizing "score" over the given stages."""
    return EvaluatorSpec(
        stages=stages, objectives=(Objective("score", direction),)
    )


def _stage(
    source: str, name: str = "run", min_fitness: float | None = None
) -> EvaluationStage:
    """Builds a stage running one inline Python program."""
    return EvaluationStage(
        name=name,
        argv=(sys.executable, "-c", source),
        timeout_seconds=30,
        min_fitness=min_fitness,
    )


_WRITES_SCORE = (
    "import json, pathlib;"
    "pathlib.Path('metrics.json').write_text(json.dumps({{'score': {value}}}))"
)


async def _evaluate(
    tmp_path: Path, spec: EvaluatorSpec, files: dict[str, str] | None = None
) -> EvaluationResult:
    """Evaluates a variant in a fresh workspace."""
    return await evaluate_variant(
        WorkspaceSession(tmp_path / "ws"),
        EvaluationRequest(spec=spec, files=files or {}),
    )


# --- the happy path -------------------------------------------------------


async def test_a_reported_metric_becomes_the_fitness(tmp_path: Path) -> None:
    result = await _evaluate(
        tmp_path, _spec(_stage(_WRITES_SCORE.format(value=0.75)))
    )
    assert result.status is EvaluationStatus.OK
    assert result.fitness == pytest.approx(0.75)
    assert result.metrics["score"] == pytest.approx(0.75)


async def test_a_minimized_metric_is_negated_once(tmp_path: Path) -> None:
    """Sorted the wrong way, a search converges on the worst program.

    And reports improvement the whole way there.
    """
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(_WRITES_SCORE.format(value=0.2)),
            direction=Direction.MINIMIZE,
        ),
    )
    assert result.fitness == pytest.approx(-0.2)
    # The raw value survives, so a report still reads as itself.
    assert result.metrics["score"] == pytest.approx(0.2)


async def test_variant_files_are_written_before_the_first_stage(
    tmp_path: Path,
) -> None:
    result = await _evaluate(
        tmp_path,
        _spec(_stage("import solver; solver.main()")),
        files={
            "solver.py": (
                "import json, pathlib\n"
                "def main():\n"
                "    pathlib.Path('metrics.json').write_text("
                'json.dumps({"score": 1.5}))\n'
            )
        },
    )
    assert result.fitness == pytest.approx(1.5)


# --- failures are results, and carry evidence -----------------------------


async def test_a_crash_is_scored_not_raised(tmp_path: Path) -> None:
    """A crash is a measurement, not an exception.

    Raising spends the task's whole retry budget reproducing it.
    """
    result = await _evaluate(
        tmp_path, _spec(_stage("raise RuntimeError('boom')"))
    )
    assert result.status is EvaluationStatus.FAILED
    assert result.fitness is None


async def test_a_traceback_is_carried_forward(tmp_path: Path) -> None:
    """The crash is the most informative thing that happened."""
    result = await _evaluate(
        tmp_path, _spec(_stage("raise RuntimeError('distinctive-message')"))
    )
    assert "distinctive-message" in result.artifacts["stderr"]
    assert result.artifacts["failed_stage"] == "run"


async def test_a_hung_program_is_reported_as_a_timeout(
    tmp_path: Path,
) -> None:
    """Distinct from a crash: one is a bug, the other may be a budget."""
    stage = EvaluationStage(
        name="hang",
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        timeout_seconds=1,
    )
    result = await _evaluate(tmp_path, _spec(stage))
    assert result.status is EvaluationStatus.TIMED_OUT


async def test_a_program_that_reports_nothing_is_not_scored_zero(
    tmp_path: Path,
) -> None:
    """A missing score is not a score of zero.

    Zero is an excellent value for an error rate, so defaulting to it
    ranks a silent program above every program that worked.
    """
    result = await _evaluate(tmp_path, _spec(_stage("pass")))
    assert result.status is EvaluationStatus.NO_METRICS
    assert result.fitness is None


async def test_an_unparseable_metrics_file_is_distinguished(
    tmp_path: Path,
) -> None:
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(
                "import pathlib; "
                "pathlib.Path('metrics.json').write_text('not json')"
            )
        ),
    )
    assert result.status is EvaluationStatus.INVALID_METRICS


# --- the cascade ----------------------------------------------------------


async def test_a_stale_metrics_file_cannot_score_a_crash(
    tmp_path: Path,
) -> None:
    """The invisible failure this whole module is shaped around.

    Plausible metrics attached to a program that never produced them --
    and the search then breeds from it.
    """
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(_WRITES_SCORE.format(value=9.9), name="cheap"),
            _stage("raise RuntimeError('boom')", name="full"),
        ),
    )
    assert result.status is EvaluationStatus.FAILED
    assert (tmp_path / "ws" / "metrics.json").exists() is False


async def test_a_threshold_skips_the_expensive_stage(
    tmp_path: Path,
) -> None:
    """The whole point of a cascade: reject cheaply."""
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(
                _WRITES_SCORE.format(value=0.1), name="cheap", min_fitness=0.5
            ),
            _stage(_WRITES_SCORE.format(value=9.9), name="expensive"),
        ),
    )
    assert result.status is EvaluationStatus.GATED
    assert [stage.name for stage in result.stages] == ["cheap"]
    assert result.fitness == pytest.approx(0.1)


async def test_a_gated_variant_still_counts_as_scored(
    tmp_path: Path,
) -> None:
    """It was measured and found wanting, which is a measurement."""
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(
                _WRITES_SCORE.format(value=0.1), name="cheap", min_fitness=0.5
            ),
            _stage(_WRITES_SCORE.format(value=9.9), name="expensive"),
        ),
    )
    assert result.status.is_scored


async def test_a_later_failure_keeps_the_earlier_measurement(
    tmp_path: Path,
) -> None:
    """A costlier stage crashing does not unmeasure the cheap one.

    Discarding it throws away the only evidence the variant produced.
    """
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(_WRITES_SCORE.format(value=0.4), name="cheap"),
            _stage("raise SystemExit(3)", name="full"),
        ),
    )
    assert result.status is EvaluationStatus.FAILED
    assert result.fitness == pytest.approx(0.4)


async def test_unscored_results_sort_last(tmp_path: Path) -> None:
    scored = await _evaluate(
        tmp_path / "a", _spec(_stage(_WRITES_SCORE.format(value=0.1)))
    )
    unscored = await _evaluate(tmp_path / "b", _spec(_stage("pass")))
    assert min([unscored, scored], key=lambda r: r.sort_key) is scored


async def test_the_command_is_still_confined(tmp_path: Path) -> None:
    """The evaluator runs through the session, so the sandbox applies."""
    outside = tmp_path / "outside.txt"
    result = await _evaluate(
        tmp_path,
        _spec(
            _stage(
                "import pathlib; "
                f"pathlib.Path({str(outside)!r}).write_text('escaped')"
            )
        ),
    )
    assert result.status is EvaluationStatus.FAILED
    assert not outside.exists()
