# Evaluations

Reproducible evaluation harness for the parity work. Everything here runs **offline** (no LLM, no network) unless a runner
explicitly says otherwise; machine-readable results are written under
`results/`.

## Layout

- `_artifacts.py` — shared result-artifact writer. Every artifact any runner
  writes through it is stamped with a `provenance` block (source git
  commit/branch/dirty, python/platform environment, a digest over the
  engine's prompt templates, and whatever the runner knows about the model,
  seed, and cost of its own measurement) automatically, so a result found
  later carries what produced it rather than depending on memory.
- `parity_check.py` — the parity-ledger CI gate (fails if a `verified` row in
  `docs/PARITY.md` cites no test/eval evidence).
- `citation_eval.py` — claim/entailment metrics over
  `datasets/citation_entailment_v1.json` (precision/recall per label,
  contradiction recall, abstention). `--challenge` scores the larger
  adversarial `datasets/citation_entailment_challenge_v1.json` panel and
  enforces the documented production gates (contradiction recall ≥ 0.80,
  accuracy ≥ 0.75). Run the semantic path with `--llm`; the offline
  deterministic (lexical) assessor is expected to fail the challenge gates
  and is retained only as a fallback baseline. See "Citation evaluation
  panels" below.
- `safety_eval.py` — per-hypothesis safety false-positive / false-negative
  rates for the deterministic-regex reviewer layer
  (`co_scientist.safety.review_hypothesis_safety`; never the optional
  semantic/LLM escalation), over two datasets:
  `datasets/hypothesis_safety_adversarial_v1.json` (must-block items; every
  item's `should_block` is `true`) and
  `datasets/hypothesis_safety_controls_v1.json` (must-allow items; every
  item's `should_block` is `false`, including a broad domain-diverse sample,
  not just adversarial near-misses). Each item also carries a `difficulty`:
  `easy` is the literal-trigger regression floor the classifier was written
  against (gated at 0 false positives/negatives by `smoke.py`); `hard` is
  genuinely adversarial -- paraphrase/synonym evasion, character-gap
  padding past the regex's window, a word-boundary spacing trick, and
  vocabulary the classifier has no pattern for at all (nuclear, explosive),
  plus legitimate research that happens to use a literal trigger phrase
  ("mass casualty" disaster response, "nerve agent" detection assays,
  "bioweapon" treaty-compliance history). The `hard` split is measured and
  reported, never gated to pass -- see the eval's own module docstring.
- `metrics.py` — pure hypothesis-quality metrics (diversity;
  generation-vs-evolution yield/diversity). Does **not** use the engine's own
  Elo as ground truth.
- `_run_driver.py` — shared plumbing the two controlled-experiment drivers
  below use to persist a research goal through the real durable path
  (`store.create_run` -> `task_worker` -> `engine_tasks` -> engine -> drain
  -> report) and read back the resulting artifacts. Not a runner itself.
- `scaling_budget_driver.py` (L9) — drives the SAME research goal across the
  run tiers (express/standard/extended/ultra), differing only in tier, and
  feeds `scaling_eval.scaling_curve()`. **Offline by default (the only mode
  CI or the committed test exercises):** proves the driver's wiring and that
  each tier really does request more compute — it is NOT evidence that a
  real model's output quality scales with budget, since the offline backend
  answers every call identically regardless of tier; every offline artifact
  carries an explicit `offline_disclaimer` field saying so. `--live` (opt-in,
  never automatic, needs a provider key) runs the real four-tier sweep; no
  live sweep has been recorded yet.
- `ablation_driver.py` (L11) — drives paired arms (`baseline`,
  `no_web_search`, `no_literature_review`) across a small goal set through
  the real durable path and feeds `scaling_eval.ablation_summary()`. Only
  arms with an actual engine-level toggle are reachable this way; a
  meta-review or debate-strategy ablation is not (neither has a
  `GeneratorOptions` seam), and the driver records that as
  `unreachable_arms` rather than faking it. Offline by default — proves
  wiring only, since without a reachable MCP server every arm's literature
  review already degrades to LLM-only and the arms look near-identical
  regardless of the toggle. `--live` (opt-in) makes the toggles actually
  bite; no live sweep has been recorded yet.
- `elo_concordance_eval.py` (L8) — round-robins graded candidate answers
  through the exact production Elo update math and scores the result against
  known correctness with Kendall's tau-b. This is explicitly **not** GPQA:
  GPQA is a licensed, gated benchmark and is not reproduced here, so the
  harness runs against a small (8-item), hand-authored synthetic substitute
  instead, and every report says so via its `external_gap` field. Passing
  here shows only that the Elo mechanism recovers a coarse ordering over a
  handful of candidates per question — not concordance at GPQA difficulty.
  The default comparator is a deterministic stub (never calls a model);
  `--llm` (opt-in) scores the engine's real pairwise ranking judge instead;
  no `--llm` run has been recorded yet.
- `expert_review.py` — the blinded expert-review export/import schema
  (alignment/plausibility/novelty/testability/safety/impact/preference),
  validated round-trip, with per-axis confidence intervals and transparent
  pairwise inter-rater agreement for imported panels.
- `scaling_eval.py` — computes budget-ordered best-Elo (internal signal),
  blinded top-10 expert quality, diversity, verified-claim ratio, cost, and
  latency; also aggregates paired feature-ablation arms without treating Elo
  as quality ground truth.
- `release_gate.py` — fail-closed scientific publication readiness over claim,
  safety, and provenance artifacts.
- `smoke.py` — the offline smoke suite with documented regression tolerances.
- `prod_smoke.py` — the one deliberate exception to "runs offline": a
  **non-mutating** live smoke against a deployed Co-Scientist API (auth,
  CORS, ownership isolation, MCP/SMTP status disclosure, sanitized share
  404). GET/OPTIONS only, never wired into CI (hermetic-CI forbids live
  network -- see `docs/CI.md`); run it by hand before/after a release. Its
  own unit tests (`tests/test_prod_smoke.py`) exercise the check logic
  offline via `httpx.MockTransport`.
- `mcp_live_smoke.py` — another deliberate exception: a live contract +
  rate-limit smoke against the real PubMed (NCBI E-utilities), OpenAlex, and
  INDRA CoGex APIs `engine/mcp_server`'s tools call, checking the response
  shape those tools parse still holds and that a burst of calls degrades to
  a well-formed HTTP response rather than a crash. `engine/mcp_server`'s own
  suite fakes every HTTP client (correctly, for hermetic CI) and so cannot
  catch either. Also never wired into CI; its own unit tests
  (`tests/test_mcp_live_smoke.py`) exercise the check logic offline via a
  monkeypatched transport.
- `datasets/` — versioned, synthetic, legally shareable labeled sets.
- `results/` — dated machine-readable result artifacts.
- `tests/` — unit tests for every runner.

## Commands

```bash
# From the repo root, using the shared venv python:
python -m evaluations.parity_check          # ledger gate
python -m evaluations.smoke                 # offline smoke (safety + citation)
python -m evaluations.citation_eval         # writes results/citation-entailment-<date>.json
python -m evaluations.citation_eval --challenge --llm  # adversarial panel, semantic assessor, enforces gates
python -m evaluations.safety_eval           # writes results/hypothesis-safety-<date>.json
python -m evaluations.scaling_eval path/to/controlled-runs.json
python -m evaluations.scaling_budget_driver              # offline; writes results/scaling-budget-curve-<date>.json
python -m evaluations.scaling_budget_driver --live        # needs DEEPSEEK_API_KEY; real spend/time
python -m evaluations.ablation_driver                     # offline; writes results/ablation-sweep-<date>.json
python -m evaluations.ablation_driver --live               # needs DEEPSEEK_API_KEY + reachable MCP
python -m evaluations.elo_concordance_eval                 # offline stub; writes results/elo-concordance-<date>.json
python -m evaluations.elo_concordance_eval --llm            # needs DEEPSEEK_API_KEY; scores the real judge
python -m evaluations.prod_smoke            # LIVE, non-mutating; not in CI
python -m evaluations.prod_smoke --base-url https://api.ai-co-scientist.com
python -m evaluations.mcp_live_smoke        # LIVE, non-mutating; not in CI
python -m pytest evaluations/tests -q       # harness unit tests

# Or via make:
make parity        # parity gate + harness tests
make eval-smoke    # offline smoke suite
```

## Citation evaluation panels

Two panels exercise the claim-entailment assessor:

- **`citation_entailment_v1`** (20 items) — the offline regression panel. The
  deterministic (lexical) assessor handles it, so it gates the CI smoke suite
  (`smoke.py`) at contradiction recall ≥ 0.80.
- **`citation_entailment_challenge_v1`** (30 items) — an adversarial panel
  whose passages share the claim's vocabulary but must be rejected or inverted
  by a semantic reader: negation-free numeric/direction conflicts,
  species/model mismatches, temporal mismatches, topic-mention-only passages,
  retracted sources, and low-overlap paraphrase support/contradiction. It is
  the production-gate panel.

Latest recorded results (2026-07-14, `results/`):

| Assessor | Panel | n | accuracy | contradiction recall | gates |
|---|---|---|---|---|---|
| deterministic (lexical) | v1 | 20 | 1.00 | 1.00 | pass |
| deterministic (lexical) | challenge | 30 | 0.17 | 0.00 | **fail (expected)** |
| `llm:deepseek/deepseek-chat` | challenge | 30 | 0.90 | 1.00 | pass |

The lexical assessor collapsing to 0.00 contradiction recall on the challenge
panel is the point: token overlap is a retrieval feature, not proof, so it is
retained only as an offline fallback. The semantic assessor clears the gates.
Its two conservative misses (abstaining on genuine paraphrase support) are
safe; its one retracted-passage miss is scored in isolation here — the full
pipeline quarantines retracted sources upstream, before grounding.

DeepSeek is a **compatibility-mode** provider. These numbers are not a claim of
current Google-model (Gemini) parity, and the thresholds are the replica's own
reconstructed gates, not Google's undisclosed production thresholds. The panel
is synthetic and legally shareable; a human-audited representative sample and
calibrated thresholds remain an external gap.

## Safety evaluation splits

`safety_eval.py` scores the deterministic-regex hypothesis-safety layer only
(never the optional semantic/LLM escalation) over `easy` (the literal-trigger
regression floor) and `hard` (genuinely adversarial paraphrase/synonym/
padding/spacing evasion, vocabulary the classifier has no pattern for, and
legitimate near-boundary research that happens to use a trigger phrase)
items, combined from the adversarial and controls datasets.

Latest recorded results (2026-08-07, `results/hypothesis-safety-2026-08-07.json`):

| Split | n | false-negative rate | false-positive rate |
|---|---|---|---|
| easy | 31 | 0.00 | 0.00 |
| hard | 18 | 1.00 | 0.833 |

The `easy` split being clean is why this gap was invisible before the `hard`
split existed: every one of the 12 hard adversarial items evaded the
deterministic layer, and 5 of the 6 hard legitimate-research controls were
wrongly blocked. This is not a threshold-tuning problem — it is a
deterministic-regex layer being asked to do semantic work it structurally
cannot do. The `hard` split is measured and reported, never gated to pass.
See `J13` in `docs/fidelity-audit/FINDINGS.md` for the finding this measured.

## External gaps (not reproducible here)

These need unavailable data / credentials / expert panels / wet
labs and are recorded honestly rather than fabricated:

- **Elo-vs-known-answer calibration** (`elo_concordance_eval.py`,
  **test-time-compute scaling curves** (`scaling_budget_driver.py`), and
  **strategy/tool ablations** (`ablation_driver.py`) all now have runnable
  drivers in-tree, driving the real durable path end to end — that part is
  no longer a gap. What remains external in each is different, and stays
  three separate facts rather than one:
  - The drivers are **offline-proven only** so far (the only mode CI or the
    committed tests exercise): the deterministic offline LLM backend answers
    every call identically regardless of tier or arm, so an offline run
    demonstrates the harness's *wiring* — that tiers really do request more
    compute, that arms really do differ in config — and is explicitly NOT
    evidence that a real model's output quality scales with budget, that an
    ablated feature changes real output, or that a real judge's Elo
    concordance holds. Every offline artifact says so in its own
    `offline_disclaimer`/`external_gap` field.
  - Each driver also supports a `--live`/`--llm` opt-in path against a real
    provider (and, for the ablation driver, a reachable MCP server for the
    toggles to bite) — but **no live run has been recorded yet**; that
    credentialed measurement is still to be taken, not merely unbuilt.
  - The concordance harness's substitute dataset is a separate, permanent
    gap independent of live/offline: GPQA itself is a licensed, gated
    benchmark this repository cannot commit, so even a `--llm` run only
    measures concordance on an 8-item hand-authored synthetic set — never
    GPQA-difficulty concordance.
- **Expert ratings** — the schema (`expert_review.py`) is here; the actual
  ratings require a recruited expert panel (external).
- **Google's private 1,200-goal safety benchmark** and **203-goal scaling
  corpus** are request-only and not reproduced.
- **Wet-lab validation** (AML / fibrosis / AMR) is out of scope.

Each runner records its own `external_gap` in its result artifact.
