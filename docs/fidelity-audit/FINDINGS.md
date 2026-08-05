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
on `main` since, `~` = partly addressed, `?` = contested between audits.
`Src` — provenance in the source audits (`12:`/`20:`/`21:` = audit date).

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
| A2 | High | missing | Custom evaluation criteria never collected; `criteria: []` hard-coded, so no rubric governs ranking, debates, or self-improvement | ~ | 12:A08, 20:F-INTERVIEW-09/EB-006, 21:K1 |
| A3 | Medium | incorrect | Plan fields read-only; "Edit research plan" opens no editor and `editInterviewFields` is unused | | 12:A06, 20:F-INTERVIEW-05, 21:R38 |
| A4 | Medium | missing | Interview lives only in React route state; reload discards it although the server still has it (`getInterview` never called) | ✓ | 20:F-INTERVIEW-04/F-STATE-01 |
| A5 | Medium | incorrect | Raw provider chain-of-thought streamed to the user; Google's footage shows only a "Thinking" status | | 20:F-INTERVIEW-03/U23 |
| A6 | Medium | missing | No AI/medical disclaimer anywhere ("AI can be inaccurate…" / "Consult a professional…") | | 12:J08/M03, 20:F-HOME-04, 21:R22 |
| A7 | Medium | partial | Mid-run steering changes agent behavior but no UI calls `sendRunSteering` | | 12:A11/I05, 20:F-RUN-04, 21:R23 |
| A8 | Medium | partial | Scientist hypotheses/reviews: endpoints and safety admission exist, no UI | | 12:A12/A13, 20:F-AGENT-03, 21:A10 |
| A9 | Medium | partial | Attachments upload only *after* run creation and never ground the interview or plan, though the UI implies they do | | 20:F-HOME-05, 20:EB-025 |
| A10 | Medium | partial | Private corpus is run-scoped BM25 keyword search — not an indexed hundreds-of-PDFs, multimodal, agent-searchable repository | | 12:A09/A10/G19/G20, 20:EB-025, 21:G9 |
| A11 | Medium | incorrect | Create → upload → start is non-transactional; partial failure neither rolls back nor surfaces the orphan draft | | 20:F-INTERVIEW-12 |
| A12 | Low | partial | Field vocabulary drift: "Focus Area" singular vs Google's "Focus Areas"; extra Title field | | 12:A04, 20:F-INTERVIEW-07, 21:R42 |
| A13 | Low | missing | No thumbs up/down on interview turns | | 12:M03, 21:R53 |
| A14 | Low | divergent | Composer copy differs ("What breakthrough should we make today?" vs "What's your research challenge?"); a decorative lock icon implies encryption that does not exist | | 12:M02, 20:F-HOME-01, 21:A1 |
| A15 | Low | incorrect | Retry duplicates the same assistant string instead of re-running the model | | 20:F-INTERVIEW-06 |
| A16 | Low | incorrect | Keyless/offline interview silently degrades to a canned 3-question script with no UI signal | | 12:A05, 21:R56 |
| A17 | Low | incorrect | Home composer stays active after start and keeps posting turns to the completed interview | | 20:F-AGENT-02 |
| A18 | Low | note | No interview turn cap; a model that never sets `completed` interviews indefinitely | | 21:R58 |

## B. Run configuration and lifecycle

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| B1 | High | ext | Four tiers (`express/standard/extended/ultra`) replace Google's exactly-two Standard/Advanced; Google's config is conversational, with no settings form | | 12:B01/B03, 20:F-INTERVIEW-08/EB-005, 21:R8 |
| B2 | Medium | ext | Four-way focus selector (evidence/balance/novelty/breakthrough) has no Google basis | | 12:A15, 21:R8 |
| B3 | Medium | missing | Concurrency quota is one aggregate ceiling, not Google's 3 Standard + 1 Advanced; counted per spoofable client id *and* per profile, so one id can reserve 40 | | 12:B04, 20:OP-002/OP-054 |
| B4 | Medium | divergent | Compute envelope far below Google's several-hour scale | | 12:B07, 20:EB-011 |
| B5 | Medium | incorrect | The generator caches its compiled graph and MCP availability, so configuration changes silently execute a stale topology | | 20:EB-012 |
| B6 | Low | ext | Connector toggles (PubMed / Web / Lab papers) — Google's agent selects sources, naming them in plan prose | | 20:F-HOME-06, 21:B5 |
| B7 | Low | missing | No credit / charge / refund / account-ledger concept | | 12:B05, 20:OP-003 |
| B8 | Low | partial | Completion email is implemented but delivery unproven; SMTP unset in production | | 12:B06, 20:F-INTERVIEW-10/OP-004 |
| B9 | Low | partial | Status vocabulary is a superset (extra `synthesizing`/`blocked`, `aborted`→`cancelled`); failed/cancelled/blocked runs still render full report tabs | | 12:B10, 20:F-STATE-03/F-RUN-07, 21:C4 |
| B10 | Low | partial | Pause/resume/cancel exist in the backend with no UI — and are not evidenced for Google either | | 12:B09, 20:U14 |

