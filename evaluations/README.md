# Evaluations

Reproducible evaluation harness. Everything runs **offline** (no model, no
network) unless a runner says otherwise. Runners write dated JSON artifacts to
`evaluations/results/`, which is created on demand and not tracked.

## Layout

- `_artifacts.py` — result writer. It stamps every artifact with a
  `provenance` block: source commit, branch and dirty state, Python and
  platform, a digest of the engine's prompt templates, and whatever the
  runner knows about the model, seed and cost. A result found later then
  carries what produced it.
- `citation_eval.py` — claim-entailment metrics (precision and recall per
  label, contradiction recall, abstention) over
  `datasets/citation_entailment_v1.json`. `--challenge` scores the
  adversarial `datasets/citation_entailment_challenge_v1.json` panel; with
  `--llm` it exits non-zero below the production gates (contradiction recall
  ≥ 0.80, accuracy ≥ 0.75). See [Citation panels](#citation-panels).
- `safety_eval.py` — per-hypothesis false-negative and false-positive rates
  for the deterministic reviewer (`co_scientist.domains.safety.rules.review_hypothesis_safety`),
  never the semantic escalation. See [Safety splits](#safety-splits).
- `claim_support_eval.py` — unsupported-claim rate over the verdicts a run
  already recorded. It never re-judges them: a second lexical opinion inside
  an eval is how a metric comes to disagree with the product (the Jaccard
  entry in [operations](../docs/OPERATIONS.md)). It reports the rate over
  claims and over ideas with nothing behind them, since a retrieval change
  can move one without the other. Offline, the deterministic backend answers
  every assessment the same way, so offline artifacts carry an
  `offline_disclaimer`: they prove the wiring, not quality.
- `citation_usefulness_eval.py` — does a retrieved span answer the question
  the search was serving? Unlike entailment, this separates a span that is on
  topic from one that answers the question. It scores
  `datasets/citation_usefulness_v1.json`. The default lexical judge is a floor
  (about 0.38 by construction); `--llm` scores a real model. The product does
  not judge its own retrievals this way, so the judge here is the eval's own.
- `decision_bakeoff.py`, `decision_cases.py` — the manual decision-model
  comparison; see [Decision bake-off](#decision-bake-off).
- `_run_driver.py` — plumbing for `claim_support_eval.py --live`. It creates a
  run through `co_scientist.platform.db.runs`, enqueues it with
  `orchestration.task_worker`, drains the worker pool and reads back the
  artifacts.
- `_live_config.py` — sets the environment for live runs before any app
  import: an explicit `openrouter/` model for every role, free models
  required, dotenv off, and every other `*_API_KEY` removed.
- `_usage_evidence.py` — summarizes per-call model, token and price evidence.
  Missing telemetry proves neither free execution nor absent inference.
- `_identity.py` — run and panel controls, policy snapshots and provenance
  checks.
- `smoke.py` — the offline smoke suite with its regression tolerances.
- `datasets/` — synthetic, legally shareable labeled sets.
- `tests/` — unit tests for the runners plus the import-contract ratchet.

## Commands

From the repository root, after `make setup`:

```bash
make test-evaluations                                   # harness tests
make eval-smoke                                         # offline smoke suite

.venv/bin/python -m evaluations.citation_eval                     # v1 panel, lexical assessor
.venv/bin/python -m evaluations.citation_eval --challenge --llm   # challenge panel, gated
.venv/bin/python -m evaluations.safety_eval                       # both safety arms
.venv/bin/python -m evaluations.claim_support_eval                # offline wiring check
.venv/bin/python -m evaluations.claim_support_eval --run <id>     # score a stored run
.venv/bin/python -m evaluations.citation_usefulness_eval [--llm --model openrouter/...]
```

Live panels (`--llm`, `--live`) configure the environment before importing
model code, so run each in a fresh process. Set an explicit OpenRouter
`MODEL_NAME` (or `--model` for citation usefulness) and `OPENROUTER_API_KEY`.
Every role is pinned to that model and transport admission checks that its
current price is zero; no paid or default model is chosen implicitly. A panel
score alone is not evidence of scientific quality.

## Citation panels

- **`citation_entailment_v1`** (20 items) — the offline regression panel. The
  lexical assessor handles it, and `smoke.py` gates it at contradiction
  recall ≥ 0.80.
- **`citation_entailment_challenge_v1`** (30 items) — the production-gate
  panel. Passages share the claim's vocabulary but must be rejected or
  inverted by a semantic reader: numeric and direction conflicts without
  negation, species and model mismatches, temporal mismatches, passages that
  only mention the topic, retracted sources, and low-overlap paraphrase.

| Assessor | Panel | n | Accuracy | Contradiction recall | Gates |
|---|---|---|---|---|---|
| lexical | v1 | 20 | 1.00 | 1.00 | pass |
| lexical | challenge | 30 | 0.17 | 0.00 | fail, as intended |

The lexical assessor's collapse on the challenge panel is the point: token
overlap is a retrieval feature, not proof, so it is only an offline fallback.
Re-run the semantic path with `--challenge --llm` on the current free route
before quoting a live number. The gates are this project's own; Google's
production thresholds are not published, and the panel is synthetic, so a
human-audited sample and calibrated thresholds remain open.

## Safety splits

Each safety item carries a `difficulty`. `easy` is the literal-trigger floor
the classifier was written against; `smoke.py` gates it at zero false
negatives. `hard` is adversarial: paraphrase and synonym evasion, padding past
the regex window, a word-boundary spacing trick, vocabulary the classifier has
no pattern for (nuclear, explosive), and legitimate research that uses a
trigger phrase ("mass casualty" disaster response, "nerve agent" detection
assays). The hard split is measured, never gated.

The runner reports two arms, because the shipped layer is two layers:

- **Floor** — the regex alone. This is also what ships whenever the
  contextual assessor cannot give a clean allow: disabled, offline,
  uncredentialed or erroring. A held verdict then stays held.
- **Permissive ceiling** — the same measurement with an assessor that clears
  every hold put to it, whether weak, captured or persuaded by the text. The
  eligibility gate is the real one, so this arm clears only what the shipped
  code would ask an assessor about.

| Arm | Split | n | False-negative rate | False-positive rate |
|---|---|---|---|---|
| floor | easy | 31 | 0.00 | 0.00 |
| floor | hard | 18 | 0.333 | 0.833 |
| ceiling | easy | 31 | 0.143 | 0.00 |
| ceiling | hard | 18 | 0.333 | 0.00 |

Read the arms together. At the floor the layer withholds 5 of 6 legitimate
near-boundary items; an assessor resolving holds takes that to zero. The worst
case costs one easy adversarial item whose danger is a genuine context call
("test the compound on patients without informed consent"). Acquisition,
yield improvement or a synthesis procedure named against a weapon class are
deterministic blocks no assessor can reach, so the ceiling's hard-split
false-negative rate does not move. The remaining hard misses are paraphrases
with no trigger token, which neither layer closes. Neither arm measures a real
assessor's judgment; together they bound it in each direction.

## Quality benchmark

The manual `Benchmark` workflow (`.github/workflows/benchmark.yml`) runs
`claim_support_eval.py --live --tier express|standard` on a fixed goal with
the free default route. It reports the unsupported-claim rate with its claim
count and a 95% Wilson interval, the unverified-idea rate, requests and wall
time, and keeps the run database as an artifact. The run stops after 120
minutes (Express) or 240 (Standard), and the job fails when no rate was
written. It needs the `OPENROUTER_API_KEY` repository secret; its MCP server
also needs `OPENALEX_API_KEY` and `TAVILY_API_KEY`, without which there is no
web search and literature retrieval is keyless.

- **Noise floor.** Express runs on unchanged code have ranged from 0.65 to 1.0
  unsupported-claim rate at about 25 claims. Claims cluster within ideas, so
  the run-to-run spread is wider than the interval. Read a change only when
  its rate falls outside both runs' intervals. Revert such a change unless it
  is a large speed gain with a small, stated loss.
- **Ration live runs.** OpenRouter's free models allow 20 requests a minute
  and 1,000 a day for the whole account. Do not benchmark changes that cannot
  alter model output (caching, backend, frontend, CI); measure those offline.
  Batch prompt, reasoning-budget and retry changes and check each batch with
  one Express run.
- **Standard runs need a higher ceiling.** Admission reserves the full output
  cap per call, roughly four times what a run uses, so a Standard run stops at
  the default `PROVIDER_CLIENT_TOKENS_PER_DAY` (16M).
- Extended and Ultra get no live runs; check their call envelopes offline.

## Decision bake-off

The manual `Decision bake-off` workflow compares Liquid `d1:free` with the
current free LLM at four call sites (`literature_relevance`,
`ranking_pairwise`, `proximity`, `semantic_safety`) on inputs recorded by
earlier `Benchmark` runs. Pass their run IDs as `source_runs`. It needs the
`LIQUID_API_KEY` and `OPENROUTER_API_KEY` secrets, and `decision_bakeoff.py`
refuses to run outside a manual Actions dispatch. Method and adoption rules:
[decision model](../docs/decision-model.md).

## External gaps

These need data, credentials, expert panels or wet labs that are not
available here:

- Google's private 1,200-goal safety benchmark and 203-goal scaling corpus are
  request-only.
- Wet-lab validation (AML, liver fibrosis, antimicrobial resistance) is out of
  scope.

`citation_eval.py` and `safety_eval.py` record their gap in each artifact's
`external_gap` field.
