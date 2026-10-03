# Parity Verification Report

This report records the exact commands, results, coverage, and honest
limitations of the published-behavior parity work. It is
the companion to the requirement-level ledger in [PARITY.md](PARITY.md).

**It does not claim a 1:1 replica of Google's proprietary AI Co-Scientist.**
It documents which *publicly specified* behaviors are implemented and proven,
and which are external (unavailable data / credentials / expert / wet-lab) or
undisclosed (Google-unspecified, implemented as a documented configurable clone
decision).

Report date: 2026-07-10. Branch: `goolge-ai-co-scientist-parity`.

> **Architecture note (added after a3729a0b, 2026-07-18).** This report
> predates the deletion of the app's mock workflow provider
> (`app/app/mock_workflow*.py`, deleted in commit `a3729a0b`). Every mention
> of "mock" below describes that now-retired code path as it existed on the
> report date; it is not a live alternative to the engine today. Every run
> now executes on the real LangGraph engine, and what this report calls the
> "mock" path is superseded by the engine pinned to the deterministic offline
> LLM backend (`engine/src/co_scientist/offline/llm.py`, fakes only
> `offline/`-prefixed models at the `litellm.acompletion` seam). The
> dated command results below are left as recorded, not re-run; current
> equivalent test files are noted inline where the architecture changed
> enough to matter.

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
| Parity checker | `python -m evaluations.parity_check` | OK — every `verified` row cites test/eval evidence; every `partial`/`missing` row names a residual gap/owner (64 rows) |
| Parity checker tests | `python -m pytest evaluations/tests -q` | passed (parity + docs-truth + citation-eval + safety-eval) |

Coverage floors (≥80% each of engine, app backend,
frontend) are met with margin: engine 96%, app 95%, frontend 95.4% statements /
96.9% lines. No individual source file (including every module added in this
work) falls below 80%.

### Parity ledger status snapshot

`python -m evaluations.parity_check` reports, over 115 requirement rows:
**verified=100, partial=4, divergent=8, missing=0, external=3, undisclosed=0.**
Each `verified` row cites test/eval evidence that exists on disk; each
`partial`/`missing`/`divergent` row names a concrete residual gap and owner (or,
for `divergent`, why the difference is accepted); each `external` row records a
precise, non-safety-weakening blocker in [PARITY.md](PARITY.md).

> **Reclassification (2026-09-10, `partial` → `divergent`).** Three rows
> moved from `partial` to `divergent` (partial 7 → 4, divergent 6 → 9). They
> were labeled `partial` only because the `divergent` status did not exist
> when they were written (added 2026-09-10, `16acaed0`); each is a settled
> accepted divergence, not pending work: **RESEARCH-CONTACTS-FIELDS-001** —
> the `expertise` field is kept and pinned by the owner's explicit "revisit
> only if a further exemplar surfaces that positively excludes it"; **SUP-STACKING-001**
> — the Supervisor's weighted agent "sampling" (Nature §3 text) names a
> behavior whose mechanism the paper never discloses, so matching it
> exactly is not attemptable from public sources; **HITL-MANUAL-HYP-001** —
> the two remaining admission windows are end-of-run edges that self-heal or
> sit outside admission itself, accepted rather than open. After this move,
> all four `partial` rows are the eval sweeps, and each is blocked on a
> credentialed comparison rather than on unbuilt code: `EVAL-ELO-CALIB-001`,
> `EVAL-SCALING-001` and `EVAL-ABLATION-001` still need a credentialed run
> plus Google's undisclosed reference corpora; `EVAL-RETRIEVAL-001` already
> carries credentialed numbers (2026-08-21) and is the nearest to closing,
> kept `partial` only because its numbers come from a single extended-tier
> run rather than the repeated comparison its residual describes. No verdict
> was reconciled away to shrink a count — each move is a truer label, checked
> against the row's own residual.

> **Reintroduction (2026-09-10, `divergent` → `verified`).** **GOAL-RESTATEMENT-001**
> moved from `divergent` to `verified` (divergent 9 → 8, verified 99 → 100)
> when the synthesized narrative goal restatement was reintroduced by owner
> decision. Unlike the form reversed 2026-09-04 (which differentiated two
> header goal lines), it now opens the report's `## Top hypotheses` section,
> reproducing the lead-in Google's `top-ranking-hypotheses` document opens
> with; it is generated once from the goal alone and persisted on the run
> (`runs.goal_restatement`). Pinned by a render test at the section boundary.
> The single-document divergence from Google's two documents stays owned by
> `REPORT-DOCUMENT-SPLIT-001`.