## C. Active run and progress

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| C1 | Medium | incorrect | Progress moves **backward**: fixed phase constants let deep verification report 81–84 then proximity 75–85, and the home card retains the furthest phase with `Math.max` | | 12:C06/C07, 20:F-RUN-06/EB-062, 21:R36 |
| C2 | Medium | incorrect | "Time remaining" is permanently "Estimating…"; where computed it is naive linear extrapolation over uneven tasks | | 12:C02, 20:F-RUN-02, 21:R36 |
| C3 | Medium | partial | Progress bar permanently indeterminate ("Progress pending") vs Google's determinate bar | | 12:C01, 20:F-RUN-01, 21:R36 |
| C4 | Medium | divergent | Activity log exposes internal stage names and raw task strings ("Engine Node Generate"); no per-item `EXECUTING` / `-- : --` status | | 12:C05/C08, 20:F-RUN-03, 21:R36 |
| C5 | Medium | divergent | Report and ideas unviewable mid-run — the tab bar is suppressed until the run settles | | 21:R37 |
| C6 | Medium | missing | No live/reconnecting/stale indicator; SSE reconnects silently so a frozen page looks healthy | | 20:F-RUN-05 |
| C7 | Low | partial | Tiles differ from Google's exact three (Time remaining / Sources Analyzed / Ideas explored) | | 12:C03/C04, 20:F-RUN-01, 21:L6 |
| C8 | Low | ext | Developer diagnostics (Logs popover, Offline chip) inside the research shell | | 12:C09, 20:F-STATE-05/F-STATE-06 |

## D. Goal Report surface

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| D1 | **Critical** | ext | **Ideas is an Elo leaderboard with rank + "Elo rating: N" chips. Google deliberately hides Elo and shows a card list.** The single most consequential product divergence — and the local reference corpus's "Elo leaderboard" requirement is clone-invented | | 12:D02/D23, 20:F-IDEAS-01/U09, 21:R2 |
| D2 | High | divergent | All four tab labels differ and the order is inverted: `Goal Details / Learning / Research Overview / All Ideas` vs `Ideas / Knowledge Base / Summary / Run Specification(s)` | | 12:D01/M05, 20:F-REPORT-01, 21:R6 |
| D3 | High | missing | `HIGH POTENTIAL` / `NON VIABLE` pills absent from idea cards; buckets survive only as report counts | | 12:D03/D17/M06, 20:F-IDEAS-07, 21:R20 |
| D4 | High | missing | Per-idea and report-level "Chat with Agent": `askRunQuestion` exists with no UI caller | | 12:A14/D12/D24, 20:F-AGENT-01, 21:R23 |
| D5 | High | incorrect | Public share returns raw complete hypotheses and evidence tables rather than the filtered release artifact — leaks blocked ideas, private document text, and run config | | 20:F-SHARE-02/EB-052 |
| D6 | Medium | incorrect | Completed runs land on Goal Details (configuration) instead of Ideas | | 20:F-REPORT-02 |
| D7 | Medium | partial | Knowledge Base renders ≤3 sections vs Google's 12+; no sticky navigator, no inline citation chips | | 12:D07, 20:F-KB-01/F-KB-04, 21:R30 |
| D8 | Medium | incorrect | With no synthesis, the UI fabricates "learning" sections from the first three evidence abstracts — presentation output indistinguishable from an engine result | | 12:D08, 20:F-KB-02 |
| D9 | Medium | incorrect | KB reference numbers restart at 1 per topic while linking to global evidence rows, so a shown `[1]` can open `[5]` | | 20:F-KB-03 |
| D10 | Medium | missing | Mechanism diagrams absent (Google renders a generated multi-panel figure, "Generated by PaperBanana") | | 12:D05/K12, 20:F-IDEAS-04, 21:R39 |
| D11 | Medium | partial | Public share token cannot be minted from any UI or CLI | | 12:D14, 20:F-SHARE-01, 21:R50 |
| D12 | Medium | partial | Report download/export exists as an endpoint but no UI links it; no PDF/DOCX/CSV | | 12:D15, 20:F-EXPORT-01/OP-006, 21:R49 |
| D13 | Medium | incorrect | Idea detail labels a single row "Full review", hiding the independent/comprehensive/deep results and misrepresenting verification depth | | 20:F-IDEAS-05 |
| D14 | Medium | missing | Summary collapses High Potential / Non-Viable to counts, discarding the ideas and the rationales — the main decision explanation | | 12:D04, 20:F-SUMMARY-03 |
| D15 | Medium | incorrect | "Verified ideas" tile displayed the same number as "High Potential" | ✓ | 12:D04, 20:F-SUMMARY-02, 21:R29 |
| D16 | Medium | ? | NotebookLM handoff absent — **contested**: current Google Help lists it, 21 §4 argues it belongs to *Literature Insights*, not this product | ? | 12:D13/M18, 20:OP-005, 21:§4 |
| D17 | Low | partial | Tab nav labels contradict the documents' own `<h2>` headings (the "Learning" tab is headed "Knowledge Base") | | 12:M17, 20:F-SPEC-01, 21:R43 |
| D18 | Low | partial | `Evidence.available` never surfaced, so unreachable sources look accessed | | 20:F-KB-05, 21:G8 |
| D19 | Low | partial | Match history, opponents, Elo deltas, and debate transcripts are not inspectable | | 12:D23, 20:F-IDEAS-06, 21:D7 |
| D20 | Low | partial | Lineage is text-only ("evolved from an earlier hypothesis"); the parent is never named or linked and there is no tree | | 20:F-IDEAS-03, 21:D8 |
| D21 | Low | incorrect | Origin labels can leak raw engine keys (`generate`/`evolve` vs the mapped `generation`/`evolution`) | | 20:F-IDEAS-11 |
| D22 | Low | ext | Claim spans, cluster IDs, safety internals, and lineage blocks reshape the primary idea detail; Google exposes none of these | | 12:D06, 20:F-IDEAS-12 |
| D23 | Low | partial | Sections rail has no scroll-spy or active state | | 20:F-IDEAS-10 |
| D24 | Low | partial | Winning ideas render as read-only text with no navigation to the idea or its rationale | | 20:F-SUMMARY-05 |
| D25 | Low | ext | Safety adjudication controls live inside report specifications, replacing target content and weakening the reviewer boundary | | 20:F-SPEC-04 |
| D26 | Low | incorrect | Post-run upload is accepted but shows no list/status/removal and no reachable task consumes it | | 20:F-SPEC-05 |

