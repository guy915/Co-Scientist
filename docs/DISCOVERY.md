# Computational Discovery

A discovery run evolves a *program* against a measured objective, where a
hypothesis run evolves ideas against reviews. It reuses everything that
already works — the durable task queue, the safety gate, the run
lifecycle — and adds three things: a confined place to run code, a
proposal agent that writes patches, and a cascade that turns a program
into a number.

## The loop

```
seed program ──► evaluate ──► aggregate ──► propose ──► evaluate ──► aggregate ──► …
```

Three durable task types (`app/app/engine_tasks_variants.py`):

| Task | What it does |
|---|---|
| `engine.fanout.variant.propose` | Derives one child from one parent, or records the seed |
| `engine.fanout.variant.evaluate` | Runs the child's cascade in its own sandbox and scores it |
| `engine.fanout.variant.aggregate` | Reads the generation, picks parents, enqueues the next |

A generation is enqueued whole, inside one transaction
(`engine_tasks_variants_schedule.enqueue_generation`) — a half-enqueued
round leaves an aggregate waiting on evaluations nobody scheduled.

## Configuring a run

The `discovery` key in a run's config is what makes it a discovery run.
Its presence is the only flag; there is no second field that could
disagree with it.

```json
{
  "discovery": {
    "objectives": [
      {"metric": "accuracy", "direction": "maximize"},
      {"metric": "latency_seconds", "direction": "minimize"}
    ],
    "stages": [
      {"name": "smoke", "argv": ["python", "main.py", "--smoke"],
       "timeout_seconds": 30, "min_fitness": 0.1},
      {"name": "full", "argv": ["python", "main.py"], "timeout_seconds": 600}
    ],
    "descriptors": [
      {"feature": "operator"},
      {"feature": "max_depth"},
      {"feature": "imports"}
    ],
    "grid": {"strategy": "cvt", "cells": 12},
    "metrics_path": "metrics.json",
    "seed_source": {"main.py": "..."},
    "max_generations": 8,
    "children_per_generation": 4
  }
}
```

Stages run cheapest-first and each may gate the next with `min_fitness`.
The program reports by writing `metrics_path` as a flat JSON object; each
objective names one of its keys. A single `objective` object is still
accepted in place of the list.

**A malformed `discovery` block fails the run at bootstrap**
(`app/app/discovery_spec.py`). This is deliberate and is the one place
the code refuses rather than defaults: falling back to an empty cascade
would give a run that executes normally and scores every variant
identically, which reads as "the model cannot write working code" rather
than as "the run was misconfigured". The *budgets* do default, because
unlike the cascade they have an obviously correct fallback.

## Several objectives

A run may optimize more than one thing. The objectives are kept several
rather than collapsed into one score, because the obvious collapse -- a
weighted sum -- is worse than it looks: the weights multiply raw values
on unrelated scales, so an objective in seconds and one in [0, 1] give a
total the seconds term decides entirely, whatever weights were written.
Nothing errors; the second objective just stops mattering.

So there are two mechanisms, and neither does cross-scale arithmetic:

- **`fitness` is the first objective**, sign-corrected. It is what the
  cascade thresholds compare against, what orders the variant list, and
  what the breakthrough plot draws. The first objective is the primary by
  declaration order.
- **Every other objective acts through Pareto dominance**
  (`code_eval/pareto.py`). One variant dominates another when it is at
  least as good on every objective and strictly better on one. The
  variants nothing dominates are the **front** -- the set of real trades
  -- and they are preserved as parents and flagged in the API, so a
  variant that wins only on the second objective is never bred out by
  variants that win on the first.

A missing objective value is not a bad one. A variant that reported
accuracy but no latency has no position on the latency axis, so it is
skipped in that comparison rather than treated as the worst possible
value -- which would let anything dominate it and drop it silently.

The proposal prompt names **every** objective, not just the primary. A
second objective the model never hears about is one no proposal ever
tries to improve, however well the archive preserves it.

