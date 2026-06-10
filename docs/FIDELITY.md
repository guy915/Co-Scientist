# Fidelity to Google DeepMind's AI Co-Scientist

The Co-Scientist research artefacts (the "Towards an AI co-scientist" paper, the public demos, and the product captures in `reference/Media/`) describe the system at the level of agent roles, behavioural invariants, and final-product UX. They do **not** publish numeric hyperparameters, ranking constants, prompt details, or persistence schemas. This document catalogues which invariants the clone preserves, which are **clone-defined** (chosen by us to satisfy the spirit of the published behaviour without overspecifying), and which are explicitly out of scope.

## Invariants preserved exactly

| Invariant | Where | Source |
| --- | --- | --- |
| Multi-agent, supervised co-scientist (not a single prompt chain) | `engine_adapter`, `mock_workflow` | "Towards an AI co-scientist" §3 |
| Hypotheses are persistent, versioned, auditable | `store.hypotheses` is append-only; `hypothesis_state` separates mutable fields | published behavioural invariant |
| Tournament uses **pairwise** comparison (not absolute scalar scoring) | `mock_workflow._judge`, `engine.nodes.ranking` | published |
| Initial Elo is **1200** | `app/elo.py` `INITIAL_ELO`; mirrors engine `INITIAL_ELO_RATING` | published |
| Standard Elo formula | `app/elo.py` `update_pair` mirrors `engine.nodes.ranking.calculate_elo_update` | textbook Elo |
| Evolution generates **new** offspring hypotheses with lineage | `store.add_hypothesis(parent_id=…)`; verified by `tests/test_evolution.py` | published — explicit invariant in product docs |
| Meta-review feedback persisted and fed back into later iterations | `store.reviews` row per iteration; included in iterative ranking | published |
| Citation verification is a gate, not decoration | `store.citations.state` ∈ {verified, partial, unsupported, unavailable}; UI shows them prominently | published |
| Safety screening before **and** after generation | `safety.screen_intake` + `safety.screen_final`; both persisted | published |
| Standard vs Advanced produce observably different compute depth | `mock_workflow.PROFILE_DEFAULTS`; verified by `test_advanced_run_produces_more_artifacts` | published |
| UI exposes agents, queue, progress, evidence, tournament, reports | Workbench Overview / Ideas / Evidence / Tournament / Report tabs | published UX |

## Clone-defined values

Because the source materials do not publish these numbers, the clone fixes deterministic defaults that match the published behaviour at the structural level. All are configurable via env or the run-config request body.

| Value | Default | Source of decision |
| --- | --- | --- |
| `ELO_K_FACTOR` | **24** | Mirrors engine ranking node default. K is intentionally moderate so a single match can move a candidate ~12 points; high enough to surface a leader in 6–12 matches, low enough that one bad call doesn't destroy the leaderboard. |
| Standard pool size | 5 initial hypotheses | Matches engine `DEFAULT_INITIAL_HYPOTHESES_COUNT` + Co-Scientist demo videos showing a small initial pool. |
| Advanced pool size | 8 initial hypotheses | Strictly larger so the test `test_advanced_run_produces_more_artifacts` can assert depth difference. |
| Standard iterations | 1 evolve cycle | Reflects the "fast scoping" framing of Standard runs. |
| Advanced iterations | 2 evolve cycles | Matches the "extended tournament" framing. |
| Tournament pair count (Std/Adv) | 6 / 12 | Calibrated so an Elo leader emerges with statistical separation, scaled with pool size. |
| Safety hard-block patterns | Narrow CBRN/weaponization keyword combinations | Hand-picked to bias toward avoiding false positives on legitimate research (CRISPR papers, pathogen biology, etc.). Reviewable in `app/safety.py`. |
| Citation classifier | Jaccard token overlap with two thresholds (0.35 / 0.10) | Lightweight, deterministic, and good enough to surface all four classes for the demo. The real engine would call an LLM verifier here. |

## Explicitly out of scope (this pass)

These features are described in the published material but not implemented in this clone:

- **Real-time literature retrieval against PubMed/Europe PMC.** Mock evidence is generated deterministically; the real engine path retains the MCP-based retrieval the upstream `open_coscientist` engine provides, but no live retrieval is wired into the FastAPI runs adapter beyond what the engine already does.
- **Distributed worker queue.** A Celery+Redis backend is sketched in `PLAN.md` but not implemented; runs execute in a FastAPI background task.
- **Multi-user collaboration, authentication, and project ownership.** Local-first only.
- **Full Computational Discovery and Literature Insights surfaces from the Google Labs product family.** Only Hypothesis Generation is built.
- **PDF / LaTeX export.** Markdown + JSON only.
- **Vector / hybrid retrieval.** The store has no vector column; proximity clustering in mock mode is a constant-id strategy.

## Mock Mode disclosure

When no LLM key is set, the workbench surfaces a "Mock Mode" banner on every page and the `/status` endpoint reports `mock_mode: true`. The persisted `runs.provider` column records which provider produced each run so historical runs from one mode are clearly distinguishable from the other.

The mock workflow is **deterministic**: same goal + same profile + same `run_id` produces byte-identical hypotheses, citations, and matchups. This is intentional — it lets the clone behave like a published academic artefact rather than a demo that drifts run-to-run.

## Calibration against the published research

The "Towards an AI co-scientist" paper is the primary fidelity reference. The clone matches its described behaviour on:

- The "generate → debate → evolve" core loop, under a persistent supervisor.
- Hypotheses receive deeper review when they rank highly (top-k evolution).
- Proximity clustering guides deduplication and pairing.
- The final report distinguishes verified, partially supported, and unsupported claims.
- Safety as a fail-closed gate on hazardous biomedical / chemical content.

Where the paper is silent (specific Elo K, exact pool sizes, prompt templates, regex patterns), the clone makes pragmatic choices and documents them here.
