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
        objective: What is being optimized, and which way.
        metrics_path: Workspace-relative JSON file the program writes its
            metrics to. A file rather than stdout because a real program
            prints warnings, progress bars and library chatter, and a
            metric parsed out of that stream is a metric that breaks when
            somebody adds a log line.
        artifact_chars: Ceiling on captured output carried forward.
    """

    stages: tuple[EvaluationStage, ...]
    objective: Objective
    metrics_path: str = "metrics.json"
    artifact_chars: int = DEFAULT_ARTIFACT_CHARS


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
