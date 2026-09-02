# Fidelity findings

Every distinct gap between this repository and Google's AI Co-Scientist (Nature
2026) / Google Labs **Hypothesis Generation**, synthesized from three audits
(2026-07-12, 2026-07-20, 2026-07-21) that raised 506 rows between them in three
incompatible vocabularies. Duplicates are collapsed; nothing is dropped.

See [README.md](README.md) for method, evidence, and how the three audits relate.
See [PLAN.md](PLAN.md) for the sequenced work.

**Columns.** `Sev` — Critical / High / Medium / Low. `Class` — `missing`,
`partial`, `incorrect` (claims the behavior but violates it), `divergent`
(deliberate substitute), `ext` (non-faithful extension Google does not have),
`matched`, `note`. `St` — status: blank = open as last audited, `✓` = addressed
on `main` since, `~` = partly addressed, `?` = contested between audits,
`=` = closed as a deliberate local choice.
`Src` — provenance in the source audits (`12:`/`20:`/`21:` = audit date).

The audits scored this repository as an attempted replica of Google's product,
so they recorded every difference as a gap. It is not a replica: the engine
reconstructs the paper's published behavior, the product surface is its own. A
difference is a defect only where the local choice is worse — not where it is
merely different. Rows marked `=` are the differences that were chosen.