> **Update (post-a3729a0b, mock-workflow deletion).** `CKPT-FAILINJECT-001`
> moved from `verified` to `partial`: its app-level "two consecutive resume
> cycles" test (`test_double_resume_is_stable`) was dropped with the mock
> workflow and no replacement exists yet at the app layer (the engine-level
> double-restart test and an app-level single-restart test each still pass
> independently). Every other row that cited now-deleted `mock_workflow*.py`
> modules or `test_mock_workflow.py` was re-cited against its current
> equivalent rather than downgraded — see [PARITY.md](PARITY.md) for the
> updated evidence.

> **Reclassification (2026-07-12).** An end-to-end parity re-audit found that
> the earlier snapshot (54 verified, 0 partial) over-claimed: the checker
> only proves each `verified` row *names an existing test*, not that the test
> exercises the production contract or matches Google's behavior. Fourteen
> rows whose production path is not yet equivalent were moved to `partial`
> (real-engine safety/claim gating runs *after* the tournament; app resume
> re-runs rather than continues; steering/manual hypotheses/reviews are stored
> but not fed into a live run; review/generation techniques fire but are not
> grounded; `RANK-K-FACTOR`/`ORCH-WORKER-IFACE` are cross-layer or interface
> gaps). `PROX-GRAPH-001` was split into an engine build (`verified`, after a
> schema-contract fix) and app persistence (`PROX-GRAPH-APP-001`, `missing`).
> `TOOLS-CONFIG-001` was added (`verified`) for the newly wired tools-config
> forwarding. The remaining production-contract work is tracked as P0/P1 in
> the audit and in the row residuals.

> **Correction (2026-09-02).** `RUN-TIER-001` and `RUN-FOCUS-001` added
> (`verified`): FINDINGS `B1`/`B2` had recorded the product's four run tiers
> and four-way focus selector as clone-invented divergences from Google. The
> published product capture (`docs/CORPUS-EXTRACTION.md`'s App. C plan-config
> transcription) shows Google's own product offers the identical four tiers
> and four focus values, name for name, order for order — an exact match,
> not a divergence. `B1`/`B2` corrected in FINDINGS.md; row count 77->79.

> **Addition (2026-09-02).** `REVIEW-CRITIQUES-ROLLUP-001` added
> (`missing`): the published detailed hypothesis output ends in a
> per-idea "Critiques" section — a synthesized negative-critique rollup
> distinct from both the existing per-review list and the run-level
> meta-review critique. Recording only, not built; row count 79->80.

> **Addition (2026-09-02).** `SCORE-COMPOSITION-001` added (`partial`):
> Google's published score composition is printed as an explicit sum
> of four named terms (`score=novelty+details+usefulness+pairwise
> rank=11`); ours is the mean of the review rubric's own per-criterion
> scores. Recording the divergence only, no change proposed -- the
> published terms' individual definitions and weighting are not
> disclosed beyond the one printed total. Row count 80->81.

> **Addition (2026-09-02).** `RESEARCH-CONTACTS-FIELDS-001` added
> (`partial`): our `research_contacts[]` schema carries five fields
> against the narrowest published exemplar's three (name, relevance
> paragraph, and a Research Direction heading -- corpus `R12-16`
> undercounted its own cited exemplar). Only `expertise` is a genuinely
> unattested addition; `candidate_id` is unrendered anti-hallucination
> provenance and `research_direction` already matches the exemplar.
> Recording only. Row count 81->82.

> **Addition (2026-09-02).** `META-CRITIQUE-TAXONOMY-001` added
> (`partial`): the published meta-review critique (App. B, ALS example) is
> a 5-theme, 2-3-level-deep taxonomy; `recurring_themes[]` flattens it to
> `{theme, description, frequency}`, a deliberate accepted adaptation
> (commit `69d10874`) -- meta-review runs once per evolve iteration, and a
> nested taxonomy would multiply structured-output size on every one of
> those calls. Recording only, no schema change. Row count 83->84.
> (Closed 2026-09-09 — see the parity-closure note below.)