## E. Coalition and reasoning strategies

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| E1 | **Critical** | incorrect | **Full / simulation / recurrent reviews are computed at LLM + retrieval cost and read by nothing** — not ranking, evolution, meta-review, report, or UI. Even fatal findings change no disposition | | 12:E13/E14, 20:EB-035, 21:R3 |
| E2 | **Critical** | incorrect | **The grounded-debate prompt renders `{{MISSING:user_hypotheses}}` and `{{MISSING:instructions}}` on every turn of the production path**, dropping user-supplied starting hypotheses and leaving the instruction slot empty | | 21:R5 |
| E3 | **Critical** | incorrect | **Assumptions generation runs ungrounded on the durable path** even when literature is available, and is cache-enabled — byte-identical output across identical goals | ✓ | 21:R21 |
| E4 | High | partial | Deep verification omits **sub-assumption decomposition** and **decontextualization**, two of its three defining behaviors | | 12:E11, 20:EB-036, 21:R9 |
| E5 | High | partial | Only 5 evolution operators (paper: 6); "inspiration from existing" absent, coherence/feasibility folded into ENHANCEMENT, and round-robin selection means ENHANCEMENT never fires on express | | 12:E24/K07, 20:EB-041, 21:R10 |
| E6 | High | missing | Enhancement-through-grounding performs **no literature retrieval** — only stale run-wide synthesis text | | 12:E24, 20:EB-041, 21:R11 |
| E7 | High | partial | Meta-review critique reaches ~9 of 12 prompt surfaces; **not** Proximity, Literature Review, or Safety, and never the observation node in practice | | 12:E28/I04, 20:EB-045, 21:R15 |
| E8 | High | partial | Full-review novelty grounding happens only when MCP is up; when it is down the system reproduces exactly the un-tooled failure mode Google measured (6.14 → 2.38/10) | | 12:E10/G08/K02, 20:EB-033, 21:K2 |
| E9 | Medium | incorrect | Deep verification runs **before first ranking** (all Elo tied, so "top three" is arbitrary) and fails open on provider error, leaving the idea rankable | | 20:EB-036 |
| E10 | Medium | partial | Multi-parent combination is structurally crippled: single `parent_id`, 200-char peer snippets, a contradictory "stay distinct" directive, and a 0.95 Jaccard rejection gate | | 12:E25, 20:EB-043, 21:R27 |
| E11 | Medium | partial | Agentic literature-exploration generation is dead code (`enable_tool_calling_generation` never set); research-expansion is a relabel with no distinct prompt — confirmed empirically | | 12:E05/E08, 20:EB-019, 21:R33 |
| E12 | Medium | partial | Assumptions generation is one structured call, not an iterative assumption/sub-assumption tree | | 12:E07, 20:EB-021, 21:E2 |
| E13 | Medium | partial | Debate turn counts fixed (5 generation / 3 ranking) vs the paper's 3–5 typical, max 10; the prompt says "max 10" while hard-coding 5 | ~ | 12:E06, 20:EB-020, 21:R26 |
| E14 | Medium | incorrect | Parallel-debate diversity angles are inert on the durable path — each debate task runs with `total_debates=1` | | 21:R28 |
| E15 | Medium | incorrect | Initial-review batch has no 1..5 schema bounds, associates results by order, and lets one exception abort a large batch | | 20:EB-034 |
| E16 | Low | divergent | The debate `HYPOTHESIS` termination token is instructed but never parsed — the loop runs a fixed turn count then re-asks for JSON | | 21:R24 |
| E17 | Low | divergent | Ranking verdict is a JSON enum, not the literal `better idea: <1 or 2>`; the 7 comparison criteria are collected but never parsed | | 12:E18, 21:R25/R47 |
| E18 | Low | partial | Ranking "debate" is one judge re-running the same prompt with prior verdicts; no distinct advocate/opponent roles (correctly, the paper specifies turn counts only) | | 12:E17 |
| E19 | Low | partial | Supervisor plan fields are stored but never re-read (3 of 6 guidance blocks unused) | | 12:E32, 21:E13 |
| E20 | Low | partial | Prompts are reconstructions, not the 8 published Google templates | | 12:E30/E31, 20:U04 |