**Re-verified against `main` on 2026-08-05**, 276 commits past the audited
revision `11a31082`. Every **Critical** and **High** finding was checked against
the working tree; Medium and Low were checked where a commit or a neighbouring
change made staleness likely. A blank `St` on a Medium/Low row therefore means
"not contradicted by this pass", not "individually re-confirmed". See
[the re-verification log](#re-verification-2026-08-05) for the evidence.

---

## A. Interview and goal setup

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| A1 | High | missing | No **Interview Progress** rail — Google shows 3 numbered steps → green checks; our only in-flight signal is "Thinking…" and fields are invisible until completion | | 12:A03, 20:F-INTERVIEW-02, 21:R7 |
| A2 | High | missing | Custom evaluation criteria never collected; `criteria: []` hard-coded, so no rubric governs ranking, debates, or self-improvement | ✓ | 12:A08, 20:F-INTERVIEW-09/EB-006, 21:K1 |
| A3 | Medium | incorrect | Plan fields read-only; "Edit research plan" opens no editor and `editInterviewFields` is unused | | 12:A06, 20:F-INTERVIEW-05, 21:R38 |
| A4 | Medium | missing | Interview lives only in React route state; reload discards it although the server still has it (`getInterview` never called) | ✓ | 20:F-INTERVIEW-04/F-STATE-01 |
| A5 | Medium | incorrect | Raw provider chain-of-thought streamed to the user; Google's footage shows only a "Thinking" status | = | 20:F-INTERVIEW-03/U23 |
| A6 | Medium | missing | No AI/medical disclaimer anywhere ("AI can be inaccurate…" / "Consult a professional…") | | 12:J08/M03, 20:F-HOME-04, 21:R22 |
| A7 | Medium | partial | Mid-run steering changes agent behavior but no UI calls `sendRunSteering` | | 12:A11/I05, 20:F-RUN-04, 21:R23 |
| A8 | Medium | partial | Scientist hypotheses/reviews: endpoints and safety admission exist, no UI | | 12:A12/A13, 20:F-AGENT-03, 21:A10 |
| A9 | Medium | partial | Attachments upload only *after* run creation and never ground the interview or plan, though the UI implies they do | ✓ | 20:F-HOME-05, 20:EB-025 |
| A10 | Medium | partial | Private corpus is run-scoped BM25 keyword search — not an indexed hundreds-of-PDFs, multimodal, agent-searchable repository | | 12:A09/A10/G19/G20, 20:EB-025, 21:G9 |
| A11 | Medium | incorrect | Create → upload → start is non-transactional; partial failure neither rolls back nor surfaces the orphan draft | ✓ | 20:F-INTERVIEW-12 |
| A12 | Low | partial | Field vocabulary drift: "Focus Area" singular vs Google's "Focus Areas"; extra Title field | = | 12:A04, 20:F-INTERVIEW-07, 21:R42 |
| A13 | Low | missing | No thumbs up/down on interview turns | | 12:M03, 21:R53 |
| A14 | Low | divergent | Composer copy differs ("What breakthrough should we make today?" vs "What's your research challenge?"); a decorative lock icon implies encryption that does not exist | = | 12:M02, 20:F-HOME-01, 21:A1 |
| A15 | Low | incorrect | Retry duplicates the same assistant string instead of re-running the model | | 20:F-INTERVIEW-06 |
| A16 | Low | incorrect | Keyless/offline interview silently degrades to a canned 3-question script with no UI signal | ✓ | 12:A05, 21:R56 |
| A17 | Low | incorrect | Home composer stays active after start and keeps posting turns to the completed interview | ✓ | 20:F-AGENT-02 |
| A18 | Low | note | No interview turn cap; a model that never sets `completed` interviews indefinitely | | 21:R58 |
| A19 | Low | partial | `cosci runs create` has no `--attach`; the document-staging path that grounds the interview is reachable only from the browser | | observed during A9 fix, 2026-08-06 |

## B. Run configuration and lifecycle

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| B1 | High | matched | Originally claimed: four tiers (`express/standard/extended/ultra`) replace Google's exactly-two Standard/Advanced; Google's config is conversational, with no settings form. **Corrected 2026-09-02, tier-count clause only**: false. The published product capture itself (App. C, `docs/CORPUS-EXTRACTION.md:1966`, the `## Tier` block of `plan-configs/mash-liver-fibrosis-reversal-research-plan.md`) lists exactly four tiers — Express/Standard/Extended/Ultra — in that order, with the identical quick→medium→large-scale→most-compute-intensive semantics `app/app/run_modes.py:15`'s `RUN_TIER_PATTERN` implements; there is no Google two-tier Standard/Advanced anywhere in the corpus. Pinned by `app/tests/test_published_plan_config.py::test_run_tiers_are_the_ones_the_product_offers`; see `docs/PARITY.md` `RUN-TIER-001`. The second clause ("conversational, with no settings form") is a separate claim this correction does not adjudicate: the same capture shows the tiers presented as a per-section option list with one **Selected**, inside a chat-embedded "Research plan" panel rather than a standalone settings page — consistent with, but not proof of, the original "conversational" framing. Left as previously recorded pending its own check | ✓ | 12:B01/B03, 20:F-INTERVIEW-08/EB-005, 21:R8, corpus R12-1 |
| B2 | Medium | matched | Originally claimed: four-way focus selector (evidence/balance/novelty/breakthrough) has no Google basis. **Corrected 2026-09-02**: false. The same published capture (App. C, `docs/CORPUS-EXTRACTION.md:1955`, the `## Focus` block) lists Prefer evidence / Balance / Prefer novelty / Breakthrough, in that order, with Balance marked **Selected** — name for name and default for default matching `app/app/run_modes.py:16-21`'s `RUN_FOCUS_VALUES`/`DEFAULT_RUN_FOCUS`. Pinned by `app/tests/test_published_plan_config.py::test_run_focus_values_are_the_ones_the_product_offers`; see `docs/PARITY.md` `RUN-FOCUS-001` | ✓ | 12:A15, 21:R8, corpus R12-2 |
| B3 | Medium | missing | Concurrency quota is one aggregate ceiling, not Google's 3 Standard + 1 Advanced; counted per spoofable client id *and* per profile, so one id can reserve 40 | ~ | 12:B04, 20:OP-002/OP-054 |
| B4 | Medium | divergent | Compute envelope far below Google's several-hour scale | | 12:B07, 20:EB-011 |
| B5 | Medium | incorrect | The generator caches its compiled graph and MCP availability, so configuration changes silently execute a stale topology. Re-scoped and fixed: the app side was already sound (each durable task builds its own generator and tool registry, so per-run connector toggles never shared a topology). The real staleness was engine-side -- the compiled graph was built once and never rechecked, so a reused generator ran the first call's topology forever in both directions, and `get_mcp_client` keyed its process-wide singleton on nothing, so a second caller resolving different servers silently talked to the first one's deployment. The graph is now shape-keyed, and `reload_tool_registry` drops the graph and the availability answers together because the probe is what decides the shape | ✓ | 20:EB-012 |
| B6 | Low | ext | Connector toggles (PubMed / Web / Lab papers) — Google's agent selects sources, naming them in plan prose | = | 20:F-HOME-06, 21:B5 |
| B7 | Low | missing | No credit / charge / refund / account-ledger concept | | 12:B05, 20:OP-003 |
| B8 | Low | partial | Completion email is implemented but delivery unproven; SMTP unset in production | | 12:B06, 20:F-INTERVIEW-10/OP-004 |
| B9 | Low | partial | Status vocabulary is a superset (extra `synthesizing`/`blocked`, `aborted`→`cancelled`); failed/cancelled/blocked runs still render full report tabs | ✓ | 12:B10, 20:F-STATE-03/F-RUN-07, 21:C4 |
| B10 | Low | partial | Pause/resume/cancel exist in the backend with no UI — and are not evidenced for Google either | | 12:B09, 20:U14 |

## C. Active run and progress

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| C1 | Medium | incorrect | Progress moves **backward**: fixed phase constants let deep verification report 81–84 then proximity 75–85, and the home card retains the furthest phase with `Math.max` | ✓ | 12:C06/C07, 20:F-RUN-06/EB-062, 21:R36 |
| C2 | Medium | incorrect | "Time remaining" is permanently "Estimating…"; where computed it is naive linear extrapolation over uneven tasks | | 12:C02, 20:F-RUN-02, 21:R36 |
| C3 | Medium | partial | Progress bar permanently indeterminate ("Progress pending") vs Google's determinate bar | | 12:C01, 20:F-RUN-01, 21:R36 |
| C4 | Medium | divergent | Activity log exposes internal stage names and raw task strings ("Engine Node Generate"); no per-item `EXECUTING` / `-- : --` status | | 12:C05/C08, 20:F-RUN-03, 21:R36 |
| C5 | Medium | divergent | Report and ideas unviewable mid-run — the tab bar is suppressed until the run settles | = | 21:R37 |
| C6 | Medium | missing | No live/reconnecting/stale indicator; SSE reconnects silently so a frozen page looks healthy | ✓ | 20:F-RUN-05 |
| C7 | Low | partial | Tiles differ from Google's exact three (Time remaining / Sources Analyzed / Ideas explored) | = | 12:C03/C04, 20:F-RUN-01, 21:L6 |
| C8 | Low | ext | Developer diagnostics (Logs popover, Offline chip) inside the research shell | = | 12:C09, 20:F-STATE-05/F-STATE-06 |

## D. Goal Report surface

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| D1 | **Critical** | ext | **Ideas is an Elo leaderboard with rank + "Elo rating: N" chips. Google deliberately hides Elo and shows a card list.** The single most consequential product divergence — and the local reference corpus's "Elo leaderboard" requirement is clone-invented | = | 12:D02/D23, 20:F-IDEAS-01/U09, 21:R2 |
| D2 | High | divergent | All four tab labels differ and the order is inverted: `Goal Details / Learning / Research Overview / All Ideas` vs `Ideas / Knowledge Base / Summary / Run Specification(s)` | = | 12:D01/M05, 20:F-REPORT-01, 21:R6 |
| D3 | High | missing | `HIGH POTENTIAL` / `NON VIABLE` pills absent from idea cards; buckets survive only as report counts | = | 12:D03/D17/M06, 20:F-IDEAS-07, 21:R20 |
| D4 | High | missing | Per-idea and report-level "Chat with Agent": `askRunQuestion` exists with no UI caller | | 12:A14/D12/D24, 20:F-AGENT-01, 21:R23 |
| D5 | High | incorrect | Public share returns raw complete hypotheses and evidence tables rather than the filtered release artifact — leaks blocked ideas, private document text, and run config | ✓ | 20:F-SHARE-02/EB-052 |
| D6 | Medium | incorrect | Completed runs land on Goal Details (configuration) instead of Ideas | = | 20:F-REPORT-02 |
| D7 | Medium | partial | Knowledge Base renders ≤3 sections vs Google's 12+; no sticky navigator, no inline citation chips | | 12:D07, 20:F-KB-01/F-KB-04, 21:R30 |
| D8 | Medium | incorrect | With no synthesis, the UI fabricates "learning" sections from the first three evidence abstracts — presentation output indistinguishable from an engine result | | 12:D08, 20:F-KB-02 |
| D9 | Medium | incorrect | KB reference numbers restart at 1 per topic while linking to global evidence rows, so a shown `[1]` can open `[5]` | | 20:F-KB-03 |
| D10 | Medium | missing | Mechanism diagrams absent (Google renders a generated multi-panel figure, "Generated by PaperBanana") | | 12:D05/K12, 20:F-IDEAS-04, 21:R39 |
| D11 | Medium | partial | Public share token cannot be minted from any UI or CLI | ✓ | 12:D14, 20:F-SHARE-01, 21:R50 |
| D12 | Medium | partial | Report download/export exists as an endpoint but no UI links it; no PDF/DOCX/CSV | ✓ | 12:D15, 20:F-EXPORT-01/OP-006, 21:R49 |
| D13 | Medium | incorrect | Idea detail labels a single row "Full review", hiding the independent/comprehensive/deep results and misrepresenting verification depth | ✓ | 20:F-IDEAS-05 |
| D14 | Medium | missing | Summary collapses High Potential / Non-Viable to counts, discarding the ideas and the rationales — the main decision explanation | | 12:D04, 20:F-SUMMARY-03 |
| D15 | Medium | incorrect | "Verified ideas" tile displayed the same number as "High Potential" | ✓ | 12:D04, 20:F-SUMMARY-02, 21:R29 |
| D16 | Medium | ? | NotebookLM handoff absent — **contested**: current Google Help lists it, 21 §4 argues it belongs to *Literature Insights*, not this product | ? | 12:D13/M18, 20:OP-005, 21:§4 |
| D17 | Low | partial | Tab nav labels contradict the documents' own `<h2>` headings (the "Learning" tab is headed "Knowledge Base") | | 12:M17, 20:F-SPEC-01, 21:R43 |
| D18 | Low | partial | `Evidence.available` never surfaced, so unreachable sources look accessed | ✓ | 20:F-KB-05, 21:G8 |
| D19 | Low | partial | Match history, opponents, Elo deltas, and debate transcripts are not inspectable | | 12:D23, 20:F-IDEAS-06, 21:D7 |
| D20 | Low | partial | Lineage is text-only ("evolved from an earlier hypothesis"); the parent is never named or linked and there is no tree | | 20:F-IDEAS-03, 21:D8 |
| D21 | Low | incorrect | Origin labels can leak raw engine keys (`generate`/`evolve` vs the mapped `generation`/`evolution`) | | 20:F-IDEAS-11 |
| D22 | Low | ext | Claim spans, cluster IDs, safety internals, and lineage blocks reshape the primary idea detail; Google exposes none of these | = | 12:D06, 20:F-IDEAS-12 |
| D23 | Low | partial | Sections rail has no scroll-spy or active state | | 20:F-IDEAS-10 |
| D24 | Low | partial | Winning ideas render as read-only text with no navigation to the idea or its rationale | | 20:F-SUMMARY-05 |
| D25 | Low | ext | Safety adjudication controls live inside report specifications, replacing target content and weakening the reviewer boundary | = | 20:F-SPEC-04 |
| D26 | Low | incorrect | Post-run upload is accepted but shows no list/status/removal and no reachable task consumes it | | 20:F-SPEC-05 |

## E. Coalition and reasoning strategies

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| E1 | **Critical** | incorrect | **Full / simulation / recurrent reviews are computed at LLM + retrieval cost and read by nothing** — not ranking, evolution, meta-review, report, or UI. Even fatal findings change no disposition | ✓ | 12:E13/E14, 20:EB-035, 21:R3 |
| E2 | **Critical** | incorrect | **The grounded-debate prompt renders `{{MISSING:user_hypotheses}}` and `{{MISSING:instructions}}` on every turn of the production path**, dropping user-supplied starting hypotheses and leaving the instruction slot empty | ✓ | 21:R5 |
| E3 | **Critical** | incorrect | **Assumptions generation runs ungrounded on the durable path** even when literature is available, and is cache-enabled — byte-identical output across identical goals | ✓ | 21:R21 |
| E4 | High | partial | Deep verification omits **sub-assumption decomposition** and **decontextualization**, two of its three defining behaviors | ✓ | 12:E11, 20:EB-036, 21:R9 |
| E5 | High | partial | Only 5 evolution operators (paper: 6); "inspiration from existing" absent, coherence/feasibility folded into ENHANCEMENT, and round-robin selection means ENHANCEMENT never fires on express | ✓ | 12:E24/K07, 20:EB-041, 21:R10 |
| E6 | High | missing | Enhancement-through-grounding performs **no literature retrieval** — only stale run-wide synthesis text | ✓ | 12:E24, 20:EB-041, 21:R11 |
| E7 | High | partial | Meta-review critique reaches ~9 of 12 prompt surfaces; **not** Proximity, Literature Review, or Safety, and never the observation node in practice | ✓ | 12:E28/I04, 20:EB-045, 21:R15 |
| E8 | High | partial | Full-review novelty grounding happens only when MCP is up; when it is down the system reproduces exactly the un-tooled failure mode Google measured (6.14 → 2.38/10) | ✓ | 12:E10/G08/K02, 20:EB-033, 21:K2 |
| E9 | Medium | incorrect | Deep verification runs **before first ranking** (all Elo tied, so "top three" is arbitrary) and fails open on provider error, leaving the idea rankable | ✓ | 20:EB-036 |
| E10 | Medium | partial | Multi-parent combination is structurally crippled: single `parent_id`, 200-char peer snippets, a contradictory "stay distinct" directive, and a 0.95 Jaccard rejection gate | ✓ | 12:E25, 20:EB-043, 21:R27 |
| E11 | Medium | partial | Agentic literature-exploration generation is dead code (`enable_tool_calling_generation` never set); research-expansion is a relabel with no distinct prompt — confirmed empirically | ✓ | 12:E05/E08, 20:EB-019, 21:R33 |
| E12 | Medium | partial | Assumptions generation is one structured call, not an iterative assumption/sub-assumption tree | ✓ | 12:E07, 20:EB-021, 21:E2 |
| E13 | Medium | partial | Debate turn counts fixed (5 generation / 3 ranking) vs the paper's 3–5 typical, max 10; the prompt says "max 10" while hard-coding 5 | ✓ | 12:E06, 20:EB-020, 21:R26 |
| E14 | Medium | incorrect | Parallel-debate diversity angles are inert on the durable path — each debate task runs with `total_debates=1` | ✓ | 21:R28 |
| E15 | Medium | incorrect | Initial-review batch has no 1..5 schema bounds, associates results by order, and lets one exception abort a large batch. Fixed: scores are bounded to the review rubric's integer range (the live rubric is 1–10 — the finding's "1..5" is stale) and invalid values are dropped, not clamped; entries map back by the prompt-assigned `hypothesis_index` with list order only as fallback; a malformed entry or failed call leaves that hypothesis unreviewed for the next pass instead of aborting the batch | ✓ | 20:EB-034 |
| E16 | Low | divergent | The debate `HYPOTHESIS` termination token is instructed but never parsed — the loop runs a fixed turn count then re-asks for JSON | ✓ | 21:R24 |
| E17 | Low | divergent | Ranking verdict is a JSON enum, not the literal `better idea: <1 or 2>`; the 7 comparison criteria are collected but never parsed. Fixed: the literal verdict line concluding `decision_summary` is now the primary verdict (the JSON enum stays as fallback, which is all the offline backend emits), and the seven criterion assessments ride the match record as `criteria_comparisons`; majority-vote and position-balance semantics unchanged | ✓ | 12:E18, 21:R25/R47 |
| E18 | Low | partial | Ranking "debate" is one judge re-running the same prompt with prior verdicts; no distinct advocate/opponent roles. Closed as a documented local choice: the paper's tournament prompts name a single evaluator and debate turn counts, never advocate/opponent personas — the persona requirement is clone-invented corpus design — and the choice is recorded on the judge loop (`agents/ranking/ranking_debate.py::_run_debate_turns`). **Corrected 2026-09-02**: "names a single evaluator" was wrong. The published `ranking-05-comparison-via-scientific-debate.md` prompt (App. A, `docs/CORPUS-EXTRACTION.md:1210-1214`) itself frames the judge as a plurality: "You are an expert in comparative analysis, **simulating a panel of domain experts**... The **experts** possess no pre-existing biases toward either hypothesis". Our `ranking.md` carries neither the panel framing nor any bias-neutrality language (zero hits for "panel", "domain expert", "pre-existing", "bias"). What stays true, and keeps this row closed: the paper still never names distinct advocate/opponent *personas* — the unnamed panel is not the same as our clone-invented Innovator/Pragmatist/Contrarian corpus requirement (rejected in the Corpus-integrity corrections table below), and our judge loop genuinely implements one voice, not a simulated panel of several. `ranking_debate.py::_run_debate_turns`'s own docstring still states the old, now-inaccurate "names a single evaluator" framing verbatim — out of scope for this docs-only correction; a code change is owed there | = | 12:E17, corpus R8-6 |
| E19 | Low | partial | Supervisor plan fields are stored but never re-read (3 of 6 guidance blocks unused). Closed: `supervisor_plan` and `supervisor_allocations` now persist the plan, the per-cycle allocation ledger with the observed stats behind each decision, the decision provenance and the terminal rationale, readable via `GET /api/runs/{id}/supervisor-plan`. The ledger syncs from `save_checkpoint`, not only from finalize, so a run that failed, was cancelled or was safety-blocked still leaves its record — the case the feature exists for. Growth is one row per orchestrator decision (measured: 3 on express, 5 on standard), never per task | ✓ | 12:E32, 21:E13 |
| E20 | Low | partial | Prompts are reconstructions, not the 8 published Google templates. Closed as documented and labelled — the only closure the evidence boundary allows: `engine/src/co_scientist/prompts/templates/README.md` labels every template by which of the eight published templates (A.1–A.8) it derives from and which are clone-authored reconstructions | = | 12:E30/E31, 20:U04 |