## The diversity archive

Selecting parents by score alone is the obvious strategy and a
consistently bad one. The best few programs in a generation are usually
near-copies, so breeding from them produces more of the same, and the
search settles into the first decent basin and polishes it for the rest
of its budget. Nothing looks wrong while this happens -- the score
improves, slowly, forever.

`agents/code_evolve/archive.py` keeps **the best of each kind** instead.
Every variant is assigned a niche from its behaviour, the archive holds
one elite per occupied niche, and parents are drawn from the archive.

Measured on a landscape with an easy approach that saturates at 5.0 and
a harder one that reaches 16.0 (`test_code_archive_basins.py`, 60 seeds,
identical budget and mutation operator for both):

| Selection | Mean best | Escaped the decoy |
|---|---|---|
| Score-only top-k | 5.00 | 0 / 60 |
| Diversity archive | ~8.9 | most runs |

Score-only selection ends at *exactly* the easy approach's ceiling in
every run. Note what that is not: both strategies generate the harder
approach about equally often -- the `explore` operator sees to that. The
difference is that top-k discards it immediately for being behind, and
the archive keeps investing in it while it catches up.

**Cells** come from `descriptors` plus a `grid` strategy.

A descriptor is a `feature` and, for the `fixed` strategy, ascending
`bins`. Features are `operator`, `imports`, `max_depth`, `branch_count`,
`call_diversity`, `source_lines`, `source_bytes`, or `metric:<key>` for
anything the program reports. Structure is measured from the AST when
the program parses as Python and from indentation and token shape
otherwise, so a run in another language still gets nesting, branching
and dependencies -- just more crudely.

Three strategies, because they fail differently:

| Strategy | Cells from | Fails when |
|---|---|---|
| `fixed` | Declared bin edges | The author was guessing the scale |
| `adaptive` | Per-axis quantiles of observed values | A cell's meaning drifts as the run moves |
| `cvt` (default) | k-means over the whole behaviour vector | — bounded to `cells` by construction |

**An axis must describe a variant's kind, not its progress.** This is
the rule that matters most, and it is the opposite of the intuition that
more axes are safer. A fixed grid whose edges are too coarse quietly
collapses a useless axis into one bin -- a crude accident that happens
to protect the run. `adaptive` and `cvt` have no such accident: they
subdivide whatever axis they are given. An axis that mostly tracks how
*refined* a variant is therefore turns the archive into "keep every
refinement level of every approach", and the uniform half of selection
spends its budget re-drawing one approach at different maturities.

Measured on the decoy landscape (200 seeds, identical budget and
mutation operator, `test_code_archive_basins.py`):

| Default axes | CVT mean best | Escaped the decoy |
|---|---|---|
| kind only (`operator`, `max_depth`, `imports`) | 7.84 | 144 / 200 |
| the same plus `source_lines` | 5.71 | 38 / 200 |

That is why program length is **not** a default axis despite being the
cheapest one available. Nesting and dependencies are: a variant does not
become deeper or import more simply by being polished. Note also what
the same measurement showed about strategies -- with the right axes,
`fixed`, `adaptive` and `cvt` all scored identically (7.84). The
strategy is not what rescues a badly chosen axis; nothing is.

**A cell keeps a front, not an elite.** Reducing a cell to its single
best variant re-introduces, inside the cell, exactly the collapse the
archive exists to prevent: two genuinely different trades that happen to
share a niche compete for one slot, and whichever loses on the primary
objective is discarded even though nothing dominates it. So each cell
holds its own non-dominated set (this is MOME), capped at
`DEFAULT_CELL_CAPACITY`, and an overflowing cell drops its most
*crowded* member rather than its lowest-scoring one -- dropping by score
would again delete the trade.

Selection draws a **cell** first and a member within it second. Drawing
from all members at once would hand a cell holding three trades three
times the attention of a cell holding one, which is population size
deciding selection -- the exact bias the archive removes.

