# Evaluations

Reproducible evaluation harness for the parity work (PLAN.md Milestones 0, 5,
6, 8). Everything here runs **offline** (no LLM, no network) unless a runner
explicitly says otherwise; machine-readable results are written under
`results/`.

## Layout

- `parity_check.py` — the parity-ledger CI gate (fails if a `verified` row in
  `docs/PARITY.md` cites no test/eval evidence).
- `citation_eval.py` — claim/entailment metrics over
  `datasets/citation_entailment_v1.json` (precision/recall per label,
  contradiction recall, abstention).
- `safety_eval.py` — per-hypothesis safety false-positive / false-negative
  rates over `datasets/hypothesis_safety_adversarial_v1.json`.
- `metrics.py` — pure hypothesis-quality metrics (diversity;
  generation-vs-evolution yield/diversity). Does **not** use the engine's own
  Elo as ground truth.
- `expert_review.py` — the blinded expert-review export/import schema
  (novelty/plausibility/impact/preference), validated round-trip.
- `scaling_eval.py` — computes budget-ordered best-Elo (internal signal),
  blinded top-10 expert quality, diversity, verified-claim ratio, cost, and
  latency; also aggregates paired feature-ablation arms without treating Elo
  as quality ground truth.
- `release_gate.py` — fail-closed scientific publication readiness over claim,
  safety, and provenance artifacts.
- `smoke.py` — the offline smoke suite with documented regression tolerances.
- `datasets/` — versioned, synthetic, legally shareable labeled sets.
- `results/` — dated machine-readable result artifacts.
- `tests/` — unit tests for every runner.

## Commands

```bash
# From the repo root, using the shared venv python:
python -m evaluations.parity_check          # ledger gate
python -m evaluations.smoke                 # offline smoke (safety + citation)
python -m evaluations.citation_eval         # writes results/citation-entailment-<date>.json
python -m evaluations.safety_eval           # writes results/hypothesis-safety-<date>.json
python -m evaluations.scaling_eval path/to/controlled-runs.json
python -m pytest evaluations/tests -q       # harness unit tests

# Or via make:
make parity        # parity gate + harness tests
make eval-smoke    # offline smoke suite
```

## External gaps (not reproducible here)

Per PLAN.md, these need unavailable data / credentials / expert panels / wet
labs and are recorded honestly rather than fabricated:

- **Elo-vs-known-answer calibration** and **test-time-compute scaling curves**
  need an appropriately licensed question set (e.g. GPQA) and provider
  credentials. The tractable offline metrics (`metrics.py`) are provided; the
  credentialed curves are external.
- **Expert ratings** — the schema (`expert_review.py`) is here; the actual
  ratings require a recruited expert panel (external).
- **Google's private 1,200-goal safety benchmark** and **203-goal scaling
  corpus** are request-only and not reproduced.
- **Wet-lab validation** (AML / fibrosis / AMR) is out of scope.

Each runner records its own `external_gap` in its result artifact.
