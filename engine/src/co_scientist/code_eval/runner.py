"""Running one variant through its cascade.

Three details here are the difference between a search that works and one
that looks like it works.

**The metrics file is deleted before every stage.** A stage that crashes
leaves whatever the previous stage (or the previous variant, in a reused
workspace) wrote sitting on disk, and reading it afterwards scores the
crash with somebody else's numbers. The failure is invisible: plausible
metrics, a plausible score, attached to a program that never produced
them, and the search then breeds from it.

**Nothing raises.** Every outcome is an `EvaluationResult`. See
`result.py` for why -- briefly, the host retries everything except
`UnsupportedTaskError`, so raising on a crash spends the whole attempt
budget reproducing it.

**The full output is read, not the model-facing preview.** This path uses
`WorkspaceSession` directly rather than the tool surface, because a
metrics parser needs the bytes the program actually wrote. The preview
and redaction in `workspace/output.py` are for what reaches the
transcript, which is a different question with a different answer.
"""

import json
import logging
import time
from typing import Any

from co_scientist.code_eval.result import (
    EvaluationResult,
    EvaluationStatus,
    StageOutcome,
)
from co_scientist.code_eval.spec import (
    EvaluationRequest,
    EvaluationStage,
    EvaluatorSpec,
)
from co_scientist.workspace.session import WorkspaceSession

logger = logging.getLogger(__name__)


def _write_files(session: WorkspaceSession, files: Any) -> None:
    """Places a variant's source in the workspace before evaluation."""
    for relative, content in files.items():
        target = session.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _clear_metrics(session: WorkspaceSession, spec: EvaluatorSpec) -> None:
    """Removes any metrics file left by an earlier stage or variant."""
    target = session.resolve_path(spec.metrics_path)
    target.unlink(missing_ok=True)


def _read_metrics(
    session: WorkspaceSession, spec: EvaluatorSpec
) -> tuple[dict[str, float], EvaluationStatus]:
    """Reads the metrics a stage reported.

    Returns:
        The numeric metrics and a status: NO_METRICS when the file is
        absent, INVALID_METRICS when it is not a JSON object of numbers.
        Non-numeric values are dropped rather than failing the whole
        read -- a program labelling its run is not a broken program.
    """
    target = session.resolve_path(spec.metrics_path)
    if not target.is_file():
        return {}, EvaluationStatus.NO_METRICS
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, EvaluationStatus.INVALID_METRICS
    if not isinstance(parsed, dict):
        return {}, EvaluationStatus.INVALID_METRICS
    metrics = {
        str(key): float(value)
        for key, value in parsed.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    if not metrics:
        return {}, EvaluationStatus.INVALID_METRICS
    return metrics, EvaluationStatus.OK


def _truncate(text: str, limit: int) -> str:
    """Keeps the tail of a stream, which is where a traceback ends."""
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters omitted ...]\n{text[-limit:]}"


def _failure_artifacts(
    stage: EvaluationStage, stdout: str, stderr: str, limit: int
) -> dict[str, str]:
    """Collects the evidence a failed stage leaves for the next prompt."""
    artifacts = {"failed_stage": stage.name}
    if stderr.strip():
        artifacts["stderr"] = _truncate(stderr, limit)
    if stdout.strip():
        artifacts["stdout"] = _truncate(stdout, limit)
    return artifacts


async def _run_stage(
    session: WorkspaceSession, spec: EvaluatorSpec, stage: EvaluationStage
) -> tuple[StageOutcome, dict[str, float], dict[str, str]]:
    """Runs one stage and reports what it produced.

    Returns:
        The stage outcome, the metrics it reported (empty unless the
        stage ended OK), and any artifacts worth carrying forward.
    """
    _clear_metrics(session, spec)
    started = time.monotonic()
    outcome = await session.run_command(
        list(stage.argv), timeout_seconds=stage.timeout_seconds
    )
    elapsed = time.monotonic() - started
    result = outcome.result

    if result.timed_out:
        status = EvaluationStatus.TIMED_OUT
    elif result.exit_code != 0:
        status = EvaluationStatus.FAILED
    else:
        status = EvaluationStatus.OK

    if status is not EvaluationStatus.OK:
        return (
            StageOutcome(stage.name, status, result.exit_code, elapsed),
            {},
            _failure_artifacts(
                stage, result.stdout, result.stderr, spec.artifact_chars
            ),
        )

    metrics, read_status = _read_metrics(session, spec)
    artifacts = (
        {}
        if read_status is EvaluationStatus.OK
        else _failure_artifacts(
            stage, result.stdout, result.stderr, spec.artifact_chars
        )
    )
    return (
        StageOutcome(stage.name, read_status, result.exit_code, elapsed),
        metrics,
        artifacts,
    )


