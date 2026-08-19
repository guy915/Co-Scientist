"""What it means to evaluate one candidate program.

The types here are the boundary between an agent that proposes code and
a sandbox that runs it, and two of them exist to stop a specific silent
failure rather than to describe anything.

**`Objective` owns the sign.** The evolution literature this borrows from
maximizes unconditionally; the worked example it is being pointed at
minimizes mean absolute error. Leaving that to callers means one of them
eventually sorts a minimized metric descending and the search converges
confidently on the worst program it can find, reporting improvement the
whole way. So `fitness` is always higher-is-better, and the negation
happens once, here.

**`EvaluationStage` exists for cost, and the threshold is the point.** A
few hundred variants at full evaluation is the entire budget of a run.
Cheap stages first, each gating the next, means a variant that fails to
import is rejected for the price of an import.

**Several objectives are kept several.** A run optimizing accuracy *and*
latency has no single best program, and the tempting collapse -- a
weighted sum -- is worse than it looks: the weights multiply raw values
on unrelated scales, so an objective measured in seconds and one measured
in [0, 1] produce a total that the seconds term decides entirely, whatever
weights were written. Nothing reports an error; the second objective just
stops mattering. So `fitness` stays the *first* objective's score, used
for ordering and for the cascade thresholds, and every other objective
reaches the search through Pareto dominance instead (`pareto.py`), where
no cross-scale arithmetic is required.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

# Default wall clock for one stage. Long enough for a real fit, short
# enough that a hung variant does not hold a durable task's lease past
# its renewal.
DEFAULT_STAGE_TIMEOUT_SECONDS = 300.0

# How much of a failed stage's output is carried forward into the next
# prompt. Enough for a traceback, bounded so one crash cannot fill the
# context that has to hold the code.
DEFAULT_ARTIFACT_CHARS = 4_000


class Direction(Enum):
    """Which way is better for a metric."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True)
class Objective:
    """The metric a search is optimizing, and its direction.

    Attributes:
        metric: Key the program reports under.
        direction: Whether larger or smaller is better.
    """

    metric: str
    direction: Direction = Direction.MAXIMIZE

    def fitness(self, metrics: Mapping[str, float]) -> float | None:
        """Converts reported metrics into a higher-is-better score.

        Args:
            metrics: What the program reported.

        Returns:
            The score, or None when the objective's metric is absent --
            which is a failure to report, not a score of zero. Zero is a
            legitimate value for most metrics and an excellent one for
            an error rate, so defaulting to it would rank a program that
            reported nothing above every program that worked.
        """
        raw = metrics.get(self.metric)
        if raw is None:
            return None
        return -raw if self.direction is Direction.MINIMIZE else raw


@dataclass(frozen=True)
class EvaluationStage:
    """One step of a cascade, and the bar for continuing past it.

    Attributes:
        name: Identifies the stage in results and logs.
        argv: The command, already split.
        timeout_seconds: Wall-clock ceiling for this stage.
        min_fitness: Score below which later stages are skipped. None
            runs the next stage regardless.
    """

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = DEFAULT_STAGE_TIMEOUT_SECONDS
    min_fitness: float | None = None


@dataclass(frozen=True)
class EvaluatorSpec:
    """How to evaluate a variant, start to finish.

    Attributes:
        stages: Cascade steps, cheapest first.
        objectives: What is being optimized, in declared order. The first
            is the primary: it is what `fitness` reports, what the
            cascade thresholds compare against, and what the surface
            plots. The rest are equally real, but they act through
            dominance rather than through a score -- see the module
            docstring for why they are not summed.
        metrics_path: Workspace-relative JSON file the program writes its
            metrics to. A file rather than stdout because a real program
            prints warnings, progress bars and library chatter, and a
            metric parsed out of that stream is a metric that breaks when
            somebody adds a log line.
        artifact_chars: Ceiling on captured output carried forward.
        dataset_paths: Read-only inputs placed in the workspace before
            every run. Part of the evaluation environment rather than of
            the program, which is why they live here and not in a
            variant's source: the proposal agent rewrites every file it
            is handed, so data given to it as source would be patched
            like code. Names only -- the proposal prompt states them so
            a program can open them, and never their contents.
    """

    stages: tuple[EvaluationStage, ...]
    objectives: tuple[Objective, ...]
    metrics_path: str = "metrics.json"
    artifact_chars: int = DEFAULT_ARTIFACT_CHARS
    dataset_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuses a spec with nothing to optimize."""
        if not self.objectives:
            raise ValueError("an evaluator spec needs at least one objective")

    @property
    def objective(self) -> Objective:
        """The primary objective: the one `fitness` reports."""
        return self.objectives[0]

    def objective_values(
        self, metrics: Mapping[str, float]
    ) -> tuple[float | None, ...]:
        """Scores every objective, higher-is-better, in declared order.

        Args:
            metrics: What the program reported.

        Returns:
            One entry per objective, None where that objective's metric
            was not reported. A None is not a zero and not a floor: a
            variant missing an objective simply has no position on that
            axis, which is what keeps dominance from ranking it.
        """
        return tuple(
            objective.fitness(metrics) for objective in self.objectives
        )


@dataclass(frozen=True)
class EvaluationRequest:
    """One variant to evaluate.

    Attributes:
        spec: How to evaluate it.
        files: Workspace-relative paths to write before the first stage,
            mapped to their contents. Empty when the caller has already
            placed the code -- an evolution loop applies a diff, a first
            generation writes whole files.
    """

    spec: EvaluatorSpec
    files: Mapping[str, str] = field(default_factory=dict)
