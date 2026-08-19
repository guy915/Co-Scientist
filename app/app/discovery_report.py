"""The report a discovery run publishes when it finishes.

A discovery run has no hypotheses, so it cannot reuse the hypothesis
report: every count in that payload is named for something this run does
not have, and filling them with variant numbers would produce a report
that contradicts its own tabs. This builds a separate payload under
``report_kind: "discovery"``, and consumers branch on that rather than
guessing from which fields happen to be populated.

What the report is *for* is the part worth stating. The Variants tab
already shows every attempt live. The report exists to answer the three
questions the tab cannot: what the run settled on, what it traded away,
and whether it actually explored or spent its budget polishing one idea.
The last is why coverage and its evenness are in the summary rather than
buried -- a run that reached twelve cells with everything piled in one
looks identical to a thorough one until someone says so.
"""

from __future__ import annotations

import logging
from typing import Any

from app import store
from app.discovery_spec import DiscoverySpecError, evaluator_spec

logger = logging.getLogger(__name__)

# Longest program included verbatim in the report. A discovery run can
# evolve something large, and a report nobody can scroll is not a
# report; the full source stays available per-variant in the API.
MAX_REPORT_SOURCE_CHARS = 8_000

# Evenness below which a run's spread is called out as lopsided. Matches
# the threshold the Variants tab uses, so the two never disagree about
# whether a run explored.
LOPSIDED_BELOW = 0.5

MINIMIZE = "minimize"


def measured(value: float | None, direction: str) -> str:
    """Renders one objective value as the metric it was measured in.

    Stored values are sign-corrected so that higher is always better,
    which means a minimized metric is held negated. Printing that
    straight reports 1.9 seconds as -1.9 -- a number no reader can
    reconcile with anything the program produced. The trade-off plot
    already undoes it; this is the same undoing for the report.
    """
    if value is None:
        return "—"
    raw = -float(value) if direction == MINIMIZE else float(value)
    return str(round(raw, 4))


def _objective_lines(spec: Any) -> list[str]:
    """Names what the run was optimizing, in declared order."""
    lines = []
    for index, objective in enumerate(spec.objectives):
        role = "primary" if index == 0 else "secondary"
        lines.append(
            f"- `{objective.metric}` ({objective.direction.value}, {role})"
        )
    return lines


def _variant_row(variant: dict[str, Any], direction: str) -> str:
    """One row of the attempt table."""
    score = measured(variant["fitness"], direction)
    operator = variant["operator"] or "seed"
    flags = []
    if variant.get("is_best_so_far"):
        flags.append("best so far")
    if variant.get("is_pareto_optimal"):
        flags.append("on the front")
    return (
        f"| {variant['ordinal']} | {operator.replace('_', ' ')} "
        f"| {variant['status']} | {score} | {', '.join(flags)} |"
    )


def _coverage_sentence(occupied: int, evenness: float, total: int) -> str:
    """States how much of the behaviour space the run actually reached."""
    attempts = f"{total} attempt" + ("" if total == 1 else "s")
    if occupied == 0:
        return f"{attempts}; none were measured for behaviour."
    spread = (
        " Most attempts landed in one of them, so the run explored less "
        "than that count suggests."
        if occupied > 1 and evenness < LOPSIDED_BELOW
        else ""
    )
    noun = "approach" if occupied == 1 else "distinct approaches"
    return f"{attempts} across {occupied} {noun}.{spread}"


def _one_source(path: str, whole: str, budget: int) -> list[str]:
    """Renders one file of the winning program, cut to `budget` chars."""
    body = whole[:budget]
    if body != whole:
        # Said inside the fence, not after it: a program cut short
        # silently reads as a complete one, and someone will run it.
        body += "\n... truncated; the full program is on the variant."
    return ["", f"### `{path}`", "", "```", body, "```"]


def _source_sections(source: dict[str, str]) -> list[str]:
    """The winning program, bounded so the report stays readable."""
    lines: list[str] = []
    budget = MAX_REPORT_SOURCE_CHARS
    paths = sorted(source)
    for index, path in enumerate(paths):
        lines += _one_source(path, source[path], budget)
        budget -= len(source[path][:budget])
        if budget <= 0:
            remaining = len(paths) - index - 1
            if remaining:
                lines += ["", f"_{remaining} more file(s) omitted for length._"]
            break
    return lines


def _best_section(best: dict[str, Any] | None, direction: str) -> list[str]:
    """The program the run settled on, with its source."""
    if best is None:
        return ["## Result", "", "No attempt produced a usable score."]
    lines = [
        "## Result",
        "",
        f"Attempt {best['ordinal']} scored "
        f"{measured(best['fitness'], direction)}"
        f" via `{(best['operator'] or 'seed').replace('_', ' ')}`.",
    ]
    if best.get("rationale"):
        lines += ["", best["rationale"]]
    return lines + _source_sections(best["source"])


def _front_row(variant: dict[str, Any], directions: list[str]) -> str:
    """One attempt's objective values, each in its own units."""
    values = list(variant.get("objective_values") or [])
    padded = (values + [None] * len(directions))[: len(directions)]
    cells = [
        measured(value, direction)
        for value, direction in zip(padded, directions, strict=True)
    ]
    return f"| {variant['ordinal']} | " + " | ".join(cells) + " |"


def _front_section(
    front: list[dict[str, Any]], spec: Any, directions: list[str]
) -> list[str]:
    """The real trades, when there is more than one objective."""
    if len(directions) < 2:
        return []
    headers = [
        f"`{objective.metric}` "
        f"{'↓' if objective.direction.value == MINIMIZE else '↑'}"
        for objective in spec.objectives
    ]
    return [
        "## The trade-off",
        "",
        f"This run optimized {len(directions)} things at once, so there is "
        "no single best program. These attempts are the ones nothing beat "
        "on every objective. The arrow says which way is better:",
        "",
        "| # | " + " | ".join(headers) + " |",
        "|---|" + "---|" * len(directions),
        *[_front_row(variant, directions) for variant in front],
    ]