> **Reclassification (2026-09-04).** The owner reversed the R14-11
> two-document report split, by direct product-UI evidence (the published
> screen recordings show four run-detail sections and one Goal Report
> document, not five and two). Three rows moved from `verified` to
> `partial`, no row added or removed (row count unchanged at 100):
> `REPORT-DOCUMENT-SPLIT-001` (the split itself), `GOAL-RESTATEMENT-001`
> (the per-run LLM call that existed only to make the two documents' goal
> lines differ), and `RANKING-CRITERIA-TABLE-001` (the Criterion/Importance
> table that existed only as the second document's own exemplar --
> `EVALUATION-CRITERIA-001`'s prose form is now the report's only rendering
> of `critical_criteria`). See [PARITY.md](PARITY.md) for the updated rows.

> **Addition (2026-09-07, output-fidelity pass `bcf9628c`).** Six rows added
> for what the report now shows the reader: `REPORT-ALL-REVIEWS-001`
> (`verified`), `REPORT-DEEP-VERIFY-PROBES-001` (`verified`),
> `RANK-DEBATE-TRANSCRIPT-001` (`verified`),
> `OVERVIEW-SUBTOPIC-EXAMPLE-001` (`verified`),
> `OVERVIEW-AIMS-VOCABULARY-001` (`partial`, markdown only) and
> `OVERVIEW-DIRECTION-COUNT-001` (`partial`, four directions not six, sized
> from a token measurement). `REVIEW-SUMMARY-STRUCTURE-001` moved from
> `missing` to `partial`: the 8-part Reviews summary now exists, optional on
> `FULL_REVIEW_SCHEMA` and unmeasured in production. Row count 108->114.
> (Both `partial` rows closed 2026-09-09 — see the parity-closure note below.)