## F. Supervisor, orchestration, durability

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| F1 | **Critical** | incorrect | **A durable task that exhausts its retries leaves the run stuck in `running` forever** — no `failed` transition, SSE never closes, `cosci runs wait` hangs until a process restart | | 20:EB-015 (reproduced), 21:R18 |
| F2 | High | incorrect | An approved intake/final safety hold has **no claimable successor task** — the holding task already succeeded, so approval reuses a completed idempotency key and nothing resumes | | 12:J06, 20:EB-016 (reproduced) |
| F3 | High | incorrect | A scientist-submitted hypothesis **collides with itself** during final persistence (`UNIQUE constraint failed: hypotheses.id`), preventing completion | | 20:EB-003 (reproduced) |
| F4 | High | divergent | Supervisor is not an allocator — its own prompt says it must **not** plan workflow execution; execution is a fixed serial spine that picks one successor at a time | | 12:E02/F04, 20:EB-008, 21:F1 |
| F5 | High | partial | No weighted sampling or dynamic re-weighting; the per-agent `performance_assessment` that would drive it is computed and unused | | 12:E04/F05, 20:EB-009, 21:R31 |
| F6 | Medium | incorrect | Steering is marked applied **before** the consuming checkpoint commits, so a crash can lose acknowledged steering | | 20:EB-002/EB-017 |
| F7 | Medium | incorrect | Human review score is reconstructed as 20/60/90 from summary words and re-drained as a generic `review`, losing authorship and semantics | | 20:EB-004 |
| F8 | Medium | incorrect | Foreign keys are declared but `PRAGMA foreign_keys=ON` runs only on the schema-init connection, so runtime FKs are off | ✓ | 20:EB-018, 21:M6 |
| F9 | Medium | incorrect | Several fan-outs abort the whole batch on one item failure instead of committing successful siblings | | 12:F09/L08, 20:EB-010/EB-043 |
| F10 | Medium | partial | Evolution is not strictly stagnation-gated — on the common both-zero tie it alternates, so it fires without stagnation | | 21:R32 |
| F11 | Low | divergent | Termination is iteration budget / convergence / LLM-call budget, not the paper's `MaxIdeas` and `MaxMatchesPerIdea` | | 12:F06, 20:EB-011, 21:F6 |
| F12 | Low | note | Dead termination reasons (`CANCELLED`/`SAFETY`/`MAX_TASKS`/`WALL_CLOCK`) exist but their state keys are never written | | 21:F8 |
| F13 | Low | note | The compiled LangGraph was built on every bootstrap but never invoked for real runs | ✓ | 20:EB-007, 21:R54 |

## G. Retrieval, grounding, citations

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| G1 | **Critical** | incorrect | **Claim-gate-blocked hypotheses stay `active` and are released** into the leaderboard, idea buckets, and report. Reproduced: fresh Standard and Ultra runs completed with **all** hypotheses failing the claim gate and **all** claim assessments `insufficient` | ~ | 12:G16/G17, 20:EB-029 (reproduced) |
| G2 | **Critical** | incorrect | **Multi-term natural-language phrases are sent verbatim to Entrez, which ANDs every token** — no MeSH, no OR expansion, no field tags, no broadening retry, and the final fallback sends the whole prose goal. Documented root cause of the ~99% "insufficient" evidence rate | ~ | 12:G02/G09, 20:EB-024, 21:R1 |
| G3 | High | incorrect | The `verified` citation label is token overlap; the module described itself as a mock — and it runs on the real path | ✓ | 12:G12/G13/D16, 20:EB-027, 21:R12 |
| G4 | High | missing | **arXiv, bioRxiv, OpenTargets, ClinicalTrials.gov, Semantic Scholar, Crossref, Google Scholar** are named in config with no runnable backend — including OpenTargets and bioRxiv, which Google's product plan names explicitly | ✓ | 12:G01/G03/G04/G06/G07, 20:EB-023, 21:R13 |
| G5 | High | partial | No vector, semantic, or hybrid retrieval anywhere — all retrieval and ranking is lexical/heuristic, so irrelevant recent or highly-cited work can win | | 12:G02, 20:EB-024/U26, 21:G3 |
| G6 | High | incorrect | A retracted source can still be reserved, selected, analyzed, and synthesized: the score penalizes retractions but reserved-slot and underfilled-budget paths still choose them | ~ | 12:G21, 20:EB-026 (reproduced), 21:R44 |
| G7 | Medium | incorrect | Knowledge Base evidence links read a nonexistent edge-level `evidence_id`, so links are usually empty | | 20:EB-030 |
| G8 | Medium | incorrect | Contradiction insights read nonexistent `claim_text`/`claim_id` instead of the persisted `claim`, producing blank untraceable content | ✓ | 20:EB-031 |
| G9 | Medium | partial | Q&A omits evidence passages yet requests citations; unsupported sources enter context and the offline answer ignores the question | | 20:EB-032 |
| G10 | Medium | partial | Literature is gathered once and reused; full/simulation/evolution/ranking perform no live search | | 12:G09, 21:E10 |
| G11 | Medium | incorrect | Ungrounded runs are not conspicuously marked — a literature failure falls back to latent model knowledge and the report still reads categorically | | 12:G15/G23 |
| G12 | Low | partial | PMIDs/DOIs are captured but never dereferenced; `available` means only "URL string non-empty" | | 12:G14, 20:EB-027, 21:G8 |
| G13 | Low | missing | AlphaFold and other specialized models absent (Google's evidence for this is qualitative only) | | 12:G05, 20:EB-023, 21:G10 |
| G14 | Low | partial | No durable structured fact/contradiction knowledge base; entity extraction is regex, not NER | | 12:G22, 21:G4 |

## H. Hypothesis lifecycle — ranking, proximity, evolution

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| H1 | **Critical** | incorrect | **The persisted proximity graph was always empty** — the builder resolved members by a `text` field the schema no longer emitted, so `edges=[]` every run, making `proximity_neighbors` in evolution and the event `clusters` map permanently empty. Reproduced independently by two audits | ✓ | 12:H07/E20/E21, 20:EB-040 (reproduced), 21:R14 (observed `edges=0`) |
| H2 | Medium | partial | Proximity similarity is LLM-judged qualitative (high/medium/low → 0.3/0.6/1.0); no embeddings (the paper says "e.g. text embeddings", so this is a permitted local choice) | | 12:E22, 20:U07, 21:H6 |
| H3 | Medium | incorrect | Proximity dedup rematched cluster members by fragile 100-character text prefix, deleting distinct hypotheses on a false match | ✓ | 12:E21, 20:EB-040 |
| H4 | Medium | partial | Evolution diversity is computed only within the selected top-k and its sampling is unseeded | | 20:EB-043, 21:R28 |
| H5 | Medium | partial | Ideas can finish with roughly one average match; tournament coverage is thin | | 12:H02 |
| H6 | Low | note | Elo K fixed at 24 — no annealing, margin scaling, draws, or tie policy. Paper-unspecified, so a permitted local choice, but it departs from the schedule the local corpus documents | | 12:H03, 20:U08, 21:R48 |
| H7 | Low | incorrect | Match judgments are computed concurrently from pre-round ratings, so later matches in a round cannot observe earlier Elo changes | | 12:H04 |
| H8 | Low | partial | Evolution reads a tier-scaled set (4/8/12/16), not the paper's fixed top-5 (the research overview's top-10 does match) | | 12:H09, 21:H10 |
| H9 | Low | partial | The near-duplicate guard is lexical Jaccard | | 21:K7 |

