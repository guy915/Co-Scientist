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
  against (gated at 0 false negatives by `smoke.py`); `hard` is
  genuinely adversarial -- paraphrase/synonym evasion, character-gap
  padding past the regex's window, a word-boundary spacing trick, and
  vocabulary the classifier has no pattern for at all (nuclear, explosive),
  plus legitimate research that happens to use a literal trigger phrase
  ("mass casualty" disaster response, "nerve agent" detection assays,
  "bioweapon" treaty-compliance history). The `hard` split is measured and
  reported, never gated to pass -- see the eval's own module docstring.
- `retrieval_replay_eval.py` — replay reproducibility: can a run's
  retrieval be reconstructed from its record alone? Re-derives each
  `retrieval_calls` row's content id from the fields the row carries,
  checks that every evidence row naming a search resolves to one, and
  checks that everything a call admitted or dropped appears in the hits it
  recorded. Offline by default, persisting a synthetic ledger through the
  real writer (`app.research_provenance` → `store.add_retrieval_calls`) --
  a driven offline run does no research at all, so scoring one would
  measure an empty set and report a perfect score. `--run <id>` scores a
  real persisted run, which is the mode that says anything about
  production.
- `claim_support_eval.py` — unsupported-claim rate over the verdicts a run
  already recorded, never re-judged here (a second lexical opinion inside
  an eval is how a metric comes to disagree with the product; see the
  Jaccard entry in the root AGENTS.md). Reports two rates: over claims,
  and over ideas with nothing behind them, since a retrieval change can
  move one without the other. **Offline by default proves the wiring, not
  quality** -- the deterministic backend answers every assessment the same
  canned way whatever was retrieved, and offline artifacts say so in an
  `offline_disclaimer`. `--run <id>` scores a persisted run; `--live`
  drives one against a real provider.
- `citation_usefulness_eval.py` — does a retrieved span answer *the
  question the search was serving*? Distinct from `citation_eval.py`,
  which asks whether a span entails a claim: the two come apart exactly
  where a research loop earns its cost, on a span that is squarely
  on-topic and answers a different question. Scores
  `datasets/citation_usefulness_v1.json`; the default deterministic judge
  is lexical coverage and is kept as a floor (it scores ~0.38 on the
  panel, by construction), `--llm` scores a real model. Note there is no
  production assessor to score here -- the system does not yet judge its
  own retrievals this way, so this eval's judge is its own.
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
- `golden_run.py` — a deliberate exception to "runs offline": drives one small
  biomedical run through the real durable path (`store.create_run` ->
  `task_worker` -> `engine_tasks` -> engine -> MCP -> drain -> report) against
  a **local** MCP server with `indra_cancer.yaml` and the semantic claim
  assessor, then asserts real (non-offline) evidence, nonempty support
  passages, and at least one authorized INDRA invocation. Needs a provider key
  and a running local MCP server; never in CI, never against production, fresh
  temp DB each time.
- `prod_smoke.py` — another deliberate exception to "runs offline": a
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
- `tests/` — unit tests for the runners, plus the repo-wide source gates
  (file length, function length, docs truth) that `make parity` runs alongside
  the ledger check.

## Commands

```bash
# From the repo root, using the shared venv python:
python -m evaluations.parity_check          # ledger gate
python -m evaluations.smoke                 # offline smoke (safety + citation)
python -m evaluations.citation_eval         # writes results/citation-entailment-deterministic-<date>.json
python -m evaluations.citation_eval --challenge --llm  # adversarial panel, semantic assessor, enforces gates
python -m evaluations.safety_eval           # writes results/hypothesis-safety-<date>.json
python -m evaluations.scaling_eval path/to/controlled-runs.json
python -m evaluations.scaling_budget_driver              # offline; writes results/scaling-budget-curve-<date>.json
python -m evaluations.scaling_budget_driver --live        # needs DEEPSEEK_API_KEY; real spend/time
python -m evaluations.ablation_driver                     # offline; writes results/ablation-sweep-<date>.json
python -m evaluations.ablation_driver --live               # needs DEEPSEEK_API_KEY + reachable MCP
python -m evaluations.elo_concordance_eval                 # offline stub; writes results/elo-concordance-<date>.json
python -m evaluations.elo_concordance_eval --llm            # needs DEEPSEEK_API_KEY; scores the real judge
python -m evaluations.golden_run            # LIVE; needs DEEPSEEK_API_KEY + a local MCP server
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

`safety_eval.py` scores the hypothesis-safety layer over `easy` (the
literal-trigger regression floor) and `hard` (genuinely adversarial
paraphrase/synonym/padding/spacing evasion, vocabulary the classifier has no
pattern for, and legitimate near-boundary research that happens to use a
trigger phrase) items, combined from the adversarial and controls datasets.

It reports **two arms**, because the shipped layer is two layers and neither
number alone describes it:

- **Floor** — the deterministic regex alone. This is also exactly what ships
  whenever the contextual assessor cannot run: disabled, offline-pinned,
  uncredentialed, erroring, or answering anything but a clean allow. Every one
  of those leaves a held verdict held.
- **Permissive-assessor ceiling** — the same measurement assuming an assessor
  that clears *every* hold put to it, whether because it is weak, captured, or
  talked into it by the text it is reading. The eligibility gate is the real
  one, so this arm can only clear what the shipped code would actually put to
  an assessor.

Latest recorded results (2026-08-07, `results/hypothesis-safety-2026-08-07.json`):

| Arm | Split | n | false-negative rate | false-positive rate |
|---|---|---|---|---|
| floor | easy | 31 | 0.00 | 0.00 |
| floor | hard | 18 | 0.333 | 0.833 |
| ceiling | easy | 31 | 0.143 | 0.00 |
| ceiling | hard | 18 | 0.333 | 0.00 |

Read them together. The false-positive problem is entirely a hold problem: at
the floor the layer wrongly withholds 5 of 6 legitimate near-boundary research
items, and an assessor resolving those holds takes that to zero. What it costs
in the worst case is the gap in the other column — one easy adversarial item
whose danger is a genuine context call ("test the compound on patients without
informed consent"). Constructions whose danger is *not* a context call —
acquisition, yield improvement, a synthesis procedure named against a weapon
class — are deterministic blocks no assessor can reach, which is why the
ceiling's hard-split false-negative rate does not move at all.

Neither arm measures a real assessor's judgment. That needs a provider and is
not something this offline harness claims. What it does claim is a bound in
each direction, which is what a reader needs to judge the trade.

The remaining hard-split false negatives are genuine paraphrase with no
literal trigger token, which neither layer closes today. See `J13` in
`docs/fidelity-audit/FINDINGS.md` for the finding this measured.

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