**Behaviour is stored; the cell is not.** Under an adaptive or CVT grid
a variant's cell depends on every other variant, so a cell id written at
evaluation time is wrong by the next generation. The raw measurement is
persisted and the cell derived on read, which keeps one source of truth
rather than two that drift apart silently. Pareto membership is derived
for the same reason -- one new variant can take an older one off the
front.

## Proposing a variant

`engine/src/co_scientist/agents/code_evolve/` asks the model for a **V4A
patch**, not a rewritten program. Two consequences worth knowing:

- **Output scales with the edit, not the program.** A schema that echoed
  the program back would make a large codebase overrun the token budget
  and truncate identically on every retry — the failure that silently
  stopped proximity clustering. See the note in
  `schemas/code_evolution.py`.
- **A patch whose context does not match is a rejected child, not a
  retry.** The mismatch means the edit was written against something
  other than the program shown, and re-asking reproduces it. The task
  reports the rejection and the generation continues.

The move is assigned before the edit is requested
(`code_evolve/operators.py`). Left unprompted, a model asked to "improve
this" tunes constants forever. A parent that produced no usable score
forces `repair`, because every other move is wasted on a program that
does not run — which is what makes keeping a failure's stderr worth the
storage.

## Evaluating a variant

`engine/src/co_scientist/code_eval/` runs the cascade and **never
raises**: a crash, a timeout, an unparseable metrics file and a program
that never wrote one are four results, told apart by `status`. This is
not politeness. Only `UnsupportedTaskError` is a permanent task failure
here, so an exception would re-run identical failing code through the
whole retry budget and then strand the run — and a variant that crashes
is the expected case, not the exceptional one.

Each variant gets **its own workspace** (`open_variant_workspace`).
Variants are proposed and evaluated concurrently; sharing one directory
would have two evaluations each running part of the other's code, and
both would return a plausible number attributed to the wrong variant.

Confinement comes from `engine/src/co_scientist/sandbox/` and fails
closed: on a platform with no backend the tools are withheld from the
model rather than offered and run unconfined. See `docs/DEPLOYMENT.md`.

## Reading a run

`GET /api/runs/{id}/variants` lists every attempt in ordinal order;
`/variants/{variant_id}` adds metrics, artifacts and full source. The
**Variants** tab renders both, and appears only for discovery runs.

A multi-objective run also gets a trade-off scatter -- objective one
against objective two, with the front highlighted -- because plotting
only the primary score would show a ranking that does not exist.

Four rules the surface keeps, each of which is easy to get wrong:

- **Failed attempts keep their number.** The ordinal is dense and
  includes everything. Skipping dead attempts makes the breakthrough
  plot read as faster progress than actually happened.
- **An unscored variant shows a dash, never a zero.** No position in the
  ordering is a different fact from a score of zero.
- **The best-so-far line is a step, not an interpolation.** The record
  holds flat until something beats it; drawing a slope between records
  invents steady progress.
- **"Best trade-off" is only shown when it is not already "best so far".**
  With one objective the front *is* the best, and two badges for one fact
  reads as two findings.
- **Cell count is reported with its evenness.** Forty variants in one
  cell and one in each of five others has reached six cells and explored
  almost nothing, so a lopsided run is told it piled into one.

## Known limits

- **Behaviour is measured, not learned.** The features are hand-written
  (nesting, branching, dependencies, size, reported metrics). A learned
  descriptor -- an embedding of the program, say -- would capture
  similarity these miss, at the cost of an axis nobody can read.
- **Structural features are shallow.** Two programs with the same
  nesting depth, branch count and dependencies are one cell even if they
  implement different algorithms. `imports` catches the common case (a
  numpy rewrite versus a tuned loop) and nothing catches the rest.
- **CVT cells move as the run grows.** Adding variants re-clusters, so a
  cell is not a stable identity across time and "cells occupied" is a
  snapshot rather than a monotonic count.
- A discovery run publishes no report; it ends when its generation
  budget runs out, and the aggregate marks it completed.