> **Parity closure (2026-09-09).** Twelve rows moved from `partial` to
> `verified` across three passes today; no row was added or removed, so the
> row count is unchanged at 115 and the snapshot above moves
> `verified=83, partial=27` to `verified=95, partial=15`. The first pass
> (below) moved six rows, `verified=83, partial=27` → `verified=89,
> partial=21`:
>
> - `PROX-PAIRWISE-001` (`24b93f16`) — similarity is now measured for every
>   pair of the surviving pool, not only within an LLM-declared cluster, at
>   zero extra provider calls; the 2026-09-07 floor-edge placeholder scheme
>   (`_FLOOR_SIMILARITY`, `floor_edges`, a four-neighbour cap) is gone and
>   storage is bounded by a similarity floor instead of by node degree.
> - `REFLECT-DEEPVERIFY-ORDER-001` (`49d91169`) — deep verification now runs
>   between the safety screen and the tournament, over every rankable
>   hypothesis, once ever per idea. The `KEEP-2` cost objection was
>   recomputed rather than overruled: the published listing verifies each
>   hypothesis once, not once per cycle, which is +4 calls on express and
>   +130 on ultra, each under 1.2% of the tier's ceiling.
> - `META-CRITIQUE-TAXONOMY-001` (`351d1f6a`) — `recurring_themes[]` now
>   nests `sub_themes[].points[]`, capped at the published artifact's own
>   maxima, and the report renders all three levels.
> - `REVIEW-SUMMARY-STRUCTURE-001` and `REVIEW-AXIS-STRUCTURE-001`
>   (`8c71f9ca`) — the 8-part `Reviews summary` is now required by
>   `FULL_REVIEW_SCHEMA` *and* named by the prompt that fills it, and each
>   published axis carries its own sub-structure. Both sit on the full
>   review alone, which runs once per mature hypothesis, so neither grows
>   `REVIEW_BATCH_SCHEMA`, whose cost multiplies by pool size; `REVIEW_SCHEMA`
>   and `REVIEW_BATCH_SCHEMA` are byte-identical either side of the change.
> - `OVERVIEW-DIRECTION-COUNT-001` (`6e77befa`) — the overview now names and
>   argues six directions in the draft and develops each to the exemplar's
>   depth on its own concurrent call, so six directions no longer have to
>   fit one 24000-token ceiling shared with the chain of thought.
>
> Two neighbouring `verified` rows were re-worded rather than re-statused:
> `REFLECT-TYPES-001` and `REPORT-DEEP-VERIFY-PROBES-001` described deep
> verification as a post-ranking top-K node, and `REPORT-ALL-REVIEWS-001`
> described the per-axis sub-schemas as deliberately unbuilt.
>
> A second pass the same day closed two more, `verified=89, partial=21` →
> `verified=91, partial=19`:
>
> - `CITE-META-001` (`fe1a1686`) — the `assess_resolvability`/`Resolver`
>   seam this row named now sits underneath the one live path production
>   runs (`app/app/citation_metadata.py`, called once per run from
>   `engine_adapter/drain_evidence_resolution.py::resolve_articles`) rather
>   than beside it; the parallel offline heuristic it used to stand next to
>   is deleted, and source type / publication date are now classified and
>   reported alongside resolvability and retraction.
> - `HITL-MANUAL-REVIEW-001` (`1a35bc8a`) — a scientist's review now merges
>   into engine state at every safe task boundary and is read by
>   `review_gate.derive_review_disposition` as the outermost layer over the
>   agents' own verdicts, reaching the ranking judge and evolution prompts
>   through `Hypothesis.review_summary()` — not written to a table nothing
>   read, as before.
>
> Two neighbouring rows converged their own residuals in the same pass but
> stay `partial`: `SUP-STACKING-001` (`b8e10b5e`) — the listing's other
> periodic branch, the research overview, now stacks with system feedback
> too, leaving only the two work branches (`rank`, `evolve`) unstacked, on
> topology rather than cost — and `HITL-MANUAL-HYP-001` (`1a35bc8a`) — a
> contributed hypothesis now merges into the *running* pool at the
> orchestrator's own commit boundary instead of only on restart, narrowing
> the residual to two windows outside that boundary.
>
> A third pass the same day closed four more, `verified=91, partial=19` →
> `verified=95, partial=15`:
>
> - `HITL-STEERING-001` (`66f332a7`) — only the orchestrator's own node
>   commit may acknowledge a steering message now; previously any node's
>   commit could, so a steer posted during e.g. proximity was acknowledged
>   by proximity and never reached a scheduling decision at all. The folded
>   preferences text now sources from every steering message the run has
>   ever queued, applied or not, so it survives the node after the ack
>   instead of going quiet, and a contribution posted with no remaining
>   orchestrator boundary self-heals once the run settles.
> - `CKPT-FAILINJECT-001` (`app/tests/test_resume_double_cycle.py`) — the
>   app-level two-consecutive-resume-cycle test this row's residual named as
>   missing since the mock-workflow deletion now exists, driving the durable
>   task queue one task at a time over the real HTTP endpoints and confirming
>   the pool captured before the second interruption is a subset of the
>   finally-published pool.
> - `OVERVIEW-NIH-001` (`415f6633`) — the research overview is no longer
>   terminal-only: `_check_research_overview_cadence` fires it periodically
>   on `extended`/`ultra`, tier-gated, on its own lean two-field schema
>   budgeted at a quarter of the terminal firing's tokens, and routes back to
>   the orchestrator loop point — the feedback edge into generation the
>   paper describes and this row's residual previously recorded as absent.
> - `OVERVIEW-AIMS-VOCABULARY-001` (`2c204e1d`) — the React overview tab now
>   mirrors the markdown export field for field (`Specific Aims N` as its own
>   heading, `Overarching goal:`/`Hypothesis:`/`Reasoning:` as labelled body
>   lines), closing the divergence the previous pass recorded as
>   markdown-only.
>
> `RESEARCH-CONTACTS-FIELDS-001` (`2c204e1d`) stays `partial` in this pass:
> `expertise` is now pinned as the one rendered field no published exemplar
> supports (`app/tests/test_report_contact_groups.py::test_expertise_is_the_one_field_no_exemplar_supports`),
> closing the missing-pin-test residual the row previously named, but the
> field itself is kept rather than removed, since no exemplar positively
> excludes it.
>
> **Parity closure (2026-09-10).** Four more rows moved from `partial` to
> `verified`, `verified=95, partial=15` → `verified=98, partial=12`; no row
> added or removed, still 115. Three were reframes on evidence, not new
> behaviour — the row text had claimed a gap the code did not have:
>
> - `EXEC-PATH-CHAIN-001` — per-hypothesis task chaining is delivered on the
>   canonical durable path (one leased task per hypothesis for every fan-out
>   family); the batch-node divergence the row described is confined to the
>   streaming LangGraph engine, which has no production caller since
>   `workflow.run_workflow` was removed. Reframed to `verified` with the
>   divergence scoped to the dev-only path; no code changed.
> - `SUP-SPLIT-001` (`1306f2d4`) — `01-supervisor.md` synthesizes the plan
>   once in `StartCoScientist` and only makes per-cycle decisions against it
>   in `DecideNextSteps`; ours matches (the compiled graph gives `supervisor`
>   a single inbound edge from START), so the "plan never revisited" reading
>   was not a divergence from Google at all. The sole remaining difference is
>   cosmetic node names. Pinned by graph-topology tests; no production code
>   changed.
> - `SCALE-TIER-001` — every mechanism the source names for "flexible compute
>   scaling" is within-run allocation (`SUP-DYNAMIC-001`, `SUP-STATS-001`,
>   `ORCH-DYNAMIC-ROUTE-001`), dynamic termination (`SUP-TERMINATE-001`), and
>   per-run envelope sizing (the tiers, `RUN-TIER-001`) — all already
>   verified. The row's "continuous mid-run adaptive compute scaling" spec
>   was an unsourced gloss; the paper describes no controller that grows a
>   run's envelope mid-run. Corrected the requirement to the source and moved
>   to `verified`; no code changed.
>
> One row advanced but stays `partial`:
>
> - `EVAL-ABLATION-001` (`7b7db229`) — the two ablation arms this row lacked
>   now exist engine-side: `enable_meta_review` gates the periodic
>   meta-review cadence and `generation_strategy` forces the debate-strategy
>   mix, both offline-wired into `ablation_driver.py`. Offline arms are
>   identical by construction, so the credentialed comparative sweep against
>   `PUBLISHED_BASELINES` still needs provider keys — the residual, narrowed
>   to that.
>
> **Parity closure (2026-09-10).** A new `divergent` status was added to the
> ledger vocabulary and five rows moved from `partial` to `divergent`:
> `SCORE-COMPOSITION-001`, `REPORT-HEADING-DUPLICATION-001`,
> `REPORT-DOCUMENT-SPLIT-001`, `GOAL-RESTATEMENT-001`, and
> `RANKING-CRITERIA-TABLE-001`. So `partial` drops 12 → 7 and `divergent` is
> 5; no row added or removed, still 115. These are settled, accepted
> divergences from Google — not unfinished work: Google's score composition is
> an undisclosed formula we do not reproduce (`SCORE-COMPOSITION-001`); the
> duplicated ranking heading is a corpus transcription artifact, not a shape
> to mirror (`REPORT-HEADING-DUPLICATION-001`); and the single-document
> decision the owner made on direct product-UI evidence — the document-split
> cluster — retired the second published document and everything built only to
> differentiate it (`REPORT-DOCUMENT-SPLIT-001`, `GOAL-RESTATEMENT-001`,
> `RANKING-CRITERIA-TABLE-001`). `divergent` records the difference and its
> reason rather than tracking work still owed.