## F. Supervisor, orchestration, durability

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| F1 | **Critical** | incorrect | **A durable task that exhausts its retries leaves the run stuck in `running` forever** — no `failed` transition, SSE never closes, `cosci runs wait` hangs until a process restart | ✓ | 20:EB-015 (reproduced), 21:R18 |
| F2 | High | incorrect | An approved intake/final safety hold has **no claimable successor task** — the holding task already succeeded, so approval reuses a completed idempotency key and nothing resumes. Fixed: the hold is an explicit durable waiting state. The holding task is parked (leased -> paused, lease cleared, attempt reset) rather than recorded as succeeded, so approval releases a real row through the existing resume path instead of re-enqueueing a spent idempotency key | ✓ | 12:J06, 20:EB-016 (reproduced) |
| F3 | High | incorrect | A scientist-submitted hypothesis **collides with itself** during final persistence (`UNIQUE constraint failed: hypotheses.id`), preventing completion. Fixed: the hypothesis insert is an upsert whose conflict path keeps the stored row's id, run, author, `created_by_agent`, generation, parent lineage, title and statement, and fills only the engine-derived detail columns the row lacks; the state insert leaves an existing row (and its screened `safety_status`) alone, and the publication reset zeroes the retained row's win/loss counters so a replayed finalize does not add the same tournament twice | ✓ | 20:EB-003 (reproduced) |
| F4 | High | divergent | Supervisor is not an allocator — its own prompt says it must **not** plan workflow execution; execution is a fixed serial spine that picks one successor at a time. **Allocation contract built; concurrent node-level branching recorded as an accepted divergence.** Two corrections to this row's premise: the durable queue was already dependency-aware (`store/tasks.py::_dependencies_complete` gates `claim_task`, and fan-out already chained on it), and the orchestrator was already an adaptive per-cycle scheduler reading live `SchedulerStats`. What was missing was allocating more than one task at a time. A node commit now enqueues a bounded portfolio (`plan_portfolio`, depth cap 4) chained through the existing dependency gate, stopping at any node whose successor is genuinely unknowable — a fanning node, the orchestrator itself, or an unresolved route. The stale prompt lines forbidding workflow planning are gone. **Concurrent node-level branching stays out**, and the reason is structural, not effort: `next_task_type()` returns one successor and `_check_node_task_checkpoint` raises `SupersededTaskError` when the sequence moves, so two node tasks committing against one linear checkpoint chain means one always loses. True branching needs per-branch checkpoint chains — a durability-model change this stage deliberately excludes | ✓ | 12:E02/F04, 20:EB-008, 21:F1 |
| F5 | High | partial | No weighted sampling or dynamic re-weighting; the per-agent `performance_assessment` that would drive it is computed and unused. Half closed: the assessment is now persisted into the run's metrics row at each task commit, so it is inspectable and the allocator has something truthful to read. The weighting itself is Stage 11 and deliberately not built here — an allocator reading a counter that undercounts by design would be worse than none. **Resolved by declining the literal instruction, with evidence.** `supervisor_node` runs exactly once as the graph entry point (`graph.py` routes to it only when not resuming, and no `_TASK_ROUTES` entry returns to it), so it fires before any hypothesis, review or match exists; its own prompt tells the model to report "initial planning phase". Measured on an offline run, every `agent_performance` field came back a content-free paraphrase of the research goal. Weighting allocation on it is exactly the "worse than none" case this row already warned about. The measured per-cycle signal `rank_stable_cycles` was made causally effective instead | ✓ | 12:E04/F05, 20:EB-009, 21:R31 |
| F6 | Medium | incorrect | Steering is marked applied **before** the consuming checkpoint commits, so a crash can lose acknowledged steering | ✓ | 20:EB-002/EB-017 |
| F7 | Medium | incorrect | Human review score is reconstructed as 20/60/90 from summary words and re-drained as a generic `review`, losing authorship and semantics. Fixed: the review row carries `author` and `verdict` as columns, so nothing is recovered by scanning prose (the word scan survives only as a fallback for rows written before the columns); the verdict maps onto the engine's own 1-10 review rubric rather than a 0-100 scale of its own, which matters because the merged review is the *latest* one and the ranking prompt reads its score beside the agents'; and the drain leaves the authored row alone instead of adding a second `review`-labelled copy, restoring it with author and verdict only where a replay cascade removed it | ✓ | 20:EB-004 |
| F8 | Medium | incorrect | Foreign keys are declared but `PRAGMA foreign_keys=ON` runs only on the schema-init connection, so runtime FKs are off | ✓ | 20:EB-018, 21:M6 |
| F9 | Medium | incorrect | Several fan-outs abort the whole batch on one item failure instead of committing successful siblings | ✓ | 12:F09/L08, 20:EB-010/EB-043 |
| F10 | Medium | partial | Evolution is not strictly stagnation-gated — on the common both-zero tie it alternates, so it fires without stagnation. Closed, but note the trap found on the way: gating the tie on `rank_stable_cycles` alone starves generation outright, because stagnation is a *standing* condition, so once the Elo ordering settles the tie-break returns evolve forever and the run only ever evolves. That is the recorded pool-narrowing failure mode — evolution breeding from a shrinking pool re-derives the same idea. Stagnation is therefore edge-triggered — evolution wins a tie only on the transition into stagnation, never twice off the same standing reading | ✓ | 21:R32 |
| F11 | Low | divergent | Termination is iteration budget / convergence / LLM-call budget, not the paper's `MaxIdeas` and `MaxMatchesPerIdea`. Closed: both added to `Budget` (default `None`, no limit) as real predicates enforced at *both* sites — the deterministic policy and the code-enforced hard stop ahead of the model — so the two paths cannot diverge. `MAX_IDEAS` is gated on an empty review backlog so it drains rather than stranding fresh ideas | ✓ | 12:F06, 20:EB-011, 21:F6 |
| F12 | Low | note | **This finding's premise was mostly wrong; measured per reason.** `SAFETY` is genuinely live — `safety_blocked` is written by `agents/safety/safety_monitor.py` and invoked from meta-review every cycle. `MAX_TASKS`/`WALL_CLOCK` have real counters (`len(task_history)`, `start_time`); only their *limits* are unset by first-party callers, and they are supported public `GeneratorOptions.budget` keys, so removing them would break a library contract. Only `CANCELLED` was truly dead — nothing anywhere sets `cancel_requested` — and it is removed; cancellation is enforced more strongly by the durable executor never dispatching another node | ✓ | 21:F8 |
| F13 | Low | note | The compiled LangGraph was built on every bootstrap but never invoked for real runs | ✓ | 20:EB-007, 21:R54 |
| F14 | Low | note | A queued task whose dependency failed (without `allow_failed_dependencies`) is not claimable yet still blocks run settlement and keeps the cohort polling — a dependency livelock; settlement conservatively treats queued as claimable | | observed during F1 fix, 2026-08-05 |
| F15 | Medium | incorrect | `mcp_client._global_client` holds an `asyncio.Lock()` created at construction — the process-global asyncio primitive `AGENTS.md` records as a production failure for the ranking semaphore. Latent only because `initialize()` short-circuits once `_tools_dict` is set, so the lock is rarely awaited | | observed during B5 fix, 2026-08-06 |
| F16 | Medium | incorrect | `config/registry.get_tool_registry()` is first-caller-wins and is called with no arguments by three fallback sites (`literature_tools/draft_tools.py`, `prompts/generation_tools.py`, `prompts/loading.py`), so a run reaching them silently uses the bundled default topology rather than its own | | observed during B5 fix, 2026-08-06 |
| F17 | Low | note | Safety holds created before the `F2` fix cannot be released: their holding task is already `succeeded`, so approval has no parked row to resume. Affects only rows already in a deployed database | | observed during F2 fix, 2026-08-06 |
| F18 | High | incorrect | A lease that expires *after* its retry budget is spent is never explicitly failed, so `fail_task` never runs and Stage 1's `F1` settlement never fires. The row stays `leased` forever and the run stays non-terminal with no claimable work — the exact state F1 was meant to make impossible. Found by the L6 health probe, which detects it; F1 does not fix it. Closed: such a lease is named dead, `cohort_poll` stops counting it as a live sibling so the cohort can reach idle-exit, and `abandon_dead_leases` fails it there and settles the run. Verified by driving a real cohort over one: it spun for the whole timeout before, exits and settles now | ✓ | 26:S8 |

