# Cross-audit register

One row per distinct finding, mapped across the three audits' ID schemes. This
exists so the same defect does not have to be read three times in three
vocabularies. It **adds** navigation over the source audits; it does not replace
them — the evidence, the `file:line` anchors, and the exact wording stay in the
dated diffs.

**Derived, not re-audited.** Nothing here was independently re-verified against
the current tree. The *Since* column reports commits on `main` whose subject
addresses the finding; a commit existing is not proof the finding is closed.

## ID schemes

| Audit | Scheme |
|---|---|
| [2026-07-12](2026-07-12/FIDELITY-DIFF.md) | `A01`–`M20`, one letter per domain (A goal/interview, B run modes, C monitoring, D report, E coalition, F supervisor, G retrieval, H lifecycle, I memory, J safety, K quality, L scaling/eval, M journey/visual) |
| [2026-07-20](2026-07-20/FIDELITY-DIFF.md) | `F-*` product/frontend, `EB-*` engine/backend, `OP-*` operations; plus `M01`–`M15` credited foundations, `U01`–`U27` evidence boundaries, `G1`–`G10` external sources, `R1`–`R8` runtime observations |
| [2026-07-21](2026-07-21/FIDELITY-DIFF.md) | `R1`–`R58` severity-ordered register; domain rows `A1`–`M6`; `U1`–`U16` unverifiable |

Blank cell = that audit did not raise it (scope or date, not disagreement).

---

## 1. Confirmed matches — behaviors all three audits agree are correct

Guard these. They are the load-bearing invariants a rewrite could silently break.

| Behavior | 07-12 | 07-20 | 07-21 |
|---|---|---|---|
| Elo initialises at exactly 1200, canonical logistic update | `H01` matched | `M03`, `EB-037` | `H1` matched (observed) |
| Evolution creates immutable new children with lineage; parent never mutated | `E23`, `H08` matched | `M04`, `EB-042` matched | `H8` matched (observed) |
| Match pairing prioritises similar / newer / top-ranked | `E19` matched | `EB-038` | `H4` matched |
| Canonical Supervisor + six specialist roles all present | `E01` matched | — | `E1` matched |
| Multi-turn debate for top-ranked, single-turn for lower-ranked | `E16` partial | — | `H2` matched (observed, position-balanced) |
| Meta-review synthesises reviews **and** debate transcripts | `E27` incorrect | `EB-044`, `M06` | `E12` matched |
| Durable per-run persistence, checkpoints, working resume | `I01`, `L05` | `M02`, `EB-013` | `I1`, `L8` matched |
| Per-run (not cross-run) context memory is the faithful model | `I09` extension | `U16` | `I8` matched |
| Structured hypothesis shape: mechanism title + prose + experiment | `H01` matched | — | `K3` matched |

---

## 2. Convergent findings

### 2.1 Interview and goal setup

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **Interview Progress rail absent** — no stepper, no visible field completion | `A03` | `F-INTERVIEW-02` | `R7` (`A4`) | |
| Plan fields not editable; "Edit research plan" opens no editor | `A06` | `F-INTERVIEW-05` | `R38` (`A6`) | |
| Custom evaluation criteria never collected or used to govern ranking | `A08` | `F-INTERVIEW-09`, `EB-006` | `K1` | |
| Field vocabulary drift ("Focus Area" vs "Focus Areas", extra Title) | `A04` | `F-INTERVIEW-07` | `R42` (`A3`) | |
| **No AI/medical disclaimer anywhere** | `J08`, `M03` | `F-HOME-04` | `R22` (`A8`) | |
| Mid-run steering works in the backend but no UI calls it | `A11`, `I05` | `F-RUN-04`, `F-AGENT-03` | `R23` (`A9`) | |
| Scientist hypotheses/reviews: endpoints exist, no UI | `A12`, `A13` | `F-AGENT-03`, `EB-003`, `EB-004` | `A10` | |
| Private corpus is run-scoped keyword search, not "hundreds of PDFs" | `A09`, `A10`, `G19`, `G20` | `EB-025`, `F-HOME-05` | `G9` matched (run-scoped) | |
| Thumbs up/down feedback on turns absent | `M03` | — | `R53` | |
| Interview state not durable in the frontend (reload loses it) | — | `F-INTERVIEW-04`, `F-STATE-01` | — | |

