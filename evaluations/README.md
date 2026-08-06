# Evaluations

Reproducible evaluation harness for the parity work. Everything here runs **offline** (no LLM, no network) unless a runner
explicitly says otherwise; machine-readable results are written under
`results/`.

## Layout

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
  rates over `datasets/hypothesis_safety_adversarial_v1.json`.
- `metrics.py` — pure hypothesis-quality metrics (diversity;
  generation-vs-evolution yield/diversity). Does **not** use the engine's own
  Elo as ground truth.
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

## External gaps (not reproducible here)

These need unavailable data / credentials / expert panels / wet
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