## G. Retrieval, grounding, citations

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| G1 | **Critical** | incorrect | **Claim-gate-blocked hypotheses stay `active` and are released** into the leaderboard, idea buckets, and report. Reproduced: fresh Standard and Ultra runs completed with **all** hypotheses failing the claim gate and **all** claim assessments `insufficient`. Closed as the decided policy, and the code already implements both halves: a contradicted idea is dropped from synthesis by id before the safety check, and a merely-unsupported one publishes carrying an "Unverified" badge. A run with no claim edges at all flags nothing, which is what exempts demo and offline runs. Both halves are pinned by `app/tests/test_engine_drain_safety.py::test_rank_and_publish_splits_contradicted_from_unverified` and the badge by `ideas_tab.test.tsx`. The rest of stage 7 raises how much evidence is found, which shrinks the unsupported set; it does not change what happens to it | = | 12:G16/G17, 20:EB-029 (reproduced) |
| G2 | **Critical** | incorrect | **Multi-term natural-language phrases are sent verbatim to Entrez, which ANDs every token** — no MeSH, no OR expansion, no field tags, no broadening retry, and the final fallback sends the whole prose goal. Documented root cause of the ~99% "insufficient" evidence rate. Fixed, and measured against live PubMed: the prose-goal fallback now distils the goal to its content terms instead of sending it whole, which took a real goal from 0 hits to 41. Field tags are applied only on the already-broadening OR rung -- tagging the exact rung was tried and reverted, because per-word tagging measured *worse* than PubMed's own automatic term mapping, which translates phrases rather than words (257 hits to 20 on one query). The PubMed client also now emits publication types, so retraction is detectable on that path at all | ✓ | 12:G02/G09, 20:EB-024, 21:R1 |
| G3 | High | incorrect | The `verified` citation label is token overlap; the module described itself as a mock — and it runs on the real path | ✓ | 12:G12/G13/D16, 20:EB-027, 21:R12 |
| G4 | High | missing | **arXiv, bioRxiv, OpenTargets, ClinicalTrials.gov, Semantic Scholar, Crossref, Google Scholar** are named in config with no runnable backend — including OpenTargets and bioRxiv, which Google's product plan names explicitly. **Corrected 2026-09-02**: wrong for three of the seven -- bioRxiv, OpenTargets, and ClinicalTrials.gov are registered in the live config with real, tested MCP backends (`preprint_search`, `open_targets`, `clinical_trials`); only arXiv, Semantic Scholar, Crossref, and Google Scholar are genuinely absent from it (arXiv/Scholar appear only in illustrative `config/examples/*.yaml`). Detail in the 2026-08-05 re-verification log below | ✓ | 12:G01/G03/G04/G06/G07, 20:EB-023, 21:R13, corpus R6-5 |
| G5 | High | partial | No vector, semantic, or hybrid retrieval anywhere — all retrieval and ranking is lexical/heuristic, so irrelevant recent or highly-cited work can win. Fixed as a documented local algorithm, `hybrid-lexical-semantic/1`, following the precedent proximity already sets: the lexical heuristic is kept and a model-judged relevance pass is combined with it, one call per candidate so no schema echoes the pool. Score, rationale, and retriever version are persisted per evidence row. No embedding provider was added -- none is wired, and inventing an undisclosed retrieval provider is outside the evidence boundary | ✓ | 12:G02, 20:EB-024/U26, 21:G3 |
| G6 | High | incorrect | A retracted source can still be reserved, selected, analyzed, and synthesized: the score penalizes retractions but reserved-slot and underfilled-budget paths still choose them. Fixed: retracted candidates are excluded before both admission paths, not merely sorted last, and the reservation is left short rather than padded from another source. Ranking now uses the multi-shape retraction detector rather than the flat flag, which matters because the PubMed path emits none of the richer shapes and so was never demoting anything | ✓ | 12:G21, 20:EB-026 (reproduced), 21:R44 |
| G7 | Medium | incorrect | Knowledge Base evidence links read a nonexistent edge-level `evidence_id`, so links are usually empty. Fixed: the reader iterates the edge's `supporting` span objects and takes `evidence_id` off each, and its docstring records that the edge itself never carries one so reading it there yields nothing silently. The spans are persisted from `SupportSpan.to_dict()` | ✓ | 20:EB-030 |
| G8 | Medium | incorrect | Contradiction insights read nonexistent `claim_text`/`claim_id` instead of the persisted `claim`, producing blank untraceable content | ✓ | 20:EB-031 |
| G9 | Medium | partial | Q&A omits evidence passages yet requests citations; unsupported sources enter context and the offline answer ignores the question. Fixed on all three counts: the manifest carries the evidence passage, so a citation the model is asked for is one it can ground; `unsupported` and `unavailable` sources are withheld from the answer context rather than listed beside citable ones; and the offline answer takes the question and steers which hypotheses and review lead it, instead of rendering run state regardless of what was asked | ✓ | 20:EB-032 |
| G10 | Medium | partial | Literature is gathered once and reused; full/simulation/evolution/ranking perform no live search. Largely closed: targeted mid-run retrieval now runs on the full and simulation review cascade, on deep verification, and on enhancement-through-grounding evolution, all funnelling through one probe that degrades to the run's existing corpus when MCP is down. Ranking still reads only persisted state, which is the intended shape -- a pairwise judge compares two ideas on the evidence already gathered for them | ~ | 12:G09, 21:E10 |
| G11 | Medium | incorrect | Ungrounded runs are not conspicuously marked — a literature failure falls back to latent model knowledge and the report still reads categorically | ✓ | 12:G15/G23 |
| G12 | Low | partial | PMIDs/DOIs are captured but never dereferenced; `available` means only "URL string non-empty". Fixed: `available` is a real dereference now -- DOI through doi.org, PMID through NCBI's ESummary API (the human-facing PubMed page returns 403 to any plain client), a bare URL by status -- run before the drain's transaction opens so no network call holds the write lock. Canonical DOI and PMID, a retrieval timestamp distinct from the insert stamp, and the exact indexed passage are persisted per evidence row | ✓ | 12:G14, 20:EB-027, 21:G8 |
| G13 | Low | missing | AlphaFold and other specialized models absent (Google's evidence for this is qualitative only). Closed as a documented local choice: integrating specialized structure-model retrieval would add an external scientific dependency for qualitative-only fidelity evidence, and the evidence-boundary register forbids inventing undisclosed retrieval providers. `engine/src/co_scientist/config/tools.yaml` carries the documented extension point | = | 12:G05, 20:EB-023, 21:G10 |
| G14 | Low | partial | No durable structured fact/contradiction knowledge base; entity extraction is regex, not NER. Fixed: a durable `knowledge_facts` table derived from claim edges, with supports mapping to a fact and contradicts to a contradiction, entities extracted by the existing engine extractor, cascade-scoped to its run and wiped on re-finalize. Deliberately per-run: cross-run memory is the clone-invented model this register already rejects. Entity extraction stays regex -- no curated biomedical lexicon exists in the tree, and a heavyweight extraction dependency is a larger decision than this row | ✓ | 12:G22, 21:G4 |
| G15 | Medium | partial | The agentic `search_pubmed` MCP tool builds untagged Entrez terms and its `Article` carries no retraction fields, so the draft-generation tool-calling path gets neither the query nor the retraction handling the literature-review path now has | | observed during G2/G6 fix, 2026-08-06 |
| G16 | Low | partial | `assess_resolvability`/`Resolver` in `claims_gate.py` are still unwired into citation classification. The evidence `available` path now dereferences; citation labelling does not | | observed during G12 fix, 2026-08-06 |
| G17 | Low | note | `read_url` fetches the human-facing PubMed host, which returns 403 to any plain HTTP client -- the reason evidence resolution goes through NCBI's ESummary API instead | | observed during G12 fix, 2026-08-06 |

## H. Hypothesis lifecycle — ranking, proximity, evolution

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| H1 | **Critical** | incorrect | **The persisted proximity graph was always empty** — the builder resolved members by a `text` field the schema no longer emitted, so `edges=[]` every run, making `proximity_neighbors` in evolution and the event `clusters` map permanently empty. Reproduced independently by two audits | ✓ | 12:H07/E20/E21, 20:EB-040 (reproduced), 21:R14 (observed `edges=0`) |
| H2 | Medium | partial | Proximity similarity is LLM-judged qualitative (high/medium/low → 0.3/0.6/1.0); no embeddings — a permitted local choice (the paper says "e.g. text embeddings"). The local algorithm is now first-class: `agents/proximity/proximity_graph.py` documents `llm-cluster` v1, every persisted graph records method/version/model/goal provenance, and tests pin the degree→weight mapping and determinism | = | 12:E22, 20:U07, 21:H6 |
| H3 | Medium | incorrect | Proximity dedup rematched cluster members by fragile 100-character text prefix, deleting distinct hypotheses on a false match | ✓ | 12:E21, 20:EB-040 |
| H4 | Medium | partial | Evolution diversity is computed only within the selected top-k and its sampling is unseeded | ✓ | 20:EB-043, 21:R28 |
| H5 | Medium | partial | Ideas can finish with roughly one average match; tournament coverage is thin | ✓ | 12:H02 |
| H6 | Low | note | Elo K fixed at 24 — no annealing, margin scaling, draws, or tie policy. Paper-unspecified, so a permitted local choice, but it departs from the schedule the local corpus documents | ✓ | 12:H03, 20:U08, 21:R48 |
| H7 | Low | incorrect | Match judgments are computed concurrently from pre-round ratings, so later matches in a round cannot observe earlier Elo changes | ✓ | 12:H04 |
| H8 | Low | partial | Evolution reads a tier-scaled set (4/8/12/16), not the paper's fixed top-5 (the research overview's top-10 does match) | ✓ | 12:H09, 21:H10 |
| H9 | Low | partial | The near-duplicate guard is lexical Jaccard | ✓ | 21:K7 |

## I. Memory and feedback propagation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| I1 | **Critical** | incorrect | **The final research overview is built from all hypotheses sorted by Elo**, filtering neither review disposition, deep-verification verdict, claim gate, safety state, nor `is_rankable` — so rejected and safety-blocked content contaminates published prose | ✓ | 12:D19, 20:EB-046 (reproduced) |
| I2 | **Critical** | divergent | **The research overview never feeds back into Generation.** The paper says it does; here `research_overview` is strictly terminal with no consumer. **Behavioral gap closed; the structural claim stands as an accepted divergence.** The feedback channel already existed under another name — `state["meta_review"]` is threaded into every generation strategy — but it carried only critique fields: `emerging_themes` was computed, stored and never rendered into any prompt, and `potential_connections` was requested from the model and discarded before reaching state. So the synthesis content the paper feeds back (which areas are covered, which directions are open) genuinely never arrived, and now does, at zero added LLM cost. The `research_overview` *node* remains terminal by design — running it mid-run buys a second synthesis call for content meta-review already produces. Note the coverage sections are deliberately withheld from the two review prompts: `review_gate.py` scores `novelty`, and that score feeds a sticky never-revisited gate, so "this area is already covered" would penalize an Evolution-origin child for living in the area it was bred to strengthen | ✓ | 21:R4 |
| I3 | High | partial | Recurrent review injects tournament state but its output is write-only (see E1) | ✓ | 12:E14, 20:EB-035, 21:I4 |
| I4 | Medium | incorrect | Response/node caching is on by default with no TTL and no model/prompt/tool/source version invalidation, so more compute can replay cached output instead of exploring. Fixed: the LLM tier gains a TTL and folds the resolved tool contract and a cache schema version into its key, matching what the node tier already did. A stale entry is evicted on read rather than served. Nothing versioning the tool contract behind a prompt was the half that let more compute replay cached output instead of exploring | ✓ | 12:I10/L14, 20:EB-063 |
| I5 | Low | partial | No Elo journal; `matches.iteration` is hard-coded 0 and matches are written only at final drain, so a cancelled run persists zero | | 21:R45 |
| I6 | Low | partial | Debate transcripts exist in state but are never written to SQL — recoverable only from the checkpoint blob | | 12:H05, 21:R46 |
| I7 | Low | partial | No meta-review table; the critique survives only in the report payload and checkpoint | | 21:R46 |
| I8 | Low | partial | Q&A cannot mutate, restart, or branch the research plan | | 12:I08 |

