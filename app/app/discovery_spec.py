"""Reading a run's evaluator spec out of its stored config.

A discovery run is configured once, at creation, with what to optimize
and how to measure it. This module turns that JSON into the engine's
``EvaluatorSpec``.

**Every failure here raises.** The tempting alternative -- fall back to
an empty cascade, or to a default objective -- produces a run that
executes normally and scores every variant identically, which reads as
"the model cannot write working code" rather than as "the run was
misconfigured". A spec that cannot be built is a permanent, unretryable
condition, so it must surface as one at the boundary rather than as a
uniform absence of progress across hundreds of variants.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from co_scientist.agents.code_evolve import (
    DEFAULT_CELLS,
    METRIC_WILDCARD,
    Descriptor,
    Grid,
    GridStrategy,
    UnbinnableFeatureError,
    default_descriptors_for,
    projection_from_json,
)
from co_scientist.code_eval import (
    DEFAULT_STAGE_TIMEOUT_SECONDS,
    Direction,
    EvaluationStage,
    EvaluatorSpec,
    Objective,
)

# Whether the *host* can run what a spec asks for is a different kind of
# fact from what the spec says, and lives in app/discovery_execution.py.
# Imported back and re-exported (a redundant alias) so callers and tests
# keep reaching it at app.discovery_spec exactly as before.
from app.discovery_execution import (
    code_execution_backend as code_execution_backend,
)

# Key under which a run's config carries its discovery configuration.
# Its presence is what makes a run a discovery run.
DISCOVERY_CONFIG_KEY = "discovery"

_DIRECTIONS = {
    "maximize": Direction.MAXIMIZE,
    "minimize": Direction.MINIMIZE,
}


class DiscoverySpecError(ValueError):
    """Raised when a run's evaluator spec is absent or malformed."""


def discovery_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Returns a run's discovery block, or None if it has none."""
    block = (config or {}).get(DISCOVERY_CONFIG_KEY)
    return block if isinstance(block, dict) else None


def is_discovery_run(config: dict[str, Any] | None) -> bool:
    """Reports whether a run is a computational-discovery run."""
    return discovery_config(config) is not None


def _objectives(block: dict[str, Any]) -> tuple[Objective, ...]:
    """Reads the run's objectives, in declared order.

    Accepts ``objectives`` (a list) or ``objective`` (one). The first is
    the primary: it is what the cascade thresholds compare against and
    what the surface plots. The rest reach the search through Pareto
    dominance, never through a weighted sum -- see the note in
    ``code_eval/spec.py`` for why summing them silently discards
    whichever objective has the smaller scale.
    """
    raw = block.get("objectives")
    if raw is None:
        return (_objective(block.get("objective")),)
    if not isinstance(raw, list) or not raw:
        raise DiscoverySpecError(
            "discovery.objectives must be a non-empty list"
        )
    return tuple(_objective(item) for item in raw)


def _objective(raw: Any) -> Objective:
    """Builds the objective, refusing an unknown optimization direction."""
    if not isinstance(raw, dict):
        raise DiscoverySpecError("discovery.objective must be an object")
    metric = raw.get("metric")
    if not isinstance(metric, str) or not metric:
        raise DiscoverySpecError("discovery.objective.metric must be a name")
    name = str(raw.get("direction", "maximize")).lower()
    direction = _DIRECTIONS.get(name)
    if direction is None:
        raise DiscoverySpecError(
            f"discovery.objective.direction must be one of "
            f"{sorted(_DIRECTIONS)}, got {name!r}"
        )
    return Objective(metric=metric, direction=direction)


def _argv(raw: Any, index: int) -> tuple[str, ...]:
    """Validates one stage's command.

    A stage with no command would run nothing, report nothing, and score
    every variant the same -- the exact silent-uniformity failure this
    module exists to prevent.
    """
    if not isinstance(raw, list) or not raw:
        raise DiscoverySpecError(
            f"discovery.stages[{index}].argv must be a non-empty list"
        )
    if not all(isinstance(part, str) for part in raw):
        raise DiscoverySpecError(
            f"discovery.stages[{index}].argv must contain only strings"
        )
    return tuple(str(part) for part in raw)