---

## 2. Deterministic mock / recovery evidence

> As of the note above, "mock" throughout this section names the retired
> `app/app/mock_workflow*.py` provider exercised on 2026-07-10; the commands
> and files below (`test_integration_run_flow.py`, `test_resume.py`) now run
> against the engine pinned to the offline LLM backend instead, per
> `033c5377`/`a3729a0b`.

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
- **Checkpoint / restart-recovery (app, failure injection):** as recorded on
  the report date, `test_resume.py` interrupted a mock run mid-iteration,
  reconciled it as resumable, resumed (clear + deterministic re-run), and
  asserted identical terminal artifacts, exactly one report, and
  unique/monotonic event seqs (no duplicates); double-resume was stable. That
  test content (`test_interrupted_run_is_resumable_and_completes_once`,
  `test_double_resume_is_stable`) was dropped with the mock workflow and has
  no direct app-level replacement (see `CKPT-FAILINJECT-001`, now `partial`,
  in [PARITY.md](PARITY.md)). A single interruption + resume is still proven
  end-to-end at the app layer (`test_resume_engine.py`), and two consecutive
  restarts preserving the pool is still proven at the engine layer
  (`test_resume_pipeline.py::test_double_restart_preserves_pool_and_completes`);
  only the app-level *double-resume* composition currently lacks a test.