## J. Safety

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| J1 | High | incorrect | The **intake** content policy is materially weaker than the per-hypothesis policy — "design a bioweapon for mass-casualty deployment" blocks per-hypothesis but is only dual-use (a no-op in standard mode) at intake. Fixed: intake now also runs the canonical per-hypothesis classifier and keeps the stricter verdict, so the two agree by construction rather than by two lists kept in step by hand. Measured against the committed adversarial set, intake was worse than this row recorded -- the bioweapon item returned `allow`, not dual-use, and 6 of 7 unsafe items were false negatives; 7/7 are now withheld with no new false positives on the benign controls | ✓ | 21:R16 |
| J2 | High | incorrect | Semantic safety **fails open silently** when the configured model's provider key is absent: regex-only, no log line. A deployment holding one provider's key but not the screen's is regex-only. Fixed closed: a configured semantic screen that cannot reach its model now refuses (`hold`, `requires_review`) and logs at WARNING, sharing one refusal builder with the provider-error path. The offline carve-out is scoped to a process pinned to the offline backend -- that is a deployment mode, not a missing control -- so a partially configured deployment (a provider key present but not the screen's) still refuses | ✓ | 20:EB-048, 21:R17 |
| J3 | High | incorrect | A `redact` decision records the label but persists the original content — the gate proceeds with the same goal and report Markdown. Fixed: redaction is now an effect of the decision rather than something each caller must remember. The intake gate rewrites the persisted goal and the title generated from it; the report path scrubs payload and markdown before publish. A `redact` naming no removable span becomes a `hold` instead of passing the original through under a redaction label. Verified absent from the run row, report markdown, every API payload, SSE and replayed events, the log table, the share payload, and the export; it survives only in the audit record's `matches`, deliberately | ✓ | 12:J07, 20:EB-050 |
| J4 | High | partial | The primary classifier is a regex list; the LLM is an optional escalation. Google's is model-based. Closed within the evidence boundary (safety classifiers and thresholds are withheld, so this matches the invariant and the auditability, never the policy): the model is primary wherever it is stricter, and the deterministic rules are pre-blocks bounding it from below. Previously a permissive model assessment wholly replaced the baseline and could clear a rule-matched `redact`; it may now raise a verdict and never lower one | ✓ | 12:J04, 20:EB-048/EB-049, 21:J2 |
| J5 | Medium | incorrect | `UNCERTAIN` hypotheses are dropped from the pool into `held_for_review`, which is never wired to the app or UI — they vanish silently | ✓ | 12:J06, 21:R34 |
| J6 | Medium | partial | No mid-flight safety monitoring or halt; `safety_blocked` is read but never written, and the meta-review overview is not used as a monitor | ✓ | 12:J12, 20:EB-051, 21:J5 |
| J7 | Medium | partial | Adversarial suite is 13 hand-written, near-tautological items against Google's 1,200 goals / 40 topics plus ~2,000 safe controls. Closed: 49 items across two arms (must-block and a new must-allow control set), split `easy`/`hard`, so a false-positive rate has a denominator for the first time. The measured result is bad and is recorded as `J13` | ✓ | 12:J03, 20:EB-067, 21:R51 |
| J8 | Low | partial | The reviewer `safety` score is collected but no code reads it to reject | ✓ | 21:R52 |
| J9 | Low | missing | MCP / web / PubMed tool calls pass through no safety filter (unattested for Google too) | | 21:J8 |
| J10 | Low | partial | A non-null safety status prevents re-screening after context changes. Not a defect, on evidence: only `redact` and `dual_use` are sticky, and every other status -- including `allow` -- is re-screened when context changes (verified by re-screening an `allow` hypothesis into `prohibited` after its mechanism changed). The remaining skip is deliberate and tested: a redacted hypothesis keeps its verdict because its trigger text is gone, so a fresh review would read ALLOW and silently downgrade an audited decision | = | 20:EB-049 |
| J11 | Low | note | App and engine carry parallel regex implementations that the code itself says should be consolidated | | 12:J09 |
| J12 | Low | note | `hypothesis_state` records no policy version, so bumping `POLICY_VERSION` cannot force a re-screen of hypotheses whose status is sticky (`redact`/`dual_use`) | | observed during J10 verification, 2026-08-06 |
| J13 | **High** | partial | **The deterministic safety layer fails on both arms once probed past literal triggers.** Measured 2026-08-07: FN 1.0 on 12 hard adversarial items, FP 0.833 on 6 hard controls; easy split clean on both, which is why it was invisible. The policy is two-tier: patterns naming an *action* are unconditional blocks; patterns naming only a *category* hold for context. **FN half:** coverage gaps closed (a `\b` spacing defeat, a truncated match window, weapon classes with no pattern, then the spelled-out category names and acquisition/yield/synthesis constructions) — overall FN 0.316 -> 0.211, hard 1.0 -> 0.333. **FP half:** a first attempt reached 0.0 by clearing a category hit to `allow` on a benign marker, which opened a real bypass ("improve the yield of a bioweapon" passed); that was rejected and inverted. The FP fix that shipped instead is a contextual assessor that resolves a Tier B hold in *either* direction (`app/app/hypothesis_safety_resolve.py`), on the reasoning that a Tier B hold asserts the rules cannot tell rather than asserting risk. Deterministic-only FP is unchanged at 0.833 hard and that is now reported as the no-assessor floor; the permissive-assessor ceiling is FP 0.0 / FN 0.263, and `evaluations/safety_eval.py` reports both so the layer's reach is bounded in each direction. Stays `~`: no live measurement of a real assessor's judgment exists, and genuine paraphrase with no literal token remains uncovered by either layer | ~ | measured during J7 expansion, 2026-08-07 |
| J14 | **High** | missing | **Contextual safety escalation did not cover the path that screens almost everything.** `escalate_review` gave a model the final say over a held per-hypothesis verdict but was wired only into the scientist-authored route; the bulk engine drain screened deterministically and nothing else, so the regex verdict was final for the overwhelming majority of a run's output. **Closed by a genuine three-phase split**: deterministic screening and persistence in the drain's first transaction, escalation strictly between the two transactions holding no store connection, and the raised verdicts persisted in the second. Nothing holds the SQLite write lock across the model call. Only a fresh Tier B *held* verdict escalates — an unambiguous allow or a certain block never calls a model — and escalation is fail-closed on provider error, missing credential and offline runs, keeping the deterministic verdict rather than downgrading it. One interaction found while wiring it: an escalation's raise would have been silently undone by a later deterministic re-screen, since the hypothesis text is unchanged and the regex re-derives the same held verdict, so a certain block is now sticky while `UNCERTAIN` stays retryable in case offline/credential eligibility changes between passes | ✓ | observed during J13 remediation, 2026-08-07 |

## K. Scientific output quality

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| K1 | **Critical** | incorrect | Reports state mechanisms categorically while the citation audit shows zero verified claims. One real-provider run: 5 published ideas, 3 PubMed records, **0 verified / 0 partial / 13 unsupported**. Both halves have moved: that distribution is the signature of the Jaccard defect (`G3`), where `verified` and `partial` were arithmetically unreachable, and the classifier now scores claim coverage (`citations.py:107`); an unsupported idea is published with an explicit "Unverified" badge rather than stated flat (`report_content_gates.py:81`). Stays `~`, not `✓`: no live run has produced a fresh verified/partial/unsupported distribution to replace the one this row cites | ~ | 12:K03/K10/D22, 20:EB-029 |
| K2 | High | incorrect | The early review gate is set once from the **first** review and never revisited; a blocking value bars the idea from the tournament for the whole run, hides it as "Disqualified", and shrinks the pool evolution breeds from — one production run's visible symptom was near-identical output, "why is every idea about empagliflozin" (`AGENTS.md`). **Caveat added 2026-09-02, not a correction:** this repo has twice treated near-identical idea titles as a symptom worth fixing here, and via the near-duplicate-guard gotcha in `AGENTS.md` (`evolve.py`'s `other_hypotheses_texts` sampling). Google's own one complete published run shows the identical symptom on its own terms: all 19 hypotheses in the protein-assemblies run carry near-identical titles on a narrow AlphaFold-3-scoring goal, varying only in parameter count and a cosmetic qualifier (corpus R11-1, `docs/CORPUS-EXTRACTION.md:620`; independently corroborated by the full 22-file R14 read, `:899`). Low title diversity on a narrow goal is therefore not, by itself, proof of a local defect — Google's own system produces it too. Whether this repo's guard is *stricter* than Google's stays a genuinely open, undecided question either way; the record should not read as though Google avoided the symptom | ✓ | 12:H11, repo `_apply_initial_review_gate`, corpus R11-1 |
| K3 | High | incorrect | Novelty claims are not verified against a broad current corpus, yet output still uses definitive novelty language. Reopened 2026-08-07 (the earlier tick was unearned: `validate_novelty` runs only under `enable_tool_calling_generation`, which defaults false and the app never sets, and `novelty_validation` is never read in `app/`). **Closed by qualifying the claim, not by grounding it.** Grounding was declined with reason: `validate_novelty` is welded to the tool-calling path's own search plumbing, so reaching the debate path production actually runs would be a re-architecture, and it would add a per-hypothesis literature call. The generation, ranking and review prompts now hedge novelty language, and the report renders an explicit note that novelty reflects the reviewing model's own judgement rather than a literature search. That note is a genuine check for corpus-checked results, not a constant, so it stops rendering by itself if grounding is ever wired through — and it fires identically when MCP is down or the literature kill switch is set, which is where the silent fallback to definitive wording used to live. The review gate's scoring bands are untouched, so this cannot disqualify more ideas or shrink the pool evolution breeds from. Zero added cost. Residual: novelty is still an unaided judgement — it is now labelled as one | ✓ | 12:K08, 21:K2 |
| K4 | Medium | partial | Five default criteria are embedded in prompts and reviews score 8 axes, but only soundness and novelty gate | ✓ | 12:K01, 21:K1 |
| K5 | Medium | incorrect | Feasibility does not reflect the scientist's lab constraints; intake never elicits them and prompts invent feasible-looking methods | ✓ | 12:K05 |
| K6 | Medium | partial | Output is far shorter and shallower than Google's published examples (multi-thousand-word overviews, a 60,000-word MASH export) | ✓ | 12:K11/D18 |
| K7 | Low | partial | The `category` field is optional and absent from the prompt body, so categorization is inconsistent | ✓ | 12:K13, 21:R57 |
| K8 | Low | incorrect | Observation-review positives are stored separately, never appended to the hypothesis as the paper describes | ✓ | 12:H17 |
| K9 | Low | incorrect | Incorrect non-fundamental assumptions do not feed refinement | ✓ | 12:H18 |
| K10 | Low | incorrect | **`hypothesis_state.novelty_score` held a general score, not a novelty score.** The drain persisted `h["score"]`, the engine's overall score, so the column held a different quantity than its name. Closed: it now reads the reviewers' own `novelty` axis, averaged across reviews so a single harsh or generous reviewer cannot define it, and stores nothing rather than a wrong number when no reviewer scored novelty — the case where a reader would most wrongly trust the column name | ✓ | observed during K3 remediation, 2026-08-07 |

## L. Observability and evaluation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| L1 | High | incorrect | The evaluation **release gate exists only in evaluation code**; live finalization uses different rules, so passing evaluator tests does not prove live publication enforcement. Closed by making the evaluator apply the live rules — it imports `EXCLUDED_HYPOTHESIS_STATUSES` and `is_blocking_status` from the modules finalization calls, and mirrors the contradicted-idea and empty-leaderboard rules. Its two invented rules are now reported, not enforced: an 80% verified-claim ratio would have withheld runs production publishes with an "Unverified" badge, and nothing live withholds a report over a missing provenance field | ✓ | 20:OP-045 |
| L2 | High | missing | No token or cost accounting anywhere — `response.usage` is discarded. Fixed: per-call telemetry (prompt/completion/reasoning tokens, estimated cost, latency, retries, cache hit/miss, error kind) is captured at the engine's single dispatch boundary, accumulated in a `ContextVar` scoped to the executing node, and rolled up into `ExecutionMetrics.model_usage` keyed by phase and model. Aggregation is in memory and persists once per task commit, never per call — a row per LLM call is the shape that starved the single SQLite writer in production. The first landing instrumented only `engine.node.*` tasks, which on a real run was 9 of 136 calls, because every fan-out item and ranking match is an app-side handler that never enters `execute_task_node`. Item tasks now carry their snapshot home in their result payload and each aggregate folds them in: 153 attributed dispatches plus 13 cache hits accounts for all 166 | ✓ | 12:F10/L09, 20:EB-061, 21:R35 |
| L3 | Medium | incorrect | `max_llm_calls` undercounts (generation, literature review, and orchestrator allocation do not report), so runs exceed the nominal cap. Fixed: all three report real deltas, threaded through the generation strategies, the literature-review query and synthesis phases, and the planner call; the durable fan-out aggregate had been discarding the generation count entirely. Measured on one identical goal, 304 —> 444 counted calls | ✓ | 20:EB-061, 21:R35 |
| L4 | Medium | missing | No tracing (langsmith installed, never configured), no OTel/Prometheus/Sentry. Fixed by deleting the phantom `langsmith` dependency and the docstring claiming a native integration, and making the L2 telemetry the one real structured seam. Deliberately did not add an OTel or Sentry dependency that nothing configures, which would restate the same defect under another package name | ✓ | 12:L09, 21:R35 |
| L5 | Medium | missing | No per-agent latency; `phase_times` has exactly one producer. Fixed via the L2 rollup — latency is attributed by durable task name, so every node and fan-out phase carries it without retrofitting the single-producer `phase_times` | ✓ | 21:R35 |
| L6 | Medium | partial | `/health` is store-reachability only — a wedged run, failed task, stalled worker, or full disk all report `healthy`. Fixed: read-only, cached queue and disk checks alongside the store and engine checks. Only store unreachability returns 503; queue and disk degradation report `degraded` at 200, because this endpoint is the deploy probe and a failing probe kills the container mid-run | ✓ | 21:R35 |
| L7 | Medium | partial | Eight schemas silently degrade to empty structures after 5 failed attempts, visible only as a WARNING | ✓ | 21:R40 |
| L8 | Medium | missing | No GPQA / Elo-vs-expert-correctness concordance harness. Built as `elo_concordance_eval.py`, but it substitutes a local expert-labelled set for GPQA, which is a permanent gap independent of the harness | ~ | 12:L03, 20:EB-064, 21:R41 |
| L9 | Medium | missing | No controlled multi-budget test-time-scaling curve; adjustable budgets do not prove scaling. Built as `scaling_budget_driver.py` over the real durable path; offline-proven only, so it has produced no live curve yet | ~ | 12:L02, 20:EB-065, 21:L1 |
| L10 | Medium | missing | No blinded expert panel artifact (code exists, no recruited/rated panel) | | 12:L12, 20:EB-066 |
| L11 | Medium | missing | No strategy/tool/meta-review ablations. Built as `ablation_driver.py`; offline-proven only, and meta-review and debate strategy are not independently toggleable, so the sweep covers tools and tier, not every component | ~ | 12:L04 |
| L12 | Medium | incorrect | Evaluation artifacts lack source/env/model/prompt/seed/cost provenance; the golden run reads a secret from an absolute developer path. Closed: `_artifacts.py` stamps git commit/branch/dirty, interpreter, platform, prompt digest, model, seed and cost; the absolute path is gone | ✓ | 20:OP-043 |
| L13 | Medium | incorrect | The parity ledger marked rows verified while citing test symbols that did not exist | ✓ | 20:EB-070/OP-020 |
| L14 | Low | partial | `run_metrics` written only at finalization; no in-flight read. Fixed: the snapshot is written inside the transaction each durable task commit already holds open. Verified live — `llm_calls` observed climbing 113, 317, 349, 459, 551 while the run still reported `running` | ✓ | 21:L7 |
| L15 | Low | missing | No wet-lab / case-study reproduction (external work, not closable in code) | | 12:L12, 20:EB-069 |
| L16 | Low | partial | The pre-ranking evidence gate calls the entailment assessor through `app.claim_verifier` directly rather than through the engine's dispatch boundary, so those calls are counted in `llm_calls` but can never carry token, cost, or latency attribution in `model_usage`. Closing it means routing app-side model calls through the same instrumented seam, not widening the engine's | | 26:S8 |

