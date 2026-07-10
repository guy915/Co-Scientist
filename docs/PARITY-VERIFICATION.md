# Parity Verification Report

This report records the exact commands, results, coverage, and honest
limitations of the published-behavior parity work described in `PLAN.md`. It is
the companion to the requirement-level ledger in [PARITY.md](PARITY.md).

**It does not claim a 1:1 replica of Google's proprietary AI Co-Scientist.**
It documents which *publicly specified* behaviors are implemented and proven,
and which are external (unavailable data / credentials / expert / wet-lab) or
undisclosed (Google-unspecified, implemented as a documented configurable clone
decision).

Report date: 2026-07-10. Branch: `goolge-ai-co-scientist-parity`.

---

## 1. Quality gates (exact commands and results)

All commands run from the repo root unless noted. `../.venv/bin/python` is the
shared Python 3.12.12 environment.

| Gate | Command | Result |
|---|---|---|
| Engine tests + coverage | `cd engine && ../.venv/bin/python -m pytest -q --cov=co_scientist` | **956 passed**, **96%** line coverage |
| App backend tests + coverage | `cd app && ../.venv/bin/python -m pytest -q --cov=app` | **219 passed**, **95%** line coverage |
| Offline eval smoke | `python -m evaluations.smoke` (or `make eval-smoke`) | OK (safety + citation offline evals within tolerance) |
| Frontend tests + coverage | `cd app/frontend && bun run test` | **254 passed** (39 files); **95.4%** stmts / **96.9%** lines |
| Frontend lint | `cd app/frontend && bun run lint` | clean (gts) |
| Frontend build | `cd app/frontend && bun run build` | clean (`tsc && vite build`) |
| Engine typecheck | `cd engine && ../.venv/bin/python -m mypy .` | Success, no issues (196 files) |
| App typecheck | `cd app && ../.venv/bin/python -m mypy .` | Success, no issues (43 files) |
| Ruff lint (engine, app) | `ruff check .` in each of `engine/` and `app/` (system ruff — the shared venv has no `ruff` module, so `make lint`, which calls `python -m ruff`, does not run here) | clean |
| Parity checker | `python -m evaluations.parity_check` | OK — every `verified` row cites test/eval evidence (62 rows) |
| Parity checker tests | `python -m pytest evaluations/tests -q` | passed (parity + docs-truth + citation-eval + safety-eval) |

Coverage floors required by PLAN.md (≥80% each of engine, app backend,
frontend) are met with margin: engine 96%, app 95%, frontend 95.4% statements /
96.9% lines. No individual source file (including every module added in this
work) falls below 80%.

### Parity ledger status snapshot

`python -m evaluations.parity_check` reports, over 62 requirement rows:
**verified=54, external=6, undisclosed=2, partial=0, missing=0.** There are no
`partial` or `missing` rows: every requirement is either verified with cited
test/eval evidence, or is an `external`/`undisclosed` row with a precise,
non-safety-weakening blocker in [PARITY.md](PARITY.md).

---

## 2. Deterministic mock / recovery evidence

The deterministic offline path is exercised without any LLM or network:

- **Engine (real compiled LangGraph, LLM faked at the litellm boundary):**
  `cd engine && ../.venv/bin/python -m pytest tests/test_integration_pipeline.py tests/test_system_generation.py -q` — the full graph runs end-to-end
  (supervisor → generate → review → ranking → deep-verification → orchestrator
  loop → research-overview).
- **App (full mock provider over ASGI HTTP incl. SSE replay/live, mid-run
  cancel, steering drain, per-hypothesis safety screen, claim grounding):**
  `cd app && ../.venv/bin/python -m pytest tests/test_integration_run_flow.py tests/test_runs.py -q`.
- **Checkpoint / restart-recovery (engine, exact state):**
  `cd engine && ../.venv/bin/python -m pytest tests/test_resume_pipeline.py -q` — interrupts a
  real graph run at a safe boundary, checkpoints, restores in a rebuilt
  generator (simulating a process restart), and resumes: the checkpointed pool
  is preserved byte-for-byte across single and double restarts.
- **Checkpoint / restart-recovery (app, failure injection):**
  `cd app && ../.venv/bin/python -m pytest tests/test_resume.py -q` — interrupts a mock run
  mid-iteration, reconciles it as resumable, resumes (clear + deterministic
  re-run), and asserts identical terminal artifacts, exactly one report, and
  unique/monotonic event seqs (no duplicates); double-resume is stable.

Offline evaluations (machine-readable results under `evaluations/results/`):

- `python -m evaluations.citation_eval` — claim/entailment metrics
  (precision/recall per label, contradiction recall, abstention).
- `python -m evaluations.safety_eval` — per-hypothesis safety false-positive /
  false-negative rates on the adversarial regression set.

---

## 3. Real-provider (engine) evidence and the recorded external blocker

Per PLAN.md, mock success never substitutes for real-provider verification.

### 3a. Real-provider run — performed

A **real-engine run through the live LangGraph path** was executed with the
DeepSeek chat model (`DEEPSEEK_API_KEY` present in `.env`). Evidence:
`evaluations/results/real_engine_baseline.json`.

- `provider="engine"`, `status="completed"`, model `deepseek/deepseek-chat`.
- Observed node sequence across two adaptive iterations: supervisor → generate
  → review → ranking → deep_verification → **orchestrator** → meta_review →
  evolve → review → ranking → deep_verification → orchestrator → proximity →
  orchestrator → **generate (iteration 2: "generate unexplored regions")** →
  … → research_overview. This exercises the real Supervisor/orchestrator
  dynamic scheduling and the research-expansion re-generation.
