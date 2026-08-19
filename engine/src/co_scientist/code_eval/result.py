"""What an evaluation reports, including when it fails.

**A failed evaluation is a result, not an exception.** This host retries
every task type except `UnsupportedTaskError`, so a variant that raises
on a crash spends its whole attempt budget crashing identically three
times before the run gives up on it. Worse, the crash is the most
informative thing that happened: the traceback says what the model got
wrong, and feeding it into the next prompt is what turns a dead variant
into a direction. So every outcome below is a value, and `artifacts`
carries the evidence.

**A missing score is not a bad score.** `fitness` is None when the
program did not report, which is different from reporting badly, and the
distinction survives into ranking: `sort_key` puts unscored variants last
without pretending they scored anything.
"""

from dataclasses import dataclass, field
from enum import Enum


class EvaluationStatus(str, Enum):
    """How an evaluation ended."""

    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NO_METRICS = "no_metrics"
    INVALID_METRICS = "invalid_metrics"
    GATED = "gated"

    @property
    def is_scored(self) -> bool:
        """Whether this outcome carries a usable score.

        GATED counts: a variant rejected by a cascade threshold was
        scored, and scored too low to be worth continuing with.
        """
        return self in (EvaluationStatus.OK, EvaluationStatus.GATED)


@dataclass(frozen=True)
class StageOutcome:
    """What one cascade stage did.

    Attributes:
        name: The stage's name.
        status: How it ended.
        exit_code: Process exit status, None if it was killed.
        duration_seconds: Wall time the stage took.
    """

    name: str
    status: EvaluationStatus
    exit_code: int | None
    duration_seconds: float


@dataclass(frozen=True)
class EvaluationResult:
    """The outcome of evaluating one variant.

    Attributes:
        status: How the evaluation ended overall.
        fitness: Higher-is-better score for the *primary* objective,
            already sign-corrected. None when nothing usable was
            reported.
        objective_values: Every objective's sign-corrected score, in the
            spec's declared order, so a caller can compute dominance
            without re-deriving them from metrics and directions. The
            first entry is always ``fitness``.
        metrics: Everything the program reported, unmodified -- the raw
            values, so a minimized metric still reads as itself in a
            report even though ``fitness`` is its negation.
        artifacts: Evidence for the next prompt, chiefly a failed
            stage's stderr.
        stages: Per-stage outcomes, in the order they ran.
    """

    status: EvaluationStatus
    fitness: float | None = None
    objective_values: tuple[float | None, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    stages: tuple[StageOutcome, ...] = ()

    @property
    def sort_key(self) -> tuple[int, float]:
        """Orders results best-first without inventing a score.

        Unscored variants sort last as a group; within the scored ones,
        higher fitness wins.
        """
        if self.fitness is None:
            return (1, 0.0)
        return (0, -self.fitness)