## I. Memory and feedback propagation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| I1 | **Critical** | incorrect | **The final research overview is built from all hypotheses sorted by Elo**, filtering neither review disposition, deep-verification verdict, claim gate, safety state, nor `is_rankable` — so rejected and safety-blocked content contaminates published prose | | 12:D19, 20:EB-046 (reproduced) |
| I2 | **Critical** | missing | **The research overview never feeds back into Generation.** The paper says it does; here `research_overview` is strictly terminal with no consumer | | 21:R4 |
| I3 | High | partial | Recurrent review injects tournament state but its output is write-only (see E1) | | 12:E14, 20:EB-035, 21:I4 |
| I4 | Medium | incorrect | Response/node caching is on by default with no TTL and no model/prompt/tool/source version invalidation, so more compute can replay cached output instead of exploring | | 12:I10/L14, 20:EB-063 |
| I5 | Low | partial | No Elo journal; `matches.iteration` is hard-coded 0 and matches are written only at final drain, so a cancelled run persists zero | | 21:R45 |
| I6 | Low | partial | Debate transcripts exist in state but are never written to SQL — recoverable only from the checkpoint blob | | 12:H05, 21:R46 |
| I7 | Low | partial | No meta-review table; the critique survives only in the report payload and checkpoint | | 21:R46 |
| I8 | Low | partial | Q&A cannot mutate, restart, or branch the research plan | | 12:I08 |

## J. Safety

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| J1 | High | incorrect | The **intake** content policy is materially weaker than the per-hypothesis policy — "design a bioweapon for mass-casualty deployment" blocks per-hypothesis but is only dual-use (a no-op in standard mode) at intake | | 21:R16 |
| J2 | High | incorrect | Semantic safety **fails open silently** when the configured model's provider key is absent: regex-only, no log line. A DashScope deployment without `DEEPSEEK_API_KEY` is regex-only | ~ | 20:EB-048, 21:R17 |
| J3 | High | incorrect | A `redact` decision records the label but persists the original content — the gate proceeds with the same goal and report Markdown | ~ | 12:J07, 20:EB-050 |
| J4 | High | partial | The primary classifier is a regex list; the LLM is an optional escalation. Google's is model-based | | 12:J04, 20:EB-048/EB-049, 21:J2 |
| J5 | Medium | incorrect | `UNCERTAIN` hypotheses are dropped from the pool into `held_for_review`, which is never wired to the app or UI — they vanish silently | | 12:J06, 21:R34 |
| J6 | Medium | partial | No mid-flight safety monitoring or halt; `safety_blocked` is read but never written, and the meta-review overview is not used as a monitor | | 12:J12, 20:EB-051, 21:J5 |
| J7 | Medium | partial | Adversarial suite is 13 hand-written, near-tautological items against Google's 1,200 goals / 40 topics plus ~2,000 safe controls | | 12:J03, 20:EB-067, 21:R51 |
| J8 | Low | partial | The reviewer `safety` score is collected but no code reads it to reject | | 21:R52 |
| J9 | Low | missing | MCP / web / PubMed tool calls pass through no safety filter (unattested for Google too) | | 21:J8 |
| J10 | Low | partial | A non-null safety status prevents re-screening after context changes | | 20:EB-049 |
| J11 | Low | note | App and engine carry parallel regex implementations that the code itself says should be consolidated | | 12:J09 |

