# Fidelity to Google's AI Co-Scientist

> **The authoritative, requirement-level parity record is
> [PARITY.md](PARITY.md)** — it tracks every published behavior with a stable
> ID, implementation evidence, an automated test/eval, and a status
> (`verified`/`partial`/`missing`/`external`/`undisclosed`). This document is
> the narrative companion; where the two differ, PARITY.md and the tests win.

The Co-Scientist research artefacts (the "Towards an AI co-scientist" paper, the public demos, and the product captures in `media/`) describe the system at the level of agent roles, behavioural invariants, and final-product UX. They do **not** publish numeric hyperparameters, ranking constants, prompt details, or persistence schemas. This document catalogues which invariants this implementation preserves, which are **implementation-defined** (chosen to satisfy the spirit of the published behaviour without overspecifying), and which are explicitly out of scope.

## Invariants preserved exactly

| Invariant | Where | Source |
| --- | --- | --- |
| Multi-agent, supervised co-scientist (not a single prompt chain) | `app/app/engine_adapter` drives the engine's compiled LangGraph `StateGraph`, whose nodes are the agent packages under `engine/src/co_scientist/agents/` (Supervisor, Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, Safety) | "Towards an AI co-scientist" §3 |
| Hypotheses are persistent, versioned, auditable | `store.hypotheses` is append-only; `hypothesis_state` separates mutable fields | published behavioural invariant |
| Tournament uses **pairwise** comparison (not absolute scalar scoring) | `co_scientist.agents.ranking.ranking::judge_matchup` (re-exported at the historical `co_scientist.nodes.ranking` import path) | published |
| Initial Elo is **1200** | `app/elo.py` `INITIAL_ELO`; mirrors engine `INITIAL_ELO_RATING` | published |
| Standard Elo formula | `app/elo.py` `update_pair` mirrors `engine.nodes.ranking.calculate_elo_update` | textbook Elo |
| Evolution generates **new** offspring hypotheses with lineage (never mutates the parent) | Engine builds an immutable child (`nodes/evolve_results.py::_build_evolution_child`: new id, Elo 1200, zero matches, `parent_id`/`generation`); real-engine drain persists the explicit lineage (`engine_adapter/drain.py`); `store.hypotheses` is append-only. Tests: engine `test_evolve.py`, `test_integration_pipeline.py::test_evolve_path_appends_immutable_children`; app `test_engine_drain.py::test_drain_persists_explicit_lineage`, `test_evolution.py` | published — explicit invariant in product docs (SSR §4, §12) |
| Meta-review feedback synthesized and appended to every agent's prompt in later iterations | `nodes/meta_review.py`; `_format_meta_review_context` threaded into the generation, reflection, ranking, review, and evolve prompts (no-op when empty); `store.reviews` row per iteration | "Towards an AI co-scientist" §3.3 — feedback without back-propagation |
| Deep-verification review (probing questions challenging a hypothesis's fundamental assumptions) | `nodes/deep_verification.py` runs on the top-k by Elo after ranking; verdict feeds the ranking prompt; surfaced as `reviewer_agent="deep_verification"` reviews | "Towards an AI co-scientist" §3.3 + Fig A.15 |
| Research overview + NIH Specific Aims synthesized from the top hypotheses | `nodes/research_overview.py` terminal node; surfaced in the report payload + markdown (`## Research Overview` / `## NIH Specific Aims`) | "Towards an AI co-scientist" §3.3 — research overview |
| Safety screening before **and** after generation | `safety.screen_intake` + `safety.screen_final`; both persisted | published |
| Runs use one canonical hypothesis-generation path | `run_modes.normalize_run_mode`; legacy `standard`/`advanced` inputs resolve to `default` | implementation policy after removing the obsolete profile split |
| UI exposes hypotheses (ideas), evidence, tournament, reports, and scientist-in-the-loop interaction | Workbench chat workspace + run detail (`workbench_app.tsx`); the only live tab component is `ideas_tab.tsx`; `run_detail.tsx` renders details / learning / research-overview inline | published UX (see the note below on retired tabs) |

> **The citation classifier is an audit label, not a verification gate.**
> Citation classification (`store.citations.state` ∈ {verified, partial,
> unsupported, unavailable}) is a post-hoc **audit label** computed from
> document-level lexical overlap (`app/citations.py`, Jaccard thresholds),
> surfaced in the UI and report. It is **not** a claim-level entailment check.
> A separate claim-level grounding + publication gate (`app/claims.py`,
> `CITE-*` in [PARITY.md](PARITY.md)) now exists but is `partial`: the
> assessor is still lexical (not entailment), and for the real engine it runs
> *after* the tournament rather than gating ranking. See PARITY.md for the
> exact status.

## Implementation-defined values

Because the source materials do not publish these numbers, this implementation fixes deterministic defaults that match the published behaviour at the structural level. All are configurable via env or the run-config request body.

| Value | Default | Source of decision |
| --- | --- | --- |
| `ELO_K_FACTOR` | **24** | Mirrors engine ranking node default. K is intentionally moderate so a single match can move a candidate ~12 points; high enough to surface a leader in 6–12 matches, low enough that one bad call doesn't destroy the leaderboard. |
| Canonical run mode | default | Current product flow has one run path. Older clients and persisted drafts may still send `standard` or `advanced`, but execution normalizes them to `default`. |
| Default pool size | 8 initial hypotheses | Matches the current chat-first workflow's candidate pool. |
| Default iterations | 2 evolve cycles | Keeps tournament and evolution as part of every run. |
| Tournament pair count | 12 | Calibrated so an Elo leader emerges with statistical separation for the canonical default pool. |
| Safety hard-block patterns | Narrow CBRN/weaponization keyword combinations | Hand-picked to bias toward avoiding false positives on legitimate research (CRISPR papers, pathogen biology, etc.). Reviewable in `app/safety.py`. |
| Citation classifier | Jaccard token overlap with two thresholds (0.35 / 0.10) | Lightweight, deterministic, and good enough to surface all four classes for the demo. The real engine would call an LLM verifier here. |

## Explicitly out of scope (this pass)

These features are described in the published material but are not implemented here:

-   **Real-time literature retrieval against PubMed/Europe PMC.** The
    literature-review node is MCP-gated (`agents/generation/literature_review/`):
    the graph auto-detects MCP availability, and without a reachable server the
    generation/reflection nodes fall back to LLM-only mode with no retrieved
    evidence, on every run (keyless/offline included). The deterministic offline
    LLM backend (`engine/src/co_scientist/offline_llm.py`) only fakes LLM
    completions at the `litellm.acompletion` seam; it does not simulate a
    literature-retrieval tool call, so an offline run's evidence gap is the same
    MCP-unavailable fallback a real-provider run hits without a reachable MCP
    server -- no separate mock-evidence generator exists. No live retrieval is
    wired into the FastAPI runs adapter beyond what the engine already does.
-   **Distributed worker queue.** Runs execute in a FastAPI background task;
    no Celery/Redis worker pool. Per PLAN.md the local FastAPI path is kept
    viable deliberately rather than adopting an undisclosed Google stack.
-   **Multi-user collaboration, authentication, and project ownership.**
    Local-first only.
-   **Full Computational Discovery and Literature Insights surfaces from the
    Google Labs product family.** Only Hypothesis Generation is built.
-   **PDF / LaTeX export.** Markdown + JSON only.
-   **Vector / hybrid retrieval.** The store has no vector column; proximity
    clustering is instead driven by an LLM-graded similarity call
    (`agents/proximity/proximity.py`, `agents/proximity/proximity_graph.py`) that
    re-matches hypotheses to the model's clusters by text prefix, not an
    embedding search. On a deterministic offline run that call is answered by
    the offline LLM backend's schema-filling response (seeded per call, not a
    fixed constant id) rather than by the retired mock's dedicated clustering
    strategy.