def _spec_or_none(config: dict[str, Any]) -> Any:
    """The run's evaluator spec, or None when it no longer parses.

    A report must still say what happened when the config has been
    edited since the run: it loses the objective names, not the run.
    """
    try:
        return evaluator_spec(config)
    except DiscoverySpecError:
        return None


def _attempt_table(variants: list[dict[str, Any]], primary: str) -> list[str]:
    """Every attempt in order, failures included."""
    return [
        "## Every attempt",
        "",
        "Failed attempts keep their number: the sequence is only honest "
        "if what went nowhere still occupies a place in it.",
        "",
        "| # | Change | Outcome | Score | Notes |",
        "|---|---|---|---|---|",
        *[_variant_row(variant, primary) for variant in variants],
    ]


def _mark_front(variants: list[dict[str, Any]]) -> None:
    """Flags the attempts nothing dominates, in place.

    Derived here rather than stored: one new variant can take an older
    one off the front, so a written flag is wrong by the next
    generation.
    """
    from app.engine_tasks_variants_schedule import pareto_variant_ids

    front_ids = pareto_variant_ids(variants)
    for variant in variants:
        variant["is_pareto_optimal"] = str(variant["id"]) in front_ids


def build_markdown(
    run: store.RunRow,
    variants: list[dict[str, Any]],
    coverage: tuple[int, float],
) -> str:
    """Renders a discovery run's report."""
    spec = _spec_or_none(run.config)
    directions = (
        []
        if spec is None
        else [item.direction.value for item in spec.objectives]
    )
    primary = directions[0] if directions else "maximize"
    _mark_front(variants)
    best = max(
        (v for v in variants if v["fitness"] is not None),
        key=lambda v: (float(v["fitness"]), -int(v["ordinal"])),
        default=None,
    )
    occupied, evenness = coverage
    lines = [
        f"# {run.research_goal}",
        "",
        "## What was optimized",
        "",
        *([] if spec is None else _objective_lines(spec)),
        "",
        _coverage_sentence(occupied, evenness, len(variants)),
        "",
        *_best_section(best, primary),
        "",
        *_front_section(
            [v for v in variants if v["is_pareto_optimal"]], spec, directions
        ),
        "",
        *_attempt_table(variants, primary),
    ]
    return "\n".join(lines).strip() + "\n"


def build_payload(
    run: store.RunRow,
    variants: list[dict[str, Any]],
    coverage: tuple[int, float],
) -> dict[str, Any]:
    """Assembles the structured half of a discovery report.

    Keys are deliberately not the hypothesis report's. A discovery run
    has no hypotheses, no evidence and no tournament, and reusing those
    names would produce a payload whose every count means something
    other than what it says.
    """
    occupied, evenness = coverage
    spec = _spec_or_none(run.config)
    scored = [v for v in variants if v["fitness"] is not None]
    return {
        "report_kind": "discovery",
        "research_goal": run.research_goal,
        "run_mode": run.profile,
        "provider": run.provider,
        # Carried so a reader of `best_fitness` can undo its sign
        # correction. Without the direction beside it, a minimized
        # metric renders as a negative number of seconds.
        "objectives": []
        if spec is None
        else [
            {"metric": item.metric, "direction": item.direction.value}
            for item in spec.objectives
        ],
        "variant_count": len(variants),
        "scored_count": len(scored),
        "generation_count": max(
            (int(v["generation"]) for v in variants), default=0
        )
        + 1,
        "niches_occupied": occupied,
        "niche_evenness": evenness,
        "best_variant_id": None
        if not scored
        else max(scored, key=lambda v: float(v["fitness"]))["id"],
        "best_fitness": None
        if not scored
        else max(float(v["fitness"]) for v in scored),
    }


def _after_publishing(
    run: store.RunRow, payload: dict[str, Any], db_path: str | None
) -> None:
    """Tells everyone the report exists: the reader, and the mail queue.

    After the save, never before, so neither can announce a report that
    was not written.
    """
    from app.report_notify import _enqueue_completion_notification

    # The completion opt-in lives in the run config, so it applies to
    # both kinds of run; without this a discovery run is the one kind
    # that asks to be told and never is.
    _enqueue_completion_notification(
        run.id, run.research_goal, payload["report_id"], db_path=db_path
    )
    store.append_event(
        run.id,
        "report",
        {
            "variant_count": payload["variant_count"],
            "best_fitness": payload["best_fitness"],
            "niches_occupied": payload["niches_occupied"],
        },
        db_path=db_path,
    )


def publish(
    run_id: str,
    variants: list[dict[str, Any]],
    coverage: tuple[int, float],
    db_path: str | None = None,
) -> None:
    """Writes the run's report, best effort.

    Never raises. This runs at the very end of a discovery run, after
    every variant is already durable, so a formatting bug here must not
    turn a finished run into a failed task that retries the whole
    aggregate -- the search is done either way. The event and mail
    writes sit inside the same guard, or a full volume would raise past
    a report that was already saved and append another on every retry.
    """
    run = store.get_run(run_id, db_path=db_path)
    if run is None:
        return
    try:
        payload = build_payload(run, variants, coverage)
        saved = store.save_report(
            run_id,
            payload,
            build_markdown(run, variants, coverage),
            db_path=db_path,
        )
        _after_publishing(run, {**payload, "report_id": saved["id"]}, db_path)
    except Exception:
        logger.exception("Could not publish the report for run %s", run_id)