def _optional_float(raw: Any, field: str) -> float | None:
    """Reads an optional numeric field, refusing a non-number."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise DiscoverySpecError(f"{field} must be a number")
    return float(raw)


def _stage(raw: Any, index: int) -> EvaluationStage:
    """Builds one cascade stage."""
    if not isinstance(raw, dict):
        raise DiscoverySpecError(f"discovery.stages[{index}] must be an object")
    timeout = _optional_float(
        raw.get("timeout_seconds"), f"discovery.stages[{index}].timeout_seconds"
    )
    return EvaluationStage(
        name=str(raw.get("name") or f"stage-{index + 1}"),
        argv=_argv(raw.get("argv"), index),
        timeout_seconds=(
            DEFAULT_STAGE_TIMEOUT_SECONDS if timeout is None else timeout
        ),
        min_fitness=_optional_float(
            raw.get("min_fitness"), f"discovery.stages[{index}].min_fitness"
        ),
    )


def evaluator_spec(config: dict[str, Any] | None) -> EvaluatorSpec:
    """Builds the evaluator spec for a discovery run.

    Args:
        config: The run's stored config.

    Returns:
        The spec its variants are evaluated against.

    Raises:
        DiscoverySpecError: If the run is not a discovery run, or its
            discovery block is malformed. Never a default spec -- see the
            module docstring.
    """
    block = discovery_config(config)
    if block is None:
        raise DiscoverySpecError("run has no discovery configuration")
    raw_stages = block.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise DiscoverySpecError("discovery.stages must be a non-empty list")
    return EvaluatorSpec(
        stages=tuple(
            _stage(raw, index) for index, raw in enumerate(raw_stages)
        ),
        objectives=_objectives(block),
        metrics_path=str(block.get("metrics_path") or "metrics.json"),
    )


def _descriptor(raw: Any, index: int) -> Descriptor:
    """Builds one archive axis."""
    if not isinstance(raw, dict):
        raise DiscoverySpecError(
            f"discovery.descriptors[{index}] must be an object"
        )
    feature = raw.get("feature")
    if not isinstance(feature, str) or not feature:
        raise DiscoverySpecError(
            f"discovery.descriptors[{index}].feature must be a name"
        )
    edges = raw.get("bins") or []
    if not isinstance(edges, list) or not all(
        isinstance(edge, (int, float)) and not isinstance(edge, bool)
        for edge in edges
    ):
        raise DiscoverySpecError(
            f"discovery.descriptors[{index}].bins must be a list of numbers"
        )
    return Descriptor(
        feature=feature, bins=tuple(sorted(float(edge) for edge in edges))
    )


def _objective_metric_names(block: dict[str, Any]) -> tuple[str, ...]:
    """The metrics this run scores on, read without raising.

    Feeds the ``metric:*`` wildcard's exclusion list: an objective's
    value *is* the variant's score, so niching on it niches by progress
    -- the failure the grid module measures -- and it would arrive
    through the one axis nobody declared.

    Deliberately tolerant where ``_objectives`` is strict: a malformed
    objective is already refused when the run is created, and this is
    also reached from read-only paths where raising would be new.
    """
    raw = block.get("objectives")
    items = raw if isinstance(raw, list) else [block.get("objective")]
    return tuple(
        item["metric"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("metric"), str)
        and item["metric"]
    )


def _with_objectives_excluded(
    axes: tuple[Descriptor, ...], block: dict[str, Any]
) -> tuple[Descriptor, ...]:
    """Tells the metric wildcard which metrics are this run's score."""
    names = _objective_metric_names(block)
    return tuple(
        replace(axis, exclude=names)
        if axis.feature == METRIC_WILDCARD
        else axis
        for axis in axes
    )


