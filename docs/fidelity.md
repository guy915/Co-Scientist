# Fidelity to Google DeepMind's AI Co-Scientist

The Co-Scientist research artefacts (the "Towards an AI co-scientist" paper, the
public demos, and the product captures in `media/`) describe the system at the
level of agent roles, behavioural invariants, and final-product UX. They do
**not** publish numeric hyperparameters, ranking constants, prompt details, or
persistence schemas. This document catalogues which invariants this
implementation preserves, which are **implementation-defined** (chosen to
satisfy the spirit of the published behaviour without overspecifying), and
which are explicitly out of scope.

## Invariants preserved exactly

| Invariant | Where | Source |
| --- | --- | --- |
| Multi-agent, supervised co-scientist (not a single prompt chain) | `engine_adapter`, `mock_workflow` | "Towards an AI co-scientist" §3 |
| Hypotheses are persistent, versioned, auditable | `store.hypotheses` is append-only; `hypothesis_state` separates mutable fields | published behavioural invariant |
| Tournament uses **pairwise** comparison (not absolute scalar scoring) | `mock_workflow._judge`, `engine.nodes.ranking` | published |
| Initial Elo is **1200** | `app/elo.py` `INITIAL_ELO`; mirrors engine `INITIAL_ELO_RATING` | published |
| Standard Elo formula | `app/elo.py` `update_pair` mirrors `engine.nodes.ranking.calculate_elo_update` | textbook Elo |
| Evolution generates **new** offspring hypotheses with lineage | `store.add_hypothesis(parent_id=…)`; verified by `tests/test_evolution.py` | published — explicit invariant in product docs |
| Meta-review feedback synthesized and appended to every agent's prompt in later iterations | `nodes/meta_review.py`; `_format_meta_review_context` threaded into the generation, reflection, ranking, review, and evolve prompts (no-op when empty); `store.reviews` row per iteration | "Towards an AI co-scientist" §3.3 — feedback without back-propagation |
| Deep-verification review (probing questions challenging a hypothesis's fundamental assumptions) | `nodes/deep_verification.py` runs on the top-k by Elo after ranking; verdict feeds the ranking prompt; surfaced as `reviewer_agent="deep_verification"` reviews | "Towards an AI co-scientist" §3.3 + Fig A.15 |
| Research overview + NIH Specific Aims synthesized from the top hypotheses | `nodes/research_overview.py` terminal node; surfaced in the report payload + markdown (`## Research Overview` / `## NIH Specific Aims`) | "Towards an AI co-scientist" §3.3 — research overview |
| Citation verification is a gate, not decoration | `store.citations.state` ∈ {verified, partial, unsupported, unavailable}; UI shows them prominently | published |
| Safety screening before **and** after generation | `safety.screen_intake` + `safety.screen_final`; both persisted | published |
| Runs use one canonical hypothesis-generation path | `run_modes.normalize_run_mode`; legacy `standard`/`advanced` inputs resolve to `default` | implementation policy after removing the obsolete profile split |
| UI exposes agents, queue, progress, evidence, tournament, reports, run specs, and scientist-in-the-loop interaction | Workbench Ideas / Knowledge Base / Summary / Run Specifications plus supporting Progress / Tournament / Chat views | published UX |

## Implementation-defined values

Because the source materials do not publish these numbers, this implementation
fixes deterministic defaults that match the published behaviour at the
structural level. All are configurable via env or the run-config request body.

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

These features are described in the published material but are not implemented
here:

-   **Real-time literature retrieval against PubMed/Europe PMC.** Mock evidence
    is generated deterministically; the real engine path retains the MCP-based
    retrieval the upstream `co_scientist` engine provides, but no live retrieval
    is wired into the FastAPI runs adapter beyond what the engine already does.
-   **Distributed worker queue.** A Celery+Redis backend is sketched in
    `plan.md` but not implemented; runs execute in a FastAPI background task.
-   **Multi-user collaboration, authentication, and project ownership.**
    Local-first only.
-   **Full Computational Discovery and Literature Insights surfaces from the
    Google Labs product family.** Only Hypothesis Generation is built.
-   **PDF / LaTeX export.** Markdown + JSON only.
-   **Vector / hybrid retrieval.** The store has no vector column; proximity
    clustering in mock mode is a constant-id strategy.

## Mock Mode disclosure

When no LLM key is set, the `/status` endpoint reports `mock_mode: true`. The
persisted `runs.provider` column records which provider produced each run so
historical runs from one mode are clearly distinguishable from the other.

The mock workflow is **deterministic**: same goal + same run mode + same
`run_id` produces byte-identical hypotheses, citations, and matchups. This is
intentional — it lets the implementation behave like a published academic
artefact rather than a demo that drifts run-to-run.

## Calibration against the published research

The "Towards an AI co-scientist" paper is the primary fidelity reference. The
implementation matches its described behaviour on:

-   The "generate → debate → evolve" core loop, under a persistent supervisor.
-   Hypotheses receive deeper review when they rank highly (top-k evolution).
-   Proximity clustering guides deduplication and pairing.
-   The final report distinguishes verified, partially supported, and
    unsupported claims.
-   Safety as a fail-closed gate on hazardous biomedical / chemical content.

Where the paper is silent (specific Elo K, exact pool sizes, prompt templates,
regex patterns), this implementation makes pragmatic choices and documents them
here.