Offline evaluations (machine-readable results under `evaluations/results/`):

- `python -m evaluations.citation_eval` — claim/entailment metrics
  (precision/recall per label, contradiction recall, abstention).
- `python -m evaluations.safety_eval` — per-hypothesis safety false-positive /
  false-negative rates on the adversarial regression set.

---

## 3. Real-provider (engine) evidence and the recorded external blocker

Mock success never substitutes for real-provider verification.

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
pip install -e engine/mcp_server/    # into a 3.12 environment
cd engine && uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888

# 2. Run the app against the real engine + MCP with a live key:
cd app && MODEL_NAME=deepseek/deepseek-chat \
  MCP_SERVER_URL=http://localhost:8888/mcp \
  ../.venv/bin/python -m uvicorn app.main:app --port 8008
# then POST /api/runs + /start and observe provider="engine" in /status,
# and evidence rows sourced from pubmed/indra (source != "mock").
```

The `/status` and `/config` endpoints disclose which path produced each run;
since the mock provider's deletion, `runs.provider` is always `"engine"` and
the meaningful distinction is the persisted `runs.llm_backend` column (real
vs offline), so a real-provider run is never conflated with a deterministic
offline one (`PROVENANCE-PATH-001`, verified — see the updated evidence in
[PARITY.md](PARITY.md)).

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

**Implemented and proven (47 verified rows):** immutable evolution with explicit
lineage; explicit append/replace state reducer; deterministic adaptive
Supervisor scheduling with recorded reasons, budgets, and termination; dynamic
routing that generates in later cycles; all five default output criteria scored;
meta-review critique appended to every relevant agent prompt; weighted
proximity-/recency-/rank-aware matchmaking with coverage guarantees; multi-turn
debate for top-ranked vs single-turn for lower-ranked, with persisted depth; an
engine-built weighted proximity graph from the real proximity schema
(`PROX-GRAPH-001`, after a schema-contract fix); an engine-native pre-ranking
per-hypothesis safety screen that removes blocked hypotheses from the workflow
state before they reach the tournament, evolution, meta-review, or the report
(`SAFE-PERHYP-001`/`SAFE-REMOVE-001`); a versioned workflow checkpoint with
app-driven engine-exact resume — the app persists the full `WorkflowState`
after each node and, on resume, restores it and continues from the orchestrator
without repeating completed LLM/tool work (`CKPT-RESUME-001`) — plus
pause/resume and startup auto-resume; the tools-config
forwarding/validation/disclosure path (`TOOLS-CONFIG-001`); intake and final
safety gates; run-level provider provenance; a provenance-stamped semantic
(LLM/NLI) claim assessor exercised end-to-end by a local INDRA-tools golden run
(`CITE-CLAIM-001`, `TOOLS-CONFIG-001`); and offline evaluation harnesses.

**Partial (component or one layer exists; the production path is not yet
equivalent — 10 rows):** for the real engine, claim *gating* runs *after* its
internal tournament, so a contradicted hypothesis can still shape
ranking/evolution/meta-review before being excluded from the report (the
per-hypothesis *safety* screen now runs pre-ranking — see `SAFE-PERHYP-001` —
but claim-level entailment gating placement does not yet, `CITE-GATE-001`);
scientist steering, manual hypotheses, and manual reviews are persisted but not
injected into a live engine run; the six reflection review types and four
generation techniques all *fire* but "full"/"simulation" review run ungrounded
on the single top hypothesis and literature/assumptions behavior is
path-dependent; citation resolvability has a swappable resolver but no live
retraction/DOI lookup is wired (`CITE-META-001`); the app
K-factor override is not forwarded to the engine; and no worker interface/queue
semantics exist. Each row names its gap and owner; the production-contract work
is tracked as P0/P1 in the audit.

**Missing (0 rows):** none remain. The proximity graph
(`PROX-GRAPH-APP-001`) is persisted and surfaced (now `verified`), and the
2026-09-10 pass closed the last two: the per-idea negative-critique
`Critiques` rollup (`REVIEW-CRITIQUES-ROLLUP-001`, `verified`) and the
run-view ETA tile (`RUN-VIEW-ETA-001`), reclassified `divergent` — the tile
shipped once and was deliberately removed (`f409d902`) as dishonest, and the
frontend carries no determinate progress signal to compute an honest one.

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