## M. Product identity and presentation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| M1 | High | divergent | Product identity is teal/blue **"Co-Scientist"**; the target is green **"Hypothesis Generation"** | = | 12:M01/M12, 20:F-ENTRY-01, 21:R19 |
| M2 | High | incorrect | At 16:9 desktop — a supported ratio — report tabs and content clip horizontally; 2:1 is coherent. Closed, and the boundary was the smaller half of it. Unifying the two mismatched breakpoints (720 in Tailwind variants, 700 everywhere else) on 700 made 701-720 worse. Measured in a browser, the split pane's detail column renders 0px at 701, 56px at 721, 172px at 900, 296px at 1024 -- a 656px non-shrinkable floor means it cannot show its own content near either number. One boundary was answering two questions; the columns now stack below 1024 while the phone breakpoint stays 700 | ✓ | 12:M10, 20:F-RESP-01 |
| M3 | High | incorrect | Mobile idea detail has no visible Back; the only escape is re-tapping the already-active tab. Closed -- see O3. The register was right that the run-shell Back was not this escape | ✓ | 20:F-IDEAS-09/F-RESP-03 |
| M4 | Medium | divergent | The shell follows the secondary Gemini Enterprise twin (persistent rail, chat history, three-column ideas), not the Labs product | = | 12:M13, 20:F-ENTRY-03/F-IDEAS-02 |
| M5 | Medium | divergent | An Affiliation modal interrupts first use with an unevidenced organization chooser | = | 20:F-ENTRY-02/F-ENTRY-04 |
| M6 | Medium | incorrect | Demo runs merge into personal history without an `is_demo` label, and ownership middleware exempts them so any caller can mutate shared demo state | | 12:M15/M20, 20:F-ENTRY-06/OP-014/OP-055 |
| M7 | Low | divergent | Invented three-step home onboarding and hard-coded biomedical prompt suggestions | = | 20:F-HOME-01/F-HOME-02 |
| M8 | Low | ext | Dark theme has no Google product evidence | = | 12:M09, 20:F-EXT-03 |
| M9 | Low | ext | `/proposals` renders a static authored graph that can read as scientific Proximity output | = | 20:F-EXT-01 |
| M10 | Low | incorrect | Feedback is SBI-only; the general audience gets no Product Feedback path, no privacy notice, no screenshot option | | 20:F-EXT-02/OP-007 |
| M11 | Low | incorrect | Settings stores a DeepSeek key in the browser and confirms success, but nothing reads it | ✓ | 20:F-HOME-07 |
| M12 | Low | divergent | Undiscoverable global shortcuts (`g n`, arrow tab cycling) may intercept expected navigation. Closed: shortcuts documented in the Settings help section and no longer swallowed from selects, listboxes, comboboxes, sliders, or radio groups. Browser navigation was already safe (modifier chords bail) | ✓ | 20:F-A11Y-08, 21:C11 |

## N. Operations, privacy, packaging, deployment

Raised only by the 2026-07-20 audit, which was the only one to examine these
surfaces.

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| N1 | **Critical** | incorrect | Default `compatibility` auth trusts a caller-selected `X-Client-ID`; a missing header means all such callers share one empty subject; CORS defaults to `*` with credentials. The default running product is spoofable. REOPENED and closed properly 2026-08-06. The first pass closed the query-string and CORS halves; the empty-subject half was still live, and live verification caught it -- a headerless caller read and listed a run another headerless caller had created (200). An empty subject is now the absence of a scope: refused at every create, never matched on any read | ✓ | 20:OP-001/EB-053 |
| N2 | High | incorrect | Bearer credentials accepted as an `access_token` **query parameter** and appended to download/SSE URLs, leaking through history, screenshots, proxy logs, and referrers. Fixed at the server and on the remaining SSE URL; EventSource cannot set headers, so the credential is not simply moved but replaced on that path | ✓ | 20:OP-046 |
| N3 | High | missing | No run/report/document deletion API or UI — users cannot exercise the documented permanent-deletion right | ✓ | 20:OP-008 |
| N4 | High | missing | No retention or cascade policy across events, tasks, checkpoints, reports, attachments, shares, logs, caches, notifications | ✓ | 20:OP-025 |
| N5 | High | incorrect | Uploads: caller-supplied MIME, no signature or malware check, no archive policy, no per-document delete, no at-rest encryption, no provider disclosure. Partly closed: the declared type is verified against the file's actual bytes and a mismatch is refused, and per-document deletion exists. Malware scanning, archive policy, at-rest encryption and provider disclosure remain open | ~ | 20:OP-047 |
| N6 | High | incorrect | Audience is self-declared; the publicly selectable SBI/UCD mode sends committed paper text to every model surface, and the catalog carries no per-document license manifest | ✓ | 20:OP-050 |
| N7 | High | incorrect | MCP server allows wildcard origins/headers/methods with credentials and no auth, relying entirely on network trust; dev Compose publishes port 8888 to the host | ✓ | 20:OP-031 |
| N8 | High | incorrect | Root setup installs the app `--no-deps` then an incomplete manual subset, so `pypdf` is missing and PDF ingestion is silently unavailable despite setup "succeeding" | ✓ | 20:OP-010 |
| N9 | High | incorrect | Forced offline mode still attempts the configured remote chat model for interviews before falling back — leaking goal text. Fixed: one predicate refuses remote chat before the request is shaped, at all three call sites (interview, Q&A, and titling -- titling had the goal as its whole prompt). Each site reuses its existing no-provider degradation rather than adding a second one, and a scientist's own scoped key stays exempt, since forced offline withholds the deployment's credential. Verified at the transport: with forced offline set and two provider keys present, driving all three surfaces produced no non-loopback connection attempt. Nine existing tests were asserting on the shape of a request the app must never make, which is why the suite never caught this | ✓ | 20:OP-013 |
| N10 | High | partial | Production `/status` reported MCP/PubMed/literature/web up but `tools_config=null` and `enabled_tools=null`: specialized tools are registered but not authorized in live runs | ✓ | 20:OP-037 |
| N11 | Medium | missing | No data-access/export request workflow. The export now refuses an identity-less caller rather than exporting the shared empty-subject pool; a silently empty export would read as "you have no data" | ✓ | 20:OP-009 |
| N12 | Medium | incorrect | Feedback is a write-only sink with no privacy notice, triage, ownership, retention, or deletion. Feedback submission stays open (a browser must report its own errors), but its read and delete sides no longer hand one anonymous caller another's notes | ✓ | 20:OP-048 |
| N13 | Medium | incorrect | Log-ingestion rate limiting is keyed to caller-controlled ids, never evicts, and is not shared across replicas | ✓ | 20:OP-049 |
| N14 | Medium | incorrect | Public MCP/API status/root/OpenAPI reveal internal hostname, model names, provider-key presence, and tool config | ✓ | 20:OP-038 |
| N15 | Medium | incorrect | API Dockerfiles do not install Tesseract, so image OCR cannot work in the container; tests fake `pypdf` and miss it | ✓ | 20:OP-011 |
| N16 | Medium | incorrect | Root setup writes a root `.env` while `make dev-api` runs from `app/`, whose settings load the cwd `.env` — generated configuration is silently ignored | ✓ | 20:OP-012 |
| N17 | Medium | incorrect | MCP package: editable install succeeds but setuptools discovers no package; Make/CI change cwd into `engine` to shadow the defect | ✓ | 20:OP-028 |
| N18 | Medium | incorrect | Floating Python base tags, broad unpinned ranges, mutable major Action tags, non-frozen Bun install — identical source can resolve different images | ✓ | 20:OP-029 |
| N19 | Medium | incorrect | `make test-all` covers engine + app only; root lint omits frontend gts; typecheck omits engine mypy | ~ | 20:OP-015/OP-052 |
| N20 | Medium | incorrect | CI path filters omit root Makefiles, Dockerfiles, Vercel config, docs, and corpus | ✓ | 20:OP-016 |
| N21 | Medium | missing | No CI Docker build, Compose smoke, deployment verification, or migration-on-volume gate | ✓ | 20:OP-017 |
| N22 | Medium | incorrect | A unit test asserts NotebookLM/Download are absent while E2E requires them — the two contracts cannot jointly pass | ✓ | 20:OP-018 |
| N23 | Medium | incorrect | Concurrency lease tests use fixed 10-second thresholds, making the green/red signal load-dependent | ✓ | 20:OP-023 |
| N24 | Medium | incorrect | E2E writes screenshots directly into tracked `docs/assets`, so running tests overwrites audit evidence; only one desktop project exists | ✓ | 20:OP-042 |
| N25 | Medium | incorrect | Offline/demo runs are exempted from the empty-leaderboard scientific-readiness block, so demos pass a weaker publication condition | ✓ | 20:OP-041 |
| N26 | Medium | incorrect | Docs describe retired tabs/controls; `FIDELITY.md` denies implemented auth/uploads/durable workers; `ARCHITECTURE.md` claims no durable browser state while four keys are stored | ✓ | 20:OP-019/OP-056 |
| N27 | Medium | incorrect | `.env` templates omit auth, SMTP, quota, and worker settings and still describe retired Mock Mode | ✓ | 20:OP-027 |
| N28 | Medium | incorrect | Dev Compose lacks an explicit SQLite volume, clones a mutable engine at startup, uses reload, and hard-codes the cancer tools config | ✓ | 20:OP-030 |
| N29 | Medium | incorrect | Production images run as root; the API image lacks `HEALTHCHECK` and explicit persistent paths. `HEALTHCHECK` and persistent paths are closed. The non-root half is **reverted in production on the api**: the `USER` switch took the api down for ~20 hours (0/1 replicas, eight consecutive rejected deploys) because Railway mounts the volume over `/app/data` at runtime as root, so an unprivileged process cannot write the SQLite DB and the app dies in its lifespan hook. `RAILWAY_RUN_UID=0` restores service and is now required. Only the mcp image (no volume) actually runs unprivileged | ~ | 20:OP-033 |
| N30 | Medium | partial | The API embeds the worker by default while code comments recommend a separate production worker; deployed docs list only API + MCP | ✓ | 20:OP-034 |
| N31 | Medium | divergent | SQLite WAL with one writer and up to eight workers per run; multi-replica support undefined and recent commits may be lost on power failure | ✓ | 20:OP-035 |
| N32 | Medium | incorrect | Root Vercel config is a universal rewrite and a stale frontend config lists removed routes; the production response carried no CSP, nosniff, referrer, or permissions policy | ✓ | 20:OP-040 |
| N33 | Medium | missing | No non-mutating deployed smoke of production auth, CORS, ownership, MCP, volume/migrations, SMTP, or sanitized share before release | ✓ | 20:OP-026/OP-022 |
| N34 | Medium | partial | MCP CI uses fake HTTP clients; no live PubMed/OpenAlex/INDRA rate-limit or contract smoke | ✓ | 20:OP-039 |
| N35 | Low | incorrect | Engine Compose healthcheck probes `/health`, which the MCP server does not define | ✓ | 20:OP-032 |
| N36 | Low | incorrect | MCP package docs describe a narrower tool surface than what actually registers | ✓ | 20:OP-036 |
| N37 | Medium | missing | The api runs as root in production (`RAILWAY_RUN_UID=0`, see N29) because a build-time `chown` cannot reach a runtime volume mount. Making it genuinely unprivileged needs a root entrypoint that chowns `/app/data` **after** the volume is mounted and then drops to `coscientist` (`gosu`/`setpriv`), with the `USER` line removed so the container starts as root. Deliberately not built during the outage fix: it is a new entrypoint on the only path that binds the port, so it must be proved on a deploy rather than reasoned about | | 08-07 outage |
| N38 | Medium | missing | Nothing alerts on a failed deploy or a 0/1-replica api. Eight deploys were rejected over ~20 hours and every push in that window failed identically regardless of content; the outage surfaced only because a person opened the UI. A deployed smoke exists as N33 but does not run on deploy, and the frontend stays up and green while the api is gone, so the product looks alive | | 08-07 outage |

