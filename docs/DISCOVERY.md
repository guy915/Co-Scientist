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
    "objective": {"metric": "score", "direction": "maximize"},
    "stages": [
      {"name": "smoke", "argv": ["python", "main.py", "--smoke"],
       "timeout_seconds": 30, "min_fitness": 0.1},
      {"name": "full", "argv": ["python", "main.py"], "timeout_seconds": 600}
    ],
    "metrics_path": "metrics.json",
    "seed_source": {"main.py": "..."},
    "max_generations": 8,
    "children_per_generation": 4,
    "parents_per_generation": 2
  }
}
```

Stages run cheapest-first and each may gate the next with `min_fitness`.
The program reports by writing `metrics_path` as a flat JSON object; the
objective names one of its keys.

**A malformed `discovery` block fails the run at bootstrap**
(`app/app/discovery_spec.py`). This is deliberate and is the one place
the code refuses rather than defaults: falling back to an empty cascade
would give a run that executes normally and scores every variant
identically, which reads as "the model cannot write working code" rather
than as "the run was misconfigured". The *budgets* do default, because
unlike the cascade they have an obviously correct fallback.

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

Three rules the surface keeps, each of which is easy to get wrong:

- **Failed attempts keep their number.** The ordinal is dense and
  includes everything. Skipping dead attempts makes the breakthrough
  plot read as faster progress than actually happened.
- **An unscored variant shows a dash, never a zero.** No position in the
  ordering is a different fact from a score of zero.
- **The best-so-far line is a step, not an interpolation.** The record
  holds flat until something beats it; drawing a slope between records
  invents steady progress.

## Known limits

- Parent selection is by score alone. There is no diversity archive, so
  a run can converge on one basin and stay there. The operator deck's
  `explore` move is the only counterweight.
- The objective is one metric. Multi-objective search would need the
  archive above, not just a second key.
- A discovery run publishes no report; it ends when its generation
  budget runs out, and the aggregate marks it completed.