### 2.2 Run configuration

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **Four tiers (express/standard/extended/ultra) replace Google's Standard/Advanced** | `B01`, `B03` | `F-INTERVIEW-08`, `EB-005` | `R8` (`B1`, `B2`) | 07-12 campaign closed this as *implemented*; both later audits found it reverted |
| Four-way focus selector has no Google basis | `A15` | `F-INTERVIEW-08` | `R8` (`B4`) | |
| Concurrency quota is not Google's 3 Standard / 1 Advanced | `B04` | `OP-002`, `OP-054` | — | |
| No credit / refund concept | `B05` | `OP-003` | — | |
| Completion email exists but delivery is unproven | `B06` | `F-INTERVIEW-10`, `OP-004` | — | SMTP still unset in prod |
| Connector toggles are a non-faithful surface (Google's agent picks sources) | — | `F-HOME-06` | `B5` | |

### 2.3 Active run and progress

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **Progress bar indeterminate; "Time remaining" never resolves** | `C02`, `C06` | `F-RUN-01`, `F-RUN-02` | `R36` (`B6`, `L6`) | |
| Progress can move backward across adaptive cycles | `C07` | `F-RUN-06`, `EB-062` | `R36` | |
| Activity log shows internal stage names, no per-item status | `C05`, `C08` | `F-RUN-03` | `R36` (`L6`) | |
| Sources Analyzed / Ideas Explored tiles differ from Google's | `C03`, `C04` | `F-RUN-01` | `L6` | |
| Developer diagnostics (Logs, Offline chip) in the research shell | `C09` | `F-STATE-05`, `F-STATE-06` | — | |
| Report unviewable mid-run (tab bar suppressed) | — | `F-REPORT-02` (landing tab) | `R37` (`C7`) | |

### 2.4 Goal Report surface

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **All four tab labels differ and the order is inverted** | `D01`, `M05`, `M17` | `F-REPORT-01`, `F-SPEC-01` | `R6`, `R43` (`C5`, `C6`) | |
| **`HIGH POTENTIAL` / `NON VIABLE` labels absent from idea cards** | `D03`, `D17`, `M06` | `F-IDEAS-07`, `F-SUMMARY-03` | `R20` (`C8`) | |
| **Ideas presented as an Elo leaderboard; Google hides Elo entirely** | `D02`, `D23` (as a *gap*) | `F-IDEAS-01`, `U09` | `R2` (`D1`) — the single most consequential divergence | `c8800632` stops presenting an unplayed idea's starting Elo as a rating |
| "Verified ideas" tile duplicates the High Potential count | `D04` | `F-SUMMARY-02` | `R29` (`D3`) | `f3c34e24`, `cf29e6a2`, `dc4d84b2` separate explored / released / verified counts |
| Knowledge Base far shallower than Google's; fabricated fallback | `D07`, `D08`, `D09` | `F-KB-01`–`F-KB-05`, `EB-030` | `R30` (`D4`) | `df31e797`, `fcbdb238` |
| Mechanism diagrams (PaperBanana-style) absent | `D05`, `K12` | `F-IDEAS-04` | `R39` (`C10`) | |
| Per-idea "Chat with Agent" / report-level Agent: endpoint exists, no UI | `A14`, `D12`, `D24` | `F-AGENT-01`, `OP-005` | `R23` (`C9`) | |
| Public share: `/shared/:token` renders but nothing mints a token | `D14` | `F-SHARE-01`, `EB-052` | `R50` (`D10`) | |
| Report download / export not linked from any UI | `D15`, `M18` | `F-EXPORT-01`, `OP-006` | `R49` (`D9`) | |
| Research contacts | `D20` | `EB-047` | matched, hallucination-gated | |
| NIH Specific Aims formatting | `D21` | `M06` | `K3`/§8.5 matched | |
| Lineage shown as text only; no tree, parent never linked | — | `F-IDEAS-03` | `R8`ᴅ (`D8`) | `655e39cb` distinguishes deduplicated from disqualified |

### 2.5 Agent coalition and reasoning

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **Full/simulation/recurrent reviews are computed but read by nothing** | `E13`, `E14` | `EB-035` | `R3` (`E6`) | |
| **Deep verification lacks sub-assumption decomposition and decontextualization** | `E11` | `EB-036` | `R9` (`E5`) | |
| Only 5 evolution operators (paper: 6); "inspiration-from-existing" absent | `E24`, `K07` | `EB-041` | `R10` (`E9`) | |
| Enhancement-through-grounding performs no literature retrieval | `E24` | `EB-041` | `R11` (`E10`) | |
| Multi-parent combination structurally crippled (single `parent_id`) | `E25` | `EB-043` | `R27` (`H9`) | |
| Meta-review critique reaches most, not all, agent prompts | `E28`, `I04` | `EB-045` | `R15` (`I2`) | |
| Generation: agentic literature exploration dead; research-expansion a relabel | `E05`, `E08` | `EB-019` | `R33` (`E2`) — confirmed empirically in §8.5 | |
| Assumptions generation is one call, not an iterative sub-assumption tree | `E07` | `EB-021` | `E2` | |
| Debate turn counts fixed, not the paper's 3–5 typical / max 10 | `E06` | `EB-020` | `R26` (`H3`) | `72d8def8` stops debates at convergence and lowers ceilings |
| Full-review novelty grounding depends on MCP being up | `E10`, `G08`, `K02` | `EB-033` | `K2` (`E8`) | |
| Supervisor plan fields stored but never re-read | `E32` | — | `E13`, `F1` | |

### 2.6 Supervisor, orchestration, durability

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **No weighted sampling / adaptive re-weighting; effectiveness computed but unused** | `E04`, `F05` | `EB-009` | `R31` (`F3`) | |
| Supervisor is not an allocator — its prompt forbids planning execution | `E02`, `F04` | `EB-008` | `F1` | |
| Execution is a fixed serial spine choosing one successor at a time | `F01`, `F03`, `F14`, `I02` | `EB-007`, `EB-010` | **see [disagreements](#where-the-audits-disagree)** | |
| **An exhausted durable task leaves the run stuck in `running`** | `F09`, `L08` | `EB-015` (reproduced, `R6`) | `R18` (`L9`) | |
| Approved safety hold has no claimable successor task | `J06` | `EB-016` (reproduced, `R6`) | — | |
| Scientist-submitted hypothesis collides with itself on final drain | — | `EB-003` (reproduced, `R5`) | — | |
| Foreign keys declared but not enforced at runtime | — | `EB-018` | `M6` | |
| Evolution not strictly stagnation-gated | — | — | `R32` (`F7`) | |
| Termination predicate is not the paper's `MaxIdeas`/`MaxMatchesPerIdea` | `F06` unverifiable | `EB-011` | `R48`ᴅ (`F6`) divergent | |

### 2.7 Retrieval, grounding, citations

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **"Verified" citation label is token overlap, not verification** | `G12`, `G13`, `D16` | `EB-027` | `R12` (`G5`) | `00ad64b7`, `9d64032a` replace Jaccard with claim-coverage scoring |
| **Prose sent verbatim to PubMed, which ANDs every token; no broadening retry** | `G02`, `G09` | `EB-024` (framed as no semantic retrieval) | `R1` (`G2`) — rated Critical | `7eec8832`, `8020931e`, `6b211335` add query broadening/relaxation |
| No vector/semantic/hybrid retrieval anywhere | `G02` | `EB-024`, `U26` | `G3` | |
| Sources Google names (OpenTargets, bioRxiv) have no runnable backend | `G01`, `G03`, `G04`, `G06` | `EB-023` | `R13` (`G1`) | |
| AlphaFold / specialized models absent | `G05` | `EB-023` | `G10` | |
| Retraction handling incomplete (OpenAlex filter only) | `G21` | `EB-026` (reserved slots still select them) | `R44` (`G7`) | |
| Claim-level entailment gate exists and is a genuine strength | `G13` (failing at the time) | `EB-028` | `G6` matched | `2a31ca34`, `f89d6ee5`, `83e2839b`, `5218432f` |
| A contradicted / claim-gate-blocked idea can still publish | `G17` | `EB-029` (reproduced, `R1`–`R3`) | — | `cf29e6a2`, `e07c8cb6` make the report agree with itself |
| Evidence IDs and contradiction insights read fields that don't exist | — | `EB-030`, `EB-031` | — | `fcbdb238` derives insights from real claim-evidence columns |

### 2.8 Safety

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| Primary classifier is a regex list; LLM is optional escalation | `J04` | `EB-048`, `EB-049` | `J2` | |
| Adversarial suite is ~13 items against Google's 1,200 goals / 40 topics | `J03` | `EB-067` | `R51` (`J9`) | |
| Two-gate design (intake + per-hypothesis pre-tournament) present | `J01`, `J05` | `EB-048`, `EB-049` partial | `J1` matched | |
| Human adjudication path for held decisions | `J06` | `EB-016` (broken continuation) | `J7` matched | |
| Intake gate materially weaker than the per-hypothesis gate | — | — | `R16` (`J3`) | |
| Semantic safety fails open silently on a missing provider key | — | `EB-048` (offline skips escalation) | `R17` (`J4`) | |
| `UNCERTAIN` hypotheses dropped with no surface | `J05` | — | `R34` (`J6`) | `9d69f2b3`, `1ba63cbd` change how gate outcomes are logged |
| A `redact` decision labels but does not transform content | — | `EB-050` | — | |
| No mid-flight safety monitoring / halt | `J12` | `EB-051` | `R35`ᴅ (`J5`) | |

### 2.9 Observability and evaluation

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **No token, cost, tracing, or per-agent latency accounting** | `F10`, `L09` | `EB-061` | `R35` (`L2`–`L4`) | `78ca3b96` adds worker-cohort occupancy to the latency benchmark |
| `max_llm_calls` undercounts, so runs exceed the nominal cap | — | `EB-061` | `R35` (`L5`) | `2a31ca34` counts entailment calls against the budget |
| GPQA / Elo-vs-expert concordance harness absent | `L03` | `EB-064` | `R41` (`L12`) | |
| Controlled test-time-scaling curve absent | `L02` | `EB-065` | `L1` | |
| Blinded expert panel absent | `L12` | `EB-066` | `L12` | |
| Wet-lab / case-study validation not reproduced | `L12` | `EB-069` | — | |
| Parity ledger cites test symbols that do not exist | excluded by audit rules | `EB-070`, `OP-020` | not credited | |
| Schemas silently degrade to empty structures after repeated LLM failure | — | — | `R40` (`L10`) | |
| Compiled LangGraph never invoked for real runs (dead code) | — | `EB-007` | `R54` (`M2`) | **removed** by `4d6ed845` |

### 2.10 Product identity and presentation

| Finding | 07-12 | 07-20 | 07-21 | Since |
|---|---|---|---|---|
| **Green "Hypothesis Generation" vs teal/blue "Co-Scientist"** | `M01`, `M12` | `F-ENTRY-01` | `R19` (`C1`, `C2`) | |
| Shell copies the Gemini Enterprise twin, not the Labs product | `M13` | `F-ENTRY-03`, `F-IDEAS-02` | — | |
| Dark theme has no Google product evidence | `M09` | `F-EXT-03` | — | |
| Demo runs blend into the scientist's own history | `M15`, `M20` | `F-ENTRY-06`, `OP-014`, `OP-055` | — | |
| Responsive: 16:9 desktop clips; mobile detail has no Back | `M10` | `F-RESP-01`, `F-RESP-03`, `F-IDEAS-09` | — | |
| Affiliation/audience gate blocks the core journey | — | `F-ENTRY-02`, `F-ENTRY-04` | — | |
| Google Sans typography | `M11` | — | `C3` matched | |

---

## 3. Single-audit findings

Not duplicated here — these are whole areas only one audit covered. Go to the
source.

| Area | Audit | IDs |
|---|---|---|
| **Operations, privacy, packaging, CI, deployment** — 56 findings incl. spoofable default auth, no run deletion or data export, bearer token in URLs, unauthenticated MCP, unreproducible builds, `test-all` covering only engine+app | 07-20 | `OP-001`–`OP-056` |
| **Accessibility** — focus traps, `role=status` on interactive popovers, unannounced selection, raw reasoning in an `aria-live` region | 07-20 | `F-A11Y-01`–`F-A11Y-08` |
| **Corpus-integrity corrections** — what the local `references/` corpus invents and attributes to Google | 07-21 | §4 |
| Grounded-debate prompt renders `{{MISSING:...}}` and drops user hypotheses | 07-21 | `R5` (`K5`) |
| Assumptions generation ungrounded on the durable path and cacheable | 07-21 | `R21` (`K6`) |
| Parallel-debate diversity angles inert in production | 07-21 | `R28` (`H11`) |
| Research overview never feeds back into Generation | 07-21 | `R4` (`I3`) |
| Ranking judge's 7 criteria collected but never parsed | 07-21 | `R47` (`E11`) |
| Debate `HYPOTHESIS` termination token instructed but never parsed | 07-21 | `R24` (`E14`) |
| Elo journal, debate transcripts, meta-review not persisted to SQL | 07-21 | `R45`, `R46` (`I5`–`I7`) |
| Browser-local DeepSeek BYOK control that nothing reads | 07-20 | `F-HOME-07` |
| Per-topic reference renumbering breaks `[n]` traceability | 07-20 | `F-KB-03` |
| Ablation studies (generation strategies, search, debate, evolution, proximity, meta-review) | 07-12 | `L04` |

---

## Where the audits disagree

| Question | Position | Resolution |
|---|---|---|
| **Is the async task framework implemented?** | 07-20 `EB-007` calls it `divergent`: a fixed serial bootstrap with one selected successor is not the disclosed coalition. 07-21 `F4` calls it `matched` and "arguably more faithful than the LangGraph design the local corpus proposes." | Both are right about different layers. The *durable queue* (leases, heartbeats, idempotency, checkpoints) is real and strong — 07-20 credits it separately as `M02`/`EB-014`. The *scheduling policy* over it is serial and non-adaptive, which is 07-20's point and 07-21's `F3`/`R31`. Treat the queue as matched and the allocator as missing. |
| **Is the Ideas tab supposed to be an Elo leaderboard?** | 07-12 `D02` treats the full Elo leaderboard as the *target* and scores us `partial` for not reaching it. 07-21 `R2` says Google deliberately hides Elo and the leaderboard is clone-invented, making our leaderboard a `non-faithful-extension`. | 07-21 controls. Its §4 traces the leaderboard requirement to the local corpus, not to any Google capture. Building a richer leaderboard moves *away* from fidelity. |
| **Is NotebookLM export a requirement?** | 07-12 `D13`/`M18` and 07-20 `OP-005` treat it as a verified missing feature (Google Help lists it). 07-21 §4 calls it clone-invented for this product, belonging to *Literature Insights*. | Unresolved. 07-20 cites current Google Help (`G3`) directly, which is stronger than 07-21's inference. Treat as **open**, weighted toward 07-20. |
| **Report tab name: singular or plural?** | 07-21 `C5` says `Run Specification` (singular, from captures). 07-20 `F-SPEC-01` says current Help uses `Run Specifications` (plural) and older footage the singular. | 07-20 controls — it checked live Help on its audit date. |
| **Is deep verification's gate working?** | 07-20 `EB-036` adds that it runs before first ranking (all Elo tied) and fails open on provider error. 07-21 `E5` only faults the missing decomposition. | Additive, not contradictory — take both. |
| **Was the 07-12 campaign's work retained?** | 07-12 `FINAL-STATUS` reports 86 findings implemented. 07-20 found several reverted. | 07-20/07-21 control on tree state. See the [README](README.md#why-the-07-12-campaigns-closure-claims-do-not-hold). |

---

## Consolidated priority order

The three roadmaps agree on shape: **fix what silently corrupts the science
first, then durability, then the visible product, then architecture, then
evaluation.** Merged, deduplicated, and mapped to the source phases:

| # | Theme | 07-12 | 07-20 | 07-21 |
|---|---|---|---|---|
| 1 | One canonical release gate: nothing blocked, retracted, or unsupported reaches a leaderboard, report, overview, share, or export | 1 | `P0` | `T0.4`, `T0.10` |
| 2 | Grounding correctness: PubMed query construction, the `{{MISSING}}` debate prompt, ungrounded+cached assumptions, empty proximity graph, inert diversity angles | 1, 5 | `P3` | `T0.1`–`T0.3`, `T0.6`, `T0.7` |
| 3 | Durable-state correctness: task exhaustion settles the run, safety holds resume, manual input does not collide, steering is exactly-once | 11 | `P1` | `T0.8` |
| 4 | Safety: intake parity, fail-closed on missing credentials, wire `held_for_review`, make `redact` transform | 12 | `P0`, `P1` | `T0.9` |
| 5 | Product surface: tab names and order, card list with `HIGH POTENTIAL`/`NON VIABLE`, hide Elo, Interview Progress, disclaimer, green identity, Agent follow-up, share/export/delete | 6–9, 13 | `P4`, `P5` | `T1.1`–`T1.10` |
| 6 | Adaptive asynchronous coalition: a Supervisor that allocates a portfolio from measured yield | 2 | `P2` | `T2.*` |
| 7 | Engine fidelity: sub-assumptions, the 6th evolution operator, multi-parent combination, meta-review to every agent, debate turn ranges | 4 | `P3` | `T2.1`–`T2.5` |
| 8 | Observability: tokens, cost, per-agent latency, honest `max_llm_calls`, live metrics | 3 | `P2`, `P6` | `T3.*` |
| 9 | Packaging, CI, deployment, privacy, data lifecycle | 13 | `P6` | `T3.*` |
| 10 | Evaluation: GPQA/Elo concordance, scaling curve, blinded experts, 1,200-goal safety set | 15 | `P6` | `T3.*` |
| 11 | Documentation and extension containment; keep every `U*` boundary open | 14 | `P7` | §7 |

**All three audits insist on the same ordering constraint:** do not do #5 before
#1–#4. Visual polish over an unsafe publication path preserves the wrong product.