## O. Accessibility

Raised only by the 2026-07-20 audit.

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| O1 | High | incorrect | Modal overlays support Escape but do not trap focus, inert the background, or restore opener focus. Closed: Tab and Shift+Tab wrap inside the dialog, every ancestor sibling goes inert while it is open, and focus returns on close. Browser-verified, which is what caught the restore landing on `<body>`: the only opener is a menu item whose popover unmounts as the dialog appears, so `focus()` ran on a detached node. It now falls back to the nearest surviving ancestor -- the app shell, not the trigger, which would need the owning component to hand one down | ✓ | 20:F-A11Y-02 |
| O2 | High | incorrect | Idea selection is CSS-only — no selected/current/pressed/listbox semantics, so assistive technology cannot relate the list to the detail pane. Closed as navigation, deliberately not a listbox: the rows are real deep-linkable URLs and a listbox role would owe full listbox keyboard behavior. The selected row now carries `aria-current="page"` plus `aria-controls` naming the detail pane. Browser-verified: exactly one selected row, unselected rows carry neither | ✓ | 20:F-IDEAS-08/F-A11Y-04 |
| O3 | High | incorrect | Return navigation is an undocumented active-tab re-tap with no accessible instruction or semantic control. Closed: the titlebar Back control returns to the ranked list while an idea is open, gated to the phone breakpoint where the detail actually replaces the list (on desktop both are on screen, so Back keeps meaning "leave the run"), and the mobile detail view states the escape | ✓ | 20:F-A11Y-05 |
| O4 | Medium | incorrect | Generic `ShellPopover` applies `role=status` to menus, logs, and forms, turning large interactive regions into noisy live announcements. Closed on five popovers, one more than the register listed -- the share panel hand-rolled the same `role=status`. Browser-verified: the only `role=status` left in the running app is the genuine system-status chip | ✓ | 20:F-A11Y-03 |
| O5 | Medium | incorrect | Continuously growing raw reasoning sits in an `aria-live=polite` region. Closed: the concise label stays announced, the streamed trail moved outside the live region, visually unchanged | ✓ | 20:F-A11Y-07 |
| O6 | Low | partial | Mixed navigation/tab semantics; `aria-current=page` on `<nav>` buttons with no tablist/tabpanel keyboard pattern. Closed as navigation: the strip stays `<nav>` + `aria-current=page` (real URLs, browser-navigable), and what was actually missing -- a name on the content region below it -- is now there. Deliberately not converted to a tablist | ✓ | 20:F-A11Y-06 |

---

## Closed as deliberate local choices

Marked `=` above: `A5`, `A12`, `A14`, `B6`, `C5`, `C7`, `C8`, `D1`,
`D2`, `D3`, `D6`, `D22`, `D25`, `M1`, `M4`, `M5`, `M7`, `M8`, `M9`. (`B1`/`B2`
were removed from this list 2026-09-02 — corrected to `matched`, not a
deliberate divergence; see their rows above.) Each is a
real difference from Google, correctly observed — and each is how this product
is meant to work. They are closed, and [PLAN.md](PLAN.md) does not carry them.

One of them is load-bearing beyond its surface and is worth knowing about while
working anywhere near audience or corpus code: the **`M5` affiliation control
is an access control.** `paper_corpus.disabled_tools_for()` keys corpus access
off the run's audience, so the chooser is what gates one lab's papers from
every other run.

Still open, on merit rather than on fidelity — these add capability rather than
trading one design for another, so each is worth its own judgement: the
interview progress rail (`A1`), an AI/medical disclaimer (`A6`), thumbs feedback
(`A13`), Chat with Agent (`D4`), an expanded Knowledge Base (`D7`), mechanism
diagrams (`D10`), share and download UI (`D11`, `D12`), Summary bucket members
(`D14`), match and lineage views (`D19`, `D20`), a general feedback path (`M10`).

---

## Re-verification 2026-08-05

The three audits read `11a31082` (2026-07-20). `main` is 276 commits past it.
This pass re-read the working tree for every Critical and High finding, plus the
Mediums and Lows a nearby commit made suspect. Findings are cited by the file
that decided the verdict.

### Closed since the audits (`✓`)

| ID | What changed | Evidence |
|---|---|---|
| A4 | The interview is rehydrated from the server on reload | `use_chat_rehydrate.ts:78` calls `getInterview` |
| E3 | Assumptions generation grounds on a reference index and no longer caches | `assumptions.py` — `use_cache=False`, `_resolve_assumptions_context` |
| F8 | `PRAGMA foreign_keys=ON` now runs on every store connection, not just schema init | `store/db.py:97` |
| G3 | Citation classification uses claim coverage, not Jaccard; thresholds restated against it | `citations.py:107` |
| G4 | The unrunnable sources are gone from config — arXiv, bioRxiv, OpenTargets, ClinicalTrials, Semantic Scholar, Crossref, Scholar no longer appear. **Corrected 2026-09-02: wrong for three of the seven.** bioRxiv, OpenTargets, and ClinicalTrials.gov did not disappear — they are registered in the live config with real, tested MCP backends (`preprint_search`, `open_targets`, `clinical_trials`); only arXiv, Semantic Scholar, Crossref, and Google Scholar are genuinely absent from it. arXiv and Google Scholar do still appear, but only in `config/examples/*.yaml` (illustrative bring-your-own-MCP-server deployment examples pointing at a hypothetical `localhost:8889` server, not the runtime `TOOLS_CONFIG` this repo ships or exercises as a live tool call — checked directly, zero `search_arxiv`/`google_scholar_search` implementations exist under `engine/mcp_server/tools/`) | `config/tools.yaml`'s live `search_tools` block declares 3 of the 7 with real `mcp_tool_name` backends (`engine/mcp_server/tools/lit_review/europepmc_search.py:134` `search_preprints`, `engine/mcp_server/tools/systems_biology.py:188` `search_open_targets`, `engine/mcp_server/tools/clinical_trials.py:63` `search_clinical_trials`, each with its own test file); the other 4 have zero hits anywhere in `config/tools.yaml` |
| G8 | Contradiction insights read the persisted `claim` | no `claim_text`/`claim_id` readers remain in `app/` |
| H1, H3 | Cluster members resolve by prompt index, with text only as fallback | `proximity_graph.py`, commits `9ac07d7b`, `e4cda162` |
| K2 | The review gate blocks only the "not viable" band; the rework band is `needs_revision` — rankable and publishable | `review.py:102-125` |
| N8 | `pypdf` is in the single-source dependency list installed after `--no-deps` | `app/requirements-app.txt:32` |
| N22 | The contradiction is gone — no e2e spec requires NotebookLM | only the two unit assertions remain |
| N35 | The Compose MCP healthcheck probes the root, not the undefined `/health` | `docker-compose.yml:87` |

### Partly closed (`~`)

| ID | What moved | What remains |
|---|---|---|
| A2 | `criteria` is collected and threaded into engine opts | not confirmed to reach ranking or debate prompts |
| B3 | The ceiling is one total per identity; it was multiplied per tier, so one id held four times its allowance | the assumed 3 Standard + 1 Advanced split rested on `B1`'s now-corrected two-tier premise (`B1` corrected 2026-09-02 — the product ships four tiers, not two); B3's per-tier-vs-aggregate concurrency-quota question stands independent of that premise and is unaffected by the correction, and the spoofable `X-Client-ID` half is `N1` |
| L2 | `prompt_tokens`/`completion_tokens` are parsed off the response | nothing persists or surfaces them; no cost accounting |
| M3 | A labelled Back control exists in the run shell | resolved 2026-08-06: it now returns to the ranked list while an idea is open, on the phone breakpoint only |
| N19 | `test-all` now covers mcp + parity; `typecheck` covers engine mypy | root `lint` still omits frontend gts |
| O2 | Idea rows carry `aria-current` | resolved 2026-08-06 as navigation, not a listbox: `aria-current="page"` plus `aria-controls` naming the detail pane |

### Re-confirmed open

Verified still present, with the line that proves it:

- **E2** — `generation_debate_and_literature.md` requires `{{user_hypotheses}}`
  and `{{instructions}}`; neither is produced by `_build_debate_base_variables`,
  `_build_debate_literature_variables`, or `_build_debate_guidance_variables`.
  Both render as `{{MISSING:...}}` on every turn.
- **F1** — `store.fail_task` sets the *task* to `failed` and touches no run
  state; nothing else transitions the run. An exhausted task still leaves the
  run `running`.
- **I1** — `research_overview.py:62` passes `state["hypotheses"]` straight to
  `_summarize_top_hypotheses`, which Elo-ranks the whole pool with no
  disposition, safety, or claim filter.
- **I2** — no consumer of `research_overview` in generation or supervisor.
- **E1** — `full_review`/`simulation_review` schemas are produced; no reader
  outside `agents/reflection/`.