class _Accumulator:
    """Carries state across a cascade's stages."""

    def __init__(self) -> None:
        """Starts an evaluation with nothing reported."""
        self.metrics: dict[str, float] = {}
        self.artifacts: dict[str, str] = {}
        self.stages: list[StageOutcome] = []
        # The last score computed. Kept across stages so a cascade that
        # fails at stage three still reports what stage two established
        # -- the alternative discards a real measurement because a later,
        # more expensive one crashed.
        self.fitness: float | None = None

    def result(self, status: EvaluationStatus) -> EvaluationResult:
        """Freezes what has accumulated into a result."""
        return EvaluationResult(
            status=status,
            fitness=self.fitness,
            metrics=dict(self.metrics),
            artifacts=dict(self.artifacts),
            stages=tuple(self.stages),
        )


def _prepare(
    session: WorkspaceSession, request: EvaluationRequest
) -> EvaluationResult | None:
    """Writes the variant's files, or reports why it could not."""
    try:
        _write_files(session, request.files)
    except (OSError, ValueError) as exc:
        logger.warning("could not place variant files: %s", exc)
        return EvaluationResult(
            status=EvaluationStatus.FAILED,
            artifacts={"error": f"could not write variant files: {exc}"},
        )
    return None


async def evaluate_variant(
    session: WorkspaceSession, request: EvaluationRequest
) -> EvaluationResult:
    """Evaluates one variant through its cascade.

    Args:
        session: The workspace to evaluate in.
        request: The variant's files and how to evaluate them.

    Returns:
        The outcome. Never raises: a crash, a timeout, an unparseable
        metrics file and a variant that never wrote one are all results,
        distinguishable by ``status``, each carrying whatever evidence
        the next prompt can use.
    """
    failure = _prepare(session, request)
    if failure is not None:
        return failure

    state = _Accumulator()
    for stage in request.spec.stages:
        stopped = await _advance(session, request.spec, stage, state)
        if stopped is not None:
            return stopped

    if state.fitness is None:
        return state.result(EvaluationStatus.NO_METRICS)
    return state.result(EvaluationStatus.OK)


async def _advance(
    session: WorkspaceSession,
    spec: EvaluatorSpec,
    stage: EvaluationStage,
    state: "_Accumulator",
) -> EvaluationResult | None:
    """Runs one stage into the accumulator, or ends the cascade.

    Returns:
        The finished result when this stage stops the cascade -- it
        failed, or its threshold rejected the variant -- else None.
    """
    outcome, metrics, artifacts = await _run_stage(session, spec, stage)
    state.stages.append(outcome)
    state.artifacts.update(artifacts)
    if outcome.status is not EvaluationStatus.OK:
        return state.result(outcome.status)

    state.metrics.update(metrics)
    state.fitness = spec.objective.fitness(state.metrics)
    if not _is_gated(stage, state.fitness):
        return None
    logger.debug(
        "variant gated after stage %s at fitness %s", stage.name, state.fitness
    )
    return state.result(EvaluationStatus.GATED)


def _is_gated(stage: EvaluationStage, fitness: float | None) -> bool:
    """Reports whether a stage's threshold stops the cascade here.

    A missing score does not gate: it is already the terminal
    NO_METRICS case, and treating it as "below threshold" would report a
    program that never ran the metric as one that ran it badly.
    """
    if stage.min_fitness is None or fitness is None:
        return False
    return fitness < stage.min_fitness