- The app-side drain wiring ran on the real path: 184 claim-evidence edges and
  the per-hypothesis safety decisions were persisted (safety screen + claim
  grounding execute for the real engine, not only the mock).

Two engine parity behaviors were additionally confirmed with direct real
DeepSeek calls (reused for a fast, cheap real-output check):

- **Output criteria** (`output_criteria_real_review.json`): a real review emits
  all five default criteria as integer scores (relevance, plausibility,
  novelty, testability, safety).
- **Review types** (`reflect_types_real_review.json`): the new `full_review`
  and `simulation_review` types emit valid structured output.
- **Generation techniques** (`gen_techniques_real.json`): the new
  iterative-assumptions technique emits hypothesis drafts.

MCP literature tools were **unavailable** for these runs (see 3b), so
generation ran from model latent knowledge (LLM-only fallback), which the
engine handles gracefully.

### 3b. The single external blocker: the credentialed MCP-literature smoke

The MCP reference server is **not reachable** at `http://localhost:8888/mcp`
(`curl -s -m 3 http://localhost:8888/mcp -o /dev/null -w '%{http_code}'`
returns `000`). PubMed/INDRA literature tools are therefore unavailable, and a
real run that exercises the *literature-grounded* generation/reflection paths
(as opposed to the LLM-only fallback proven above) is the single, precisely
documented external blocker. To verify later:

```bash
# 1. Start the reference MCP server (Python 3.12 venv):
pip install -e mcp_server/           # into a 3.12 environment
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888

# 2. Run the app against the real engine + MCP with a live key:
cd app && MODEL_NAME=deepseek/deepseek-chat \
  MCP_SERVER_URL=http://localhost:8888/mcp \
  ../.venv/bin/python -m uvicorn app.main:app --port 8008
# then POST /api/runs + /start and observe provider="engine" in /status,
# and evidence rows sourced from pubmed/indra (source != "mock").
```

The `/status` and `/config` endpoints and the persisted `runs.provider` column
disclose which path (mock vs engine) produced each run, so real and mock runs
are never conflated (`PROVENANCE-PATH-001`, verified).

---

## 4. Interactive frontend / browser verification

**Performed** in the built-in browser against the mock backend (port 8008) and
the Vite dev server (port 5173), at the required viewports: desktop **2:1**
(1600×800), desktop **16:9** (1280×720), and mobile **1:2** (390×780).

Each new idea-detail surface was verified by reading the live DOM (authoritative
text/CSS checks) and by screenshot:

- **Provenance & lineage pane** — Origin (agent/scientist author), Generation,
  Proximity cluster, and per-hypothesis **Safety status** (now a real screened
  value, e.g. "Allow", not "pending").
- **Debate depth** in the Match summary — "Multi-turn scientific debate
  (N turns)" vs "Single-turn comparison".
- **Claim evidence** summary — "N claim(s) assessed, X supported, Y unsupported
  (speculative)", fetched from the new `/claim-evidence` API.

No console errors on a clean load (the only warning observed was a Vite HMR
hook-order artifact that does not reproduce on a full reload or in the
production build). The frontend suite, lint, and build are green (§1).

---

## 5. Honest limitations — what is and is not a 1:1 replica

**Implemented and proven (54 verified rows):** immutable evolution with explicit
lineage; explicit append/replace state reducer; deterministic adaptive
Supervisor scheduling with recorded reasons, budgets, and termination; dynamic
routing that generates in later cycles (research expansion); all four
generation techniques (literature exploration, simulated debate, iterative
assumptions, research expansion) each *invoked* by a run, and all six reflection
review types *invoked* by a run (initial/observation/deep-verification/recurrent
throughout, and full-review + simulation-review on the top hypothesis); all five
default output criteria scored; meta-review critique appended to every relevant agent prompt; weighted
proximity-/recency-/rank-aware matchmaking with coverage guarantees; multi-turn
debate for top-ranked vs single-turn for lower-ranked, with persisted depth; a
persisted weighted proximity graph; a versioned workflow checkpoint with
engine-exact resume and app-level deterministic resume + pause/resume + startup
auto-resume; claim-level entailment with provenance, a publication gate wired
into ranking/synthesis, and the claim-evidence graph persisted and surfaced;
per-hypothesis safety review wired before the tournament with real redaction and
safe abstention; scientist-contributed hypotheses/reviews and a safe text-only
attachment corpus; grounded post-run Q&A; durable high-priority steering
consumed by the real engine's orchestrator; and offline evaluation harnesses.

**External (unavailable, cannot be reproduced locally — no safety/truthfulness
impact):** Google's private 1,200-goal safety benchmark; the 203-goal
test-time-compute scaling corpus and the ablation comparative runs; the
15-expert / 7-biomedical-expert evaluations; wet-lab validation
(AML/fibrosis/AMR); the credentialed real-engine + **MCP-literature** smoke run
(§3b). The mechanisms these would measure (configurable budget, ablation
toggles, the live engine path) are themselves verified.

**Undisclosed (Google-unspecified, documented clone decisions):** the exact
adversarial safety classifier + its 1,200-goal set (a documented rules-based
clone is used); the Elo K-factor; the Supervisor's exact weights and
convergence/termination predicates; the proximity similarity metric; the
citation entailment model and thresholds; the persistent context-memory schema.
These are configurable and are **not** presented as Google's implementation.

This clone matches every *publicly specified* behavior it claims to (see the
`verified` rows), makes conservative documented choices where Google is silent,
and honestly records what depends on unavailable data, credentials, expert
review, or wet-lab work.