## K. Scientific output quality

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| K1 | **Critical** | incorrect | Reports state mechanisms categorically while the citation audit shows zero verified claims. One real-provider run: 5 published ideas, 3 PubMed records, **0 verified / 0 partial / 13 unsupported** | | 12:K03/K10/D22, 20:EB-029 |
| K2 | High | incorrect | The early review gate is set once from the **first** review and never revisited; a blocking value bars the idea from the tournament for the whole run, hides it as "Disqualified", and shrinks the pool evolution breeds from | ✓ | 12:H11, repo `_apply_initial_review_gate` |
| K3 | High | incorrect | Novelty claims are not verified against a broad current corpus, yet output still uses definitive novelty language | | 12:K08, 21:K2 |
| K4 | Medium | partial | Five default criteria are embedded in prompts and reviews score 8 axes, but only soundness and novelty gate | | 12:K01, 21:K1 |
| K5 | Medium | incorrect | Feasibility does not reflect the scientist's lab constraints; intake never elicits them and prompts invent feasible-looking methods | | 12:K05 |
| K6 | Medium | partial | Output is far shorter and shallower than Google's published examples (multi-thousand-word overviews, a 60,000-word MASH export) | | 12:K11/D18 |
| K7 | Low | partial | The `category` field is optional and absent from the prompt body, so categorization is inconsistent | | 12:K13, 21:R57 |
| K8 | Low | incorrect | Observation-review positives are stored separately, never appended to the hypothesis as the paper describes | | 12:H17 |
| K9 | Low | incorrect | Incorrect non-fundamental assumptions do not feed refinement | | 12:H18 |

## L. Observability and evaluation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| L1 | High | incorrect | The evaluation **release gate exists only in evaluation code**; live finalization uses different rules, so passing evaluator tests does not prove live publication enforcement | | 20:OP-045 |
| L2 | High | missing | No token or cost accounting anywhere — `response.usage` is discarded | ~ | 12:F10/L09, 20:EB-061, 21:R35 |
| L3 | Medium | incorrect | `max_llm_calls` undercounts (generation, literature review, and orchestrator allocation do not report), so runs exceed the nominal cap | | 20:EB-061, 21:R35 |
| L4 | Medium | missing | No tracing (langsmith installed, never configured), no OTel/Prometheus/Sentry | | 12:L09, 21:R35 |
| L5 | Medium | missing | No per-agent latency; `phase_times` has exactly one producer | | 21:R35 |
| L6 | Medium | partial | `/health` is store-reachability only — a wedged run, failed task, stalled worker, or full disk all report `healthy` | | 21:R35 |
| L7 | Medium | partial | Eight schemas silently degrade to empty structures after 5 failed attempts, visible only as a WARNING | | 21:R40 |
| L8 | Medium | missing | No GPQA / Elo-vs-expert-correctness concordance harness | | 12:L03, 20:EB-064, 21:R41 |
| L9 | Medium | missing | No controlled multi-budget test-time-scaling curve; adjustable budgets do not prove scaling | | 12:L02, 20:EB-065, 21:L1 |
| L10 | Medium | missing | No blinded expert panel artifact (code exists, no recruited/rated panel) | | 12:L12, 20:EB-066 |
| L11 | Medium | missing | No strategy/tool/meta-review ablations | | 12:L04 |
| L12 | Medium | incorrect | Evaluation artifacts lack source/env/model/prompt/seed/cost provenance; the golden run reads a secret from an absolute developer path | | 20:OP-043 |
| L13 | Medium | incorrect | The parity ledger marked rows verified while citing test symbols that did not exist | ✓ | 20:EB-070/OP-020 |
| L14 | Low | partial | `run_metrics` written only at finalization; no in-flight read | | 21:L7 |
| L15 | Low | missing | No wet-lab / case-study reproduction (external work, not closable in code) | | 12:L12, 20:EB-069 |