## Offline Mode disclosure

Every run executes on the real engine. When no LLM key is set (or
`COSCIENTIST_FORCE_OFFLINE=1`, deprecated alias `COSCIENTIST_FORCE_MOCK=1`,
is set), the `/status` endpoint reports `llm_backend: "offline"`
(`mock_mode: true` remains as a deprecated mirror). The persisted
`runs.llm_backend` column records which backend produced each run so
historical runs from one mode are clearly distinguishable from the other.

The offline backend is **deterministic at the call level**: an identical
completion call (same model + prompt + response schema) always produces
byte-identical output. This keeps a single LLM call reproducible and lets the
suite assert on offline responses without a live provider.

Full-run byte-reproducibility does **not** hold on the engine. Unlike the
retired mock (which re-derived an entire run from `run_id` and so was
byte-identical run-to-run), the engine embeds fresh per-run identifiers
(e.g. UUIDs) into its prompts, so the same goal + run mode + `run_id`
generally yields *different* prompts across runs and therefore different
hypotheses, citations, and matchups. This run-level reproducibility was
deliberately given up in the offline-LLM migration; only per-call
determinism is guaranteed.

## Calibration against the published research

The "Towards an AI co-scientist" paper is the primary fidelity reference. The implementation matches its described behaviour on:

-   The "generate → debate → evolve" core loop, under a supervisor that
    conditions each iteration's prompts and now **dynamically schedules**
    agents from summary statistics (Milestone 2, `SUP-*` in
    [PARITY.md](PARITY.md)) — replacing the earlier fixed bounded iteration
    order. This is a *deterministic adaptive policy* with fixed thresholds
    dispatched through a single sequential graph loop, not Google's freeform
    parallel planner; that scale/parallelism gap is tracked in the audit.
-   Hypotheses receive deeper review when they rank highly (top-k evolution).
-   Proximity clustering guides deduplication and pairing.
-   The final report distinguishes verified, partially supported, and
    unsupported claims **by the audit label above** (the document-level
    citation classifier). Separate claim-level grounding (`app/claims.py`)
    now exists but is `partial` — a lexical assessor, not entailment, and for
    the real engine it runs *after* the tournament; see the `CITE-*` rows in
    [PARITY.md](PARITY.md).
-   Safety as a fail-closed gate on hazardous biomedical / chemical content
    **at the run level** (intake + final), **plus** a structured
    per-hypothesis safety review (`SAFE-PERHYP-001`). The engine-native
    `safety_screen` node (`nodes/safety_screen.py`) now runs pre-ranking on
    every path — including the orchestrator's direct `rank` route — removing
    blocked hypotheses from `WorkflowState` before they reach the tournament,
    evolution, or meta-review; the app's `engine_adapter/drain.py` retains a
    post-tournament screen at the report boundary as defense-in-depth, not as
    the only pre-ranking gate. `SAFE-PERHYP-001`/`SAFE-REMOVE-001` are
    `verified` in [PARITY.md](PARITY.md).

Where the paper is silent (specific Elo K, exact pool sizes, prompt templates, regex patterns), this implementation makes pragmatic choices and documents them here.