def descriptors(
    config: dict[str, Any] | None,
    strategy: GridStrategy = GridStrategy.CVT,
) -> tuple[Descriptor, ...]:
    """Returns the archive axes a run's variants are niched along.

    Defaults rather than raising when unset, because every run gets a
    usable grid for free: what move produced a variant, how deeply
    nested it is, what it depends on, whether it recurses, and a
    fingerprint of its syntax. The last is what separates a `for` loop
    from a `while` loop from a comprehension -- three different
    algorithms that every surface feature reads as one cell.

    Raises:
        DiscoverySpecError: If ``descriptors`` is present but malformed.
            Present-and-wrong is a different case from absent: silently
            falling back would leave a run niching along axes its author
            did not choose and has no way to notice.
    """
    block = discovery_config(config) or {}
    raw = block.get("descriptors")
    if raw is None:
        return _with_objectives_excluded(
            tuple(default_descriptors_for(strategy)), block
        )
    if not isinstance(raw, list) or not raw:
        raise DiscoverySpecError(
            "discovery.descriptors must be a non-empty list when present"
        )
    declared = tuple(_descriptor(item, index) for index, item in enumerate(raw))
    return _with_objectives_excluded(declared, block)


def _grid_strategy(raw: Any) -> GridStrategy:
    """Reads the niching strategy, refusing one this build cannot run."""
    name = str(raw or GridStrategy.CVT.value).lower()
    try:
        return GridStrategy(name)
    except ValueError as exc:
        allowed = sorted(item.value for item in GridStrategy)
        raise DiscoverySpecError(
            f"discovery.grid.strategy must be one of {allowed}, got {name!r}"
        ) from exc


def grid(config: dict[str, Any] | None) -> Grid:
    """Returns how a run turns behaviour into archive cells.

    Defaults to CVT, which is the only strategy whose archive size is
    bounded by construction: declared bin edges are guesses about a
    distribution nobody has seen yet, and both ways of guessing wrong
    disable the archive silently -- too coarse and every variant shares
    one cell, too fine and every variant gets its own.

    Raises:
        DiscoverySpecError: If ``grid`` is present but malformed, or if
            the axes and the strategy are a combination the engine
            refuses. That refusal is translated here rather than left to
            propagate: this module is the boundary every caller reads
            the spec through, and one exception type is what lets the
            create endpoint answer 422 instead of 500.
    """
    raw = (discovery_config(config) or {}).get("grid")
    try:
        return _grid(config, raw)
    except UnbinnableFeatureError as exc:
        raise DiscoverySpecError(str(exc)) from exc


def _grid(config: dict[str, Any] | None, raw: Any) -> Grid:
    """Builds the grid from an already-extracted ``grid`` block."""
    if raw is None:
        return Grid(descriptors=descriptors(config))
    if not isinstance(raw, dict):
        raise DiscoverySpecError("discovery.grid must be an object")
    cells = raw.get("cells", DEFAULT_CELLS)
    if isinstance(cells, bool) or not isinstance(cells, int) or cells < 1:
        raise DiscoverySpecError(
            "discovery.grid.cells must be a positive integer"
        )
    strategy = _grid_strategy(raw.get("strategy"))
    return Grid(
        descriptors=descriptors(config, strategy),
        strategy=strategy,
        cells=cells,
        projection=projection_from_json(raw.get("projection")),
    )


def seed_source(config: dict[str, Any] | None) -> dict[str, str]:
    """Returns the starting program, ``{path: contents}``.

    Raises:
        DiscoverySpecError: If it is absent or is not a map of text
            files. A discovery run with nothing to evolve from would
            propose its first variant against an empty program.
    """
    block = discovery_config(config) or {}
    raw = block.get("seed_source")
    if not isinstance(raw, dict) or not raw:
        raise DiscoverySpecError(
            "discovery.seed_source must be a non-empty map"
        )
    if not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise DiscoverySpecError("discovery.seed_source must map paths to text")
    return {str(k): str(v) for k, v in raw.items()}


# Key naming a previous discovery run to carry an archive forward from.
SEED_FROM_RUN_KEY = "seed_from_run"

# How many inherited programs a run may start from. A cap, not a target:
# every one of them is a full evaluation before the search has proposed
# anything, so an unbounded archive would spend a whole budget
# re-measuring what the previous run already knew.
MAX_INHERITED_SEEDS = 6


def seed_from_run(config: dict[str, Any] | None) -> str | None:
    """Returns the run this one inherits its starting programs from.

    Raises:
        DiscoverySpecError: If the key is present but is not a run id.
    """
    block = discovery_config(config) or {}
    raw = block.get(SEED_FROM_RUN_KEY)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise DiscoverySpecError(
            f"discovery.{SEED_FROM_RUN_KEY} must be a run id"
        )
    return raw.strip()