## M. Product identity and presentation

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| M1 | High | divergent | Product identity is teal/blue **"Co-Scientist"**; the target is green **"Hypothesis Generation"** | | 12:M01/M12, 20:F-ENTRY-01, 21:R19 |
| M2 | High | incorrect | At 16:9 desktop — a supported ratio — report tabs and content clip horizontally; 2:1 is coherent | | 12:M10, 20:F-RESP-01 |
| M3 | High | incorrect | Mobile idea detail has no visible Back; the only escape is re-tapping the already-active tab | ~ | 20:F-IDEAS-09/F-RESP-03 |
| M4 | Medium | divergent | The shell follows the secondary Gemini Enterprise twin (persistent rail, chat history, three-column ideas), not the Labs product | | 12:M13, 20:F-ENTRY-03/F-IDEAS-02 |
| M5 | Medium | divergent | An Affiliation modal interrupts first use with an unevidenced organization chooser | | 20:F-ENTRY-02/F-ENTRY-04 |
| M6 | Medium | incorrect | Demo runs merge into personal history without an `is_demo` label, and ownership middleware exempts them so any caller can mutate shared demo state | | 12:M15/M20, 20:F-ENTRY-06/OP-014/OP-055 |
| M7 | Low | divergent | Invented three-step home onboarding and hard-coded biomedical prompt suggestions | | 20:F-HOME-01/F-HOME-02 |
| M8 | Low | ext | Dark theme has no Google product evidence | | 12:M09, 20:F-EXT-03 |
| M9 | Low | ext | `/proposals` renders a static authored graph that can read as scientific Proximity output | | 20:F-EXT-01 |
| M10 | Low | incorrect | Feedback is SBI-only; the general audience gets no Product Feedback path, no privacy notice, no screenshot option | | 20:F-EXT-02/OP-007 |
| M11 | Low | incorrect | Settings stores a DeepSeek key in the browser and confirms success, but nothing reads it | | 20:F-HOME-07 |
| M12 | Low | divergent | Undiscoverable global shortcuts (`g n`, arrow tab cycling) may intercept expected navigation | | 20:F-A11Y-08, 21:C11 |

## N. Operations, privacy, packaging, deployment

Raised only by the 2026-07-20 audit, which was the only one to examine these
surfaces.

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| N1 | **Critical** | incorrect | Default `compatibility` auth trusts a caller-selected `X-Client-ID`; a missing header means all such callers share one empty subject; CORS defaults to `*` with credentials. The default running product is spoofable | | 20:OP-001/EB-053 |
| N2 | High | incorrect | Bearer credentials accepted as an `access_token` **query parameter** and appended to download/SSE URLs, leaking through history, screenshots, proxy logs, and referrers | | 20:OP-046 |
| N3 | High | missing | No run/report/document deletion API or UI — users cannot exercise the documented permanent-deletion right | | 20:OP-008 |
| N4 | High | missing | No retention or cascade policy across events, tasks, checkpoints, reports, attachments, shares, logs, caches, notifications | | 20:OP-025 |
| N5 | High | incorrect | Uploads: caller-supplied MIME, no signature or malware check, no archive policy, no per-document delete, no at-rest encryption, no provider disclosure | | 20:OP-047 |
| N6 | High | incorrect | Audience is self-declared; the publicly selectable SBI/UCD mode sends committed paper text to every model surface, and the catalog carries no per-document license manifest | | 20:OP-050 |
| N7 | High | incorrect | MCP server allows wildcard origins/headers/methods with credentials and no auth, relying entirely on network trust; dev Compose publishes port 8888 to the host | | 20:OP-031 |
| N8 | High | incorrect | Root setup installs the app `--no-deps` then an incomplete manual subset, so `pypdf` is missing and PDF ingestion is silently unavailable despite setup "succeeding" | ✓ | 20:OP-010 |
| N9 | High | incorrect | Forced offline mode still attempts the configured remote chat model for interviews before falling back — leaking goal text | | 20:OP-013 |
| N10 | High | partial | Production `/status` reported MCP/PubMed/literature/web up but `tools_config=null` and `enabled_tools=null`: specialized tools are registered but not authorized in live runs | | 20:OP-037 |
| N11 | Medium | missing | No data-access/export request workflow | | 20:OP-009 |
| N12 | Medium | incorrect | Feedback is a write-only sink with no privacy notice, triage, ownership, retention, or deletion | | 20:OP-048 |
| N13 | Medium | incorrect | Log-ingestion rate limiting is keyed to caller-controlled ids, never evicts, and is not shared across replicas | | 20:OP-049 |
| N14 | Medium | incorrect | Public MCP/API status/root/OpenAPI reveal internal hostname, model names, provider-key presence, and tool config | | 20:OP-038 |
| N15 | Medium | incorrect | API Dockerfiles do not install Tesseract, so image OCR cannot work in the container; tests fake `pypdf` and miss it | | 20:OP-011 |
| N16 | Medium | incorrect | Root setup writes a root `.env` while `make dev-api` runs from `app/`, whose settings load the cwd `.env` — generated configuration is silently ignored | | 20:OP-012 |
| N17 | Medium | incorrect | MCP package: editable install succeeds but setuptools discovers no package; Make/CI change cwd into `engine` to shadow the defect | | 20:OP-028 |
| N18 | Medium | incorrect | Floating Python base tags, broad unpinned ranges, mutable major Action tags, non-frozen Bun install — identical source can resolve different images | | 20:OP-029 |
| N19 | Medium | incorrect | `make test-all` covers engine + app only; root lint omits frontend gts; typecheck omits engine mypy | ~ | 20:OP-015/OP-052 |
| N20 | Medium | incorrect | CI path filters omit root Makefiles, Dockerfiles, Vercel config, docs, and corpus | | 20:OP-016 |
| N21 | Medium | missing | No CI Docker build, Compose smoke, deployment verification, or migration-on-volume gate | | 20:OP-017 |
| N22 | Medium | incorrect | A unit test asserts NotebookLM/Download are absent while E2E requires them — the two contracts cannot jointly pass | ✓ | 20:OP-018 |
| N23 | Medium | incorrect | Concurrency lease tests use fixed 10-second thresholds, making the green/red signal load-dependent | | 20:OP-023 |
| N24 | Medium | incorrect | E2E writes screenshots directly into tracked `docs/assets`, so running tests overwrites audit evidence; only one desktop project exists | | 20:OP-042 |
| N25 | Medium | incorrect | Offline/demo runs are exempted from the empty-leaderboard scientific-readiness block, so demos pass a weaker publication condition | | 20:OP-041 |
| N26 | Medium | incorrect | Docs describe retired tabs/controls; `FIDELITY.md` denies implemented auth/uploads/durable workers; `ARCHITECTURE.md` claims no durable browser state while four keys are stored | | 20:OP-019/OP-056 |
| N27 | Medium | incorrect | `.env` templates omit auth, SMTP, quota, and worker settings and still describe retired Mock Mode | | 20:OP-027 |
| N28 | Medium | incorrect | Dev Compose lacks an explicit SQLite volume, clones a mutable engine at startup, uses reload, and hard-codes the cancer tools config | | 20:OP-030 |
| N29 | Medium | incorrect | Production images run as root; the API image lacks `HEALTHCHECK` and explicit persistent paths | | 20:OP-033 |
| N30 | Medium | partial | The API embeds the worker by default while code comments recommend a separate production worker; deployed docs list only API + MCP | | 20:OP-034 |
| N31 | Medium | divergent | SQLite WAL with one writer and up to eight workers per run; multi-replica support undefined and recent commits may be lost on power failure | | 20:OP-035 |
| N32 | Medium | incorrect | Root Vercel config is a universal rewrite and a stale frontend config lists removed routes; the production response carried no CSP, nosniff, referrer, or permissions policy | | 20:OP-040 |
| N33 | Medium | missing | No non-mutating deployed smoke of production auth, CORS, ownership, MCP, volume/migrations, SMTP, or sanitized share before release | | 20:OP-026/OP-022 |
| N34 | Medium | partial | MCP CI uses fake HTTP clients; no live PubMed/OpenAlex/INDRA rate-limit or contract smoke | | 20:OP-039 |
| N35 | Low | incorrect | Engine Compose healthcheck probes `/health`, which the MCP server does not define | ✓ | 20:OP-032 |
| N36 | Low | incorrect | MCP package docs describe a narrower tool surface than what actually registers | | 20:OP-036 |