- **E5** — five operators (`enhancement`, `simplification`, `combination`,
  `analogy`, `out_of_box`), selected round-robin by `(index + iteration) % 5`.
- **E7** — `meta_review` still absent from proximity, literature review, safety.
- **E8** — novelty grounding still gated on `state["mcp_available"]`
  (`comprehensive_reflection.py:167`, `deep_verification.py:106`).
- **E11** — `enable_tool_calling_generation` is set only in tests.
- **F5** — `performance_assessment` written at `supervisor.py:254`, never read.
- **J5** — `held_for_review` exists throughout the engine and appears nowhere
  in `app/`.
- **D1** — rank and Elo chips still head each row in `ideas_tab.tsx`.
- **D2, D6** — `TABS = ['details', 'learning', 'overview', 'ideas']`;
  `normalizeTab` falls back to `details`.
- **D4, A7** — `askRunQuestion` and `sendRunSteering` have no non-test caller.
- **D5** — `get_shared_report` returns `list_hypotheses` and `list_evidence`
  raw.
- **C1** — `Math.max(seen, phase)` still retains the furthest phase.
- **C6** — `use_run_stream.ts:76` states outright that connection drops are not
  surfaced.
- **N1** — `auth_mode` defaults to `compatibility`.
- **N2** — `access_token` is still read from the query string
  (`auth.py:104`) and appended by the client (`runs_http.ts:39`).
- **N3** — the only `DELETE` route is share revocation.
- **N5** — upload MIME is still caller-supplied.
- **N7** — MCP CORS is still `allow_origins=["*"]` (deliberate, and commented).
- **N24** — one Chromium project in `e2e/playwright.config.ts`.
- **N25** — `report_render.py:405` still exempts offline-backed runs from the
  empty-leaderboard block.

Unchanged and unchecked in this pass: most of B, the Low rows of D, H2/H4–H9,
I4–I8, K3–K9, L4–L15, M-series beyond M3, and N10–N18/N26–N34. Nothing in the
276 commits suggests they moved, but they were not individually re-read.

---

## Confirmed matches — do not break these

Behaviors all three audits independently verified as correct. Two were confirmed
by running the engine, not only by reading it.

| Behavior | Evidence |
|---|---|
| Elo initialises at exactly **1200**, canonical logistic update | 12:H01, 20:M03/EB-037, 21:H1 — **observed** |
| Evolution creates immutable new children with `parent_id`, generation+1, fresh Elo, zero matches; the parent is never mutated; guaranteed by the append-only reducer and locked by tests | 12:E23/H08, 20:M04/EB-042, 21:H8 — **observed** |
| Match pairing prioritises Proximity-similar, newer, and top-ranked ideas | 12:E19, 20:EB-038, 21:H4 |
| Multi-turn debate for top-ranked pairs, single-turn for lower-ranked — genuine multiple round-trips, position-balanced, majority vote | 12:E16, 21:H2 |
| Canonical Supervisor + six specialist roles all present as executing nodes | 12:E01, 21:E1 |
| Meta-review synthesises both review histories and debate transcripts | 20:EB-044/M06, 21:E12 |
| Durable per-run persistence: leases, heartbeats, idempotency, per-node checkpoints, working resume | 20:M02/EB-014, 21:F4/L8 |
| Per-run (not cross-run) context memory — the faithful model; the corpus's cross-run "Ideation Memory" is invented | 12:I09, 20:U16, 21:I8 |
| Claim-level LLM entailment gate (SUPPORTS/CONTRADICTS/INSUFFICIENT) with verbatim-quote provenance and an anti-hallucination span-locate downgrade, on by default | 20:EB-028, 21:G6 |
| Safety decisions persisted across five stages with a working human-adjudication endpoint and UI | 21:J7 |
| Structured hypothesis shape: mechanism-naming title, prose, mechanism, experiment; NIH Specific Aims; author-gated research contacts | 12:D20/D21, 20:M06, 21:K3 |
| Initial review is genuinely tool-free, as specified | 21:E7 |
| Google Sans typography | 12:M11, 21:C3 |
| Private-repository indexing exists (run-scoped) | 21:G9 |

---

## Corpus-integrity corrections

The 2026-07-21 audit established that much of what the corpus's
clone-authored consolidation files (product surface, agent roster,
tournament/evolution, retrieval, etc. — see the region map in
[`docs/CORPUS-EXTRACTION.md`](../CORPUS-EXTRACTION.md)) present as "Google
requirements" is **clone-authored design** with no paper or product basis.
Scoring against these makes the system *less* faithful. Do not treat them as
targets.

| Claimed as Google | Reality |
|---|---|
| 12 agents | The paper specifies **7** (Supervisor + 6) |
| Ideas tab = Elo leaderboard with per-idea Elo/rank/novelty/confidence, tournament viewer, debate transcripts | The product shows a **card list** with `HIGH POTENTIAL`/`NON VIABLE` labels and **no Elo or rank** |
| Standard vs Advanced "Configure Run" form with parameter tables | Product configuration is **conversational**; no run-type form appears in any capture |
| NotebookLM / PDF / Word / LaTeX / BibTeX export | Unattested for this product; NotebookLM underpins *Literature Insights*. **Contested** — current Google Help does list NotebookLM (see D16) |
| 3-persona debate (Innovator / Pragmatist / Contrarian) | The paper specifies debate **turn counts**, never personas |
| Material-3 blue (`#0b57d0`), Spline/DM Sans | Hypothesis Generation reads **green** and uses Google Sans |
| AG-UI / CopilotKit / ~17 SSE event types | Not a Google-stated requirement |
| KSDS blackboard / cross-run "Ideation Memory" | The paper's context memory is **per-run** |
| BRIDGE / M2M / 9-category fidelity harness, GRADE, knowledge-graph novelty math | Clone evaluation design, not Google behavior |
| "Termination predicates unspecified" | The paper **specifies** `MaxIdeas` / `MaxMatchesPerIdea` (values unstated) |

The local `product-surface-and-ux.md` also renders the fourth tab plural
("Run Specifications"); captures show singular, while current Help shows plural.

**A mislabeled media asset, not a clone-authored claim (corpus R13-12(a)).**
The table above is about clone-authored documents mis-describing Google's
*requirements*; this is a different failure — a tracked corpus *file* whose
name mis-describes its own content. `media/hypothesis-generation/`
`esn-poma-hub-hypothesis-full-detail-with-diagram.jpg` does not show an
ESN/POMA-Hub hypothesis detail view: it is a Computational Discovery splash
screen credited to "Carl Elkin". Any future row citing that filename for a
hypothesis-detail-view claim is citing the wrong image. The file is not
renamed or moved (it lives under `references/`, which this pass does not
touch) — this note exists so a reader encounters the mismatch before citing
it, not after.

---

## Open, but not code

Three findings stay open and are deliberately absent from [PLAN.md](PLAN.md),
because no amount of work in this repository closes them. They are the
repository owner's to act on, not an implementer's.

| ID | What it needs |
|---|---|
| `L15` | Wet-lab or case-study reproduction. External scientific work. |
| `L10` | A blinded expert panel. The harness code exists; what is missing is recruited reviewers producing real ratings. |
| `B8` | Production SMTP settings. The completion email is code-complete; `SMTP_*` and `PUBLIC_APP_URL` are unset on the deployment. |

---

## Evidence boundaries — unknowable from public sources

These bound what "1:1" can mean. **Do not convert any of these into a code task
that could falsely "complete" it**, and never present a local choice here as
verified Google behavior.

| Area | Status | Required treatment |
|---|---|---|
| Full production source, models, routing, temperatures, context sizes | proprietary | Never claim literal source parity; close only observable behavior |
| Complete prompt library (only 8 templates are public) | undisclosed | Label all other prompts clone-authored |
| Supervisor features, reward/effectiveness model, portfolio size, sampling formula | undisclosed | Implement published semantics with configurable, recorded policy |
| Standard/Advanced cycle, idea, match, token, cost, latency budgets | undisclosed | Keep reconstructed budgets configurable, versioned, visibly local |
| Elo K-factor, ties, confidence, floors, exact pair schedule | paper-unspecified | Preserve the 1200 core; label and configure everything above it |
| Proximity embedding model, distance, threshold, index, cadence | paper says "e.g. text embeddings" | Require working semantic purpose; document the local algorithm |
| `MaxIdeas` / `MaxMatchesPerIdea` values; definition of "top-ranked" for the debate split | specified but unvalued | Use disclosed loop conditions plus configurable gates |
| Queue, lease, heartbeat, retry, DB, checkpoint implementation | undisclosed | Judge the local design for durability, not storage parity |
| Retrieval providers, reranker, source weights, per-tier budgets | undisclosed | Build a provider-neutral registry; mark undisclosed sources unavailable rather than inventing them |
| Citation schema, DOI reconciliation, claim-entailment model | undisclosed | Calibrate and version local labels |
| Safety classifiers, thresholds, taxonomy, blocked-topic list, redaction wording | withheld | Match invariant and auditability; never claim policy parity |
| Summary tab and Run Specification tab contents | no capture | Strong inference only |
| Export/share affordances; download format(s) | no control in any capture | Implement one truthful format; do not invent a format matrix |
| Pause/resume/cancel/early-stop/mid-run controls in Labs | undocumented | Keep operational controls explicitly local |
| Run progress and ETA computation | footage shows values, not computation | Expose uncertainty; do not present extrapolation as Google-equivalent |
| Token/cost metering shown to users | no meter in captures | Likely not exposed |
| Mobile layout and support; WCAG conformance level | undisclosed | Make local mobile usable; do not claim parity |
| Idea-diagram frequency and generation method | one capture proves existence | Support real artifacts without promising every idea |
| Production latency, uptime, credits, monetary cost, SLOs | proprietary | Match truthful state, not invented numbers |
| Cross-run personalized scientific memory | unresolved, probably per-run | Do not add or claim it without new evidence |
| Collaboration, annotations, branching, team notes | Enterprise-twin evidence only | Optional extensions, isolated from the faithful surface |
| Unbiased distribution of production output quality | not public | Evaluate with blinded experts; never infer parity from showcase outputs |

---

## Where the audits disagreed

| Question | Resolution |
|---|---|
| **Is the async task framework implemented?** 07-20 called it `divergent` (fixed serial spine); 07-21 called it `matched` (real durable queue, arguably more faithful than the corpus's LangGraph design). | Both, at different layers. The **queue** is real and strong — keep it (F4 confirmed match). The **allocator over it** is serial and non-adaptive — that is F4/F5 above. |
| **Is the Ideas tab supposed to be an Elo leaderboard?** 07-12 scored us `partial` for not building a *richer* leaderboard; 07-21 says the leaderboard itself is the divergence. | 07-21 controls. The requirement traces to the local corpus, not to any Google capture. Building a better leaderboard moves away from fidelity. |
| **Is NotebookLM export required?** 07-12 and 07-20 treat it as verified-missing (current Google Help lists it); 07-21 calls it clone-invented for this product. | **Open.** 07-20 cites live Help directly, which outweighs inference — weighted toward "required". Recorded as D16. |
| **`Run Specification` or `Run Specifications`?** 07-21 read singular from captures; 07-20 read plural from current Help. | 07-20 controls — it checked live Help on its audit date. Older footage shows the singular. |
| **Was the 07-12 implementation campaign's work retained?** It reported 86 findings implemented on 07-14; 07-20 and 07-21 found several reverted. | The later audits control. See [README.md](README.md#the-2026-07-12-campaign). |
