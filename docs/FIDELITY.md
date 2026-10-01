# Fidelity to Google's AI Co-Scientist

> **Precedence:** the authoritative gap analysis is
> [`fidelity-audit/`](fidelity-audit/README.md) — it does not credit this
> document as evidence, and where the two disagree, it wins. Read that first;
> this file remains useful as narrative background.

> **The authoritative, requirement-level parity record is
> [PARITY.md](PARITY.md)** — it tracks every published behavior with a stable
> ID, implementation evidence, an automated test/eval, and a status
> (`verified`/`partial`/`missing`/`external`/`undisclosed`). This document is
> the narrative companion; where the two differ, PARITY.md and the tests win.

The Co-Scientist research artefacts (the "Towards an AI co-scientist" paper, the public demos, and the product's own screenshots) describe the system at the level of agent roles, behavioural invariants, and final-product UX. They do **not** publish numeric hyperparameters, ranking constants, or persistence schemas. Prompts are the one exception: the paper's appendix publishes **eight** exact prompts (Figures A.1-A.8), and each of the eight now renders verbatim and in published order through this engine's real builders -- see `engine/src/co_scientist/prompts/templates/README.md` for the per-template account and `engine/tests/test_published_prompt_fidelity.py` for the standing check. The rest of Google's prompt library is undisclosed. This document catalogues which invariants this implementation preserves, which are **implementation-defined** (chosen to satisfy the spirit of the published behaviour without overspecifying), and which are explicitly out of scope.

## Google's own framing of this product

Distinct from the paper: labs.google's own page for this product family —
`og:title` **"Gemini for Science"** — offers **"Express interest"**: a
waitlist, not self-serve access. It presents (at least) three cards, each
credited to its own underlying technology; ours corresponds to the one
credited **"Built with Co-Scientist"**:

> **Hypothesis Generation**
>
> "Generate novel research ideas through a multi-agent system that
> simulates the scientific method to help identify knowledge gaps and
> propose testable research plans."

Its four claimed capabilities, as the page states them:

-   **Collaborative Research Partner** — chat to refine challenge,
    preferences and focus areas *before* initiating a run
-   **Tournament-Style Evaluation**
-   **Grounded Knowledge Base** — "ideas are linked to a comprehensive
    knowledge base of verified scientific references used by the agent
    during the run"
-   **Critical Flaw Detection** — "distinguish high-potential directions
    from non-viable ones"

Source: `docs/CORPUS-EXTRACTION.md:390` (corpus row R13-7), extracted
verbatim from Google's own page copy. All four capabilities have analogues
in this tree — the chat workspace, the Elo tournament, citation-grounded
evidence, and the review / deep-verification gates — so this is not a gap
list; it is the primary citation for the framing claims elsewhere in this
document and in [`EXPLAINER.md`](EXPLAINER.md) that describe what this
product *is* or *does* in language that parallels Google's own.

## Invariants preserved exactly

| Invariant | Where | Source |
| --- | --- | --- |
| Multi-agent, supervised co-scientist (not a single prompt chain) | `app/app/engine_adapter` drives the engine's compiled LangGraph `StateGraph`, whose nodes are the agent packages under `engine/src/co_scientist/agents/` (Supervisor, Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, Safety) | "Towards an AI co-scientist" §3 |
| Hypotheses are persistent, versioned, auditable | `store.hypotheses` is append-only; `hypothesis_state` separates mutable fields | published behavioural invariant |
| Tournament uses **pairwise** comparison (not absolute scalar scoring) | `co_scientist.agents.ranking.ranking::judge_matchup` (defined in the sibling `agents/ranking/ranking_debate.py` and re-exported; the old `co_scientist.nodes` shim layer has been removed) | published |
| Initial Elo is **1200** | `app/app/elo.py` `INITIAL_ELO`; mirrors engine `INITIAL_ELO_RATING` | published |
| Standard Elo formula | The engine owns the update math (`co_scientist.agents.ranking.ranking::calculate_elo_update`); `app/app/elo.py` only projects a leaderboard from the engine's already-computed ratings — its own pairwise updater was retired with the app's mock tournament | textbook Elo |
| Evolution generates **new** offspring hypotheses with lineage (never mutates the parent) | Engine builds an immutable child (`agents/evolution/evolve_results.py::_build_evolution_child`: new id, Elo 1200, zero matches, `parent_id`/`generation`); real-engine drain persists the explicit lineage (`engine_adapter/drain.py`); `store.hypotheses` is append-only. Tests: engine `test_evolve.py`, `test_integration_pipeline.py::test_evolve_path_appends_immutable_children`; app `test_engine_drain.py::test_drain_persists_explicit_lineage`, `test_evolution.py` | published — explicit invariant in product docs (SSR §4, §12) |
| Meta-review feedback synthesized and appended to every agent's prompt in later iterations | `agents/meta_review/meta_review.py`; `_format_meta_review_context` threaded into every generation strategy, comprehensive reflection, deep verification, ranking, proximity, safety, literature review, and the review node's observation prompt (no-op when empty). The two review-scoring prompt builders (`get_review_prompt`, `get_review_batch_prompt`) deliberately withhold the "areas already covered" / "open directions" sections — the initial review's `novelty` axis feeds the review gate — no longer terminal since 2026-09-07 (the disposition is derived from every review the idea holds, and a blocked idea gets one recheck per run), but still a gate whose blocking band bars an idea from the tournament — and "already covered" reads as a direct novelty penalty against an Evolution-origin refinement of a leading idea for being in the area it was bred to strengthen; those two callers still get the strengths/weaknesses/recommendations sections. `store.reviews` row per iteration | "Towards an AI co-scientist" §3.3 — feedback without back-propagation |
| Deep-verification review (probing questions challenging a hypothesis's fundamental assumptions) | `agents/reflection/deep_verification.py` runs on every rankable idea still owed one, between the safety screen and the tournament, mirroring `03-reflection.md` (ReviewHypothesis verifies, then creates that hypothesis's AddToTournament task); bounded once-ever per idea by a checkpointed `deep_verification_issued` enrichment, so the initial pool is verified once and each cycle's children once; verdict feeds the ranking prompt of the tournament it now precedes; surfaced as `reviewer_agent="deep_verification"` reviews and, since 2026-09-07, rendered in the Goal Report under each idea as the published `Question:` / `Answer:` / `Reasoning:` triple (`app/app/report/markdown/review_block.py`) | "Towards an AI co-scientist" §3.3 + Fig A.15 |
| Research overview + NIH Specific Aims synthesized from the top hypotheses | `agents/meta_review/research_overview.py`'s terminal firing publishes the NIH Specific Aims page, surfaced in the report payload + markdown (`## Research Overview` / `## NIH Specific Aims`); on `extended`/`ultra` it also fires periodically (`scheduling/policy_checks.py::_check_research_overview_cadence`) and routes back to the orchestrator loop point rather than to `END`, feeding a lean `interim_overview` into the next generate cycle | "Towards an AI co-scientist" §3.3 — research overview |
| Safety screening before **and** after generation | `safety.screen_intake` + `safety.screen_final`; both persisted | published |
| Runs use one canonical hypothesis-generation path | `run_modes.normalize_run_tier` / `run_modes.normalize_run_focus` size and steer every run; the old `standard`/`advanced`/`default` run-mode string no longer exists | implementation policy — superseded by the tier (express/standard/extended/ultra) + focus system |
| UI exposes hypotheses (ideas), evidence, tournament, reports, and scientist-in-the-loop interaction | Workbench chat workspace + run detail (`workbench_app.tsx`); `run_detail.tsx` routes to four tab components — `run_detail_specifications.tsx` (details), `run_detail_learning.tsx`, `run_detail_overview.tsx`, and `components/tabs/ideas_tab.tsx` (ideas) | Capability framing: Google's own product copy — "Google's own framing of this product" above (corpus R13-7). Four-tab mapping: [`UI-FIDELITY.md`](UI-FIDELITY.md)'s tab-mapping table and its "Evidence for the mapping" note |

> **The citation classifier is an audit label, not a verification gate.**
> Citation classification (`store.citations.state` ∈ {verified, partial,
> unsupported, unavailable}) is a post-hoc **audit label** computed from
> document-level lexical overlap (`app/app/citations.py`, coverage
> thresholds — intersection over the claim's own tokens, not Jaccard),
> surfaced in the UI and report. It is **not** a claim-level entailment check.
> A separate claim-level grounding + publication gate (`app/app/claims.py`,
> `CITE-*` in [PARITY.md](PARITY.md)) now exists and is `verified`: the
> real-run default assessor is LLM/NLI-based (the offline/CI default stays
> lexical by design), and on the durable engine path it runs *before*
> ranking via the pre-ranking evidence gate, so a contradicted claim no
> longer shapes the tournament. See PARITY.md for the exact status.

## Implementation-defined values

Because the source materials do not publish these numbers, this implementation fixes deterministic defaults that match the published behaviour at the structural level. All are configurable via env or the run-config request body.

| Value | Default | Source of decision |
| --- | --- | --- |
| `ELO_K_FACTOR` | **24** | Mirrors engine ranking node default. K is intentionally moderate so a single match can move a candidate ~12 points; high enough to surface a leader in 6–12 matches, low enough that one bad call doesn't destroy the leaderboard. |
| Canonical run mode | tier `standard` / focus `balance` | Current product flow sizes and steers every run through the tier (express/standard/extended/ultra) + focus system; the older `standard`/`advanced`/`default` run-mode string no longer exists. |
| Default pool size | 8 initial hypotheses | Matches the current chat-first workflow's candidate pool. |
| Default iterations | 2 evolve cycles | Keeps tournament and evolution as part of every run. |
| Tournament pair count | 12 | Calibrated so an Elo leader emerges with statistical separation for the canonical default pool. |
| Safety hard-block patterns | Narrow CBRN/weaponization keyword combinations | Reviewable in `app/app/safety.py`. Two layers, and `evaluations/safety_eval.py` now measures the bounds of both. The deterministic regex layer alone — which is also exactly what ships whenever the contextual assessor is disabled, offline, uncredentialed or erroring — scores FP 0.167 / FN 0.211 overall and FP 0.833 / FN 0.333 on the adversarial `hard` split: it still blocks most legitimate near-boundary research it is shown. A contextual assessor resolves those held verdicts in either direction; at the permissive ceiling (an assessor that clears every hold put to it) FP falls to 0.0 and FN rises to 0.263, which bounds what that layer can cost as well as what it buys. Constructions whose danger is not a judgment call — acquisition, yield improvement, a synthesis procedure named against a weapon class — are deterministic blocks no assessor can reach. Paraphrase with no literal trigger is the remaining gap, and nothing here closes it. |
| Citation classifier | Coverage (intersection over the claim's tokens) with two thresholds (0.60 verified / 0.30 partial) | Lightweight, deterministic, and good enough to surface all four classes for the demo; superseded the module's original Jaccard scoring, which made the top two states mathematically unreachable against an asymmetric claim/abstract pair. The real engine's LLM/NLI assessor (see `CITE-CLAIM-001` in PARITY.md) is the real-run default. |

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
-   **Multi-replica distributed worker queue.** Runs execute through a
    durable, persistent queue (`app/app/store/tasks.py`): every graph node,
    fan-out item, and tournament match is its own leased, heartbeat-renewed,
    idempotent row, resumable across process restarts (see AGENTS.md's
    "Durable task execution" section) -- this is not a bare FastAPI
    background task. What is out of scope is the *distributed* half: no
    Celery/Redis broker, and the queue's single SQLite writer means no
    multi-replica horizontal scaling (`N31` in the fidelity register) --
    the local single-process path is kept viable deliberately rather than
    adopting an undisclosed Google stack.
-   **Multi-user collaboration and project-level ownership across
    researchers.** Invite-based single-researcher authentication exists
    (`app/app/auth.py` -- access-code exchange, bearer sessions,
    `enforce_run_ownership` middleware scoping every `/api/*` request to its
    owning client), so this is not local-first-only. What remains
    unimplemented is collaboration on top of that identity layer: no shared
    or team-owned runs, no per-project roles or permissions, no multiple
    researchers viewing or steering the same run together.
-   **The Literature Insights and Computational Discovery surfaces from the
    Google Labs product family.** Hypothesis Generation is built; neither of
    the other two is. Google's own labs.google page presents the family as
    (at least) three cards, each credited to its own underlying technology
    (see "Google's own framing of this product" above, corpus R13-7); this
    repo builds only the card credited "Built with Co-Scientist".
    Computational discovery was built here and then removed
    (`docs/decisions/2026-08-26-remove-computational-discovery.md`): the
    product generates and ranks hypotheses, and evolving a program against a
    measured objective is a second product that shared only the task queue
    with it.
-   **PDF / LaTeX export.** Markdown + JSON only.
-   **Vector / hybrid retrieval.** The store has no vector column; proximity
    clustering is instead driven by an LLM-graded similarity call
    (`agents/proximity/proximity.py`, `agents/proximity/proximity_graph.py`) that
    re-matches hypotheses to the model's clusters by text prefix, not an
    embedding search. On a deterministic offline run that call is answered by
    the offline LLM backend's schema-filling response (seeded per call, not a
    fixed constant id) rather than by the retired mock's dedicated clustering
    strategy. Since 2026-09-09 the graph nonetheless carries a similarity for
    *every* pair of the surviving pool: pairs the clustering call did not judge
    are measured by `agents/proximity/proximity_similarity.py::pair_similarity`,
    the symmetric Dice form of the same token-coverage metric the evolution
    duplicate guard uses. That is lexical overlap, still not an embedding — a
    judged edge wins wherever one exists, and each edge names its own `method`.

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
    citation classifier). Separate claim-level grounding (`app/app/claims.py`)
    now exists and is `verified` — the real-run default assessor is
    LLM/NLI-based (offline/CI stays lexical by design), and on the durable
    engine path it runs *before* ranking via the pre-ranking evidence gate;
    see the `CITE-*` rows in [PARITY.md](PARITY.md).
-   Safety as a fail-closed gate on hazardous biomedical / chemical content
    **at the run level** (intake + final), **plus** a structured
    per-hypothesis safety review (`SAFE-PERHYP-001`). The engine-native
    `safety_screen` node (`agents/safety/safety_screen.py`) now runs pre-ranking on
    every path — including the orchestrator's direct `rank` route — removing
    blocked hypotheses from `WorkflowState` before they reach the tournament,
    evolution, or meta-review; the app's `engine_adapter/drain.py` retains a
    post-tournament screen at the report boundary as defense-in-depth, not as
    the only pre-ranking gate. `SAFE-PERHYP-001`/`SAFE-REMOVE-001` are
    `verified` in [PARITY.md](PARITY.md).

Where the paper is silent (specific Elo K, exact pool sizes, the prompt templates outside the published eight, regex patterns), this implementation makes pragmatic choices and documents them here. The eight published prompts are not in that category: they are mirrored verbatim, and every remaining local addition to them is enumerated in `engine/src/co_scientist/prompts/templates/README.md`.