## O. Accessibility

Raised only by the 2026-07-20 audit.

| ID | Sev | Class | Gap | St | Src |
|---|---|---|---|---|---|
| O1 | High | incorrect | Modal overlays support Escape but do not trap focus, inert the background, or restore opener focus | | 20:F-A11Y-02 |
| O2 | High | incorrect | Idea selection is CSS-only — no selected/current/pressed/listbox semantics, so assistive technology cannot relate the list to the detail pane | ~ | 20:F-IDEAS-08/F-A11Y-04 |
| O3 | High | incorrect | Return navigation is an undocumented active-tab re-tap with no accessible instruction or semantic control | | 20:F-A11Y-05 |
| O4 | Medium | incorrect | Generic `ShellPopover` applies `role=status` to menus, logs, and forms, turning large interactive regions into noisy live announcements | | 20:F-A11Y-03 |
| O5 | Medium | incorrect | Continuously growing raw reasoning sits in an `aria-live=polite` region | | 20:F-A11Y-07 |
| O6 | Low | partial | Mixed navigation/tab semantics; `aria-current=page` on `<nav>` buttons with no tablist/tabpanel keyboard pattern | | 20:F-A11Y-06 |

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
| G4 | The unrunnable sources are gone from config — arXiv, bioRxiv, OpenTargets, ClinicalTrials, Semantic Scholar, Crossref, Scholar no longer appear | `config/tools.yaml` declares only backed tools |
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
| G1 | Contradicted ideas are now withheld; merely-unsupported ones publish with an "Unverified" badge | this is a **re-scope, not a fix** — a claim-gate block still does not suppress release, it relabels it. Confirm the badge is the intended policy |
| G2 | A progressive broadening ladder retries queries that return nothing | still no MeSH, OR expansion, or field tags; prose-goal fallback unre-checked |
| G6 | Retraction detection exists across metadata shapes | the reserved-slot and underfilled-budget admission paths were not re-traced |
| J2 | The provider-credential table is unified, so a DashScope deployment resolves correctly | still fails open to regex-only, still with no log line |
| J3 | The engine redacts hypothesis fields in place | app-side goal and report-Markdown redaction not confirmed |
| L2 | `prompt_tokens`/`completion_tokens` are parsed off the response | nothing persists or surfaces them; no cost accounting |
| M3 | A labelled Back control exists in the run shell | not confirmed as the mobile idea-detail escape |
| N19 | `test-all` now covers mcp + parity; `typecheck` covers engine mypy | root `lint` still omits frontend gts |
| O2 | Idea rows carry `aria-current` | still no listbox/option semantics relating list to detail pane |

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

The 2026-07-21 audit established that much of what `references/core/google-co-scientist/`
files 02–09 present as "Google requirements" is **clone-authored design** with no
paper or product basis. Scoring against these makes the system *less* faithful.
Do not treat them as targets.

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
