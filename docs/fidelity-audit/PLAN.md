# Fidelity plan

Sequenced remediation for the gaps in [FINDINGS.md](FINDINGS.md), synthesized
from the three audits' roadmaps (07-12's 15 priorities, 07-20's `P0`–`P7`,
07-21's `T0`–`T3`). Every finding is assigned to exactly one stage; every
unknowable item is contained rather than closed.

## The ordering constraint

All three audits independently reached the same conclusion and stated it as a
rule: **do not do the visible product work before the correctness work.**

> Visual polish on the present hybrid shell would preserve the wrong product
> while unsafe publication paths remain underneath. — 2026-07-20

Stage 1–3 make the system tell the truth. Stage 4 makes it look right. Doing 4
first produces a convincing product that publishes unverified science.

## Stages

| Stage | Theme | Findings | Rough size |
|---|---|---|---|
| 1 | One release gate that everything obeys | 12 | large |
| 2 | Grounding correctness | 14 | medium |
| 3 | Durable-state and safety correctness | 17 | medium |
| 4 | The visible product | 40 | large |
| 5 | Adaptive coalition | 8 | large |
| 6 | Engine reasoning fidelity | 17 | medium |
| 7 | Observability | 8 | small |
| 8 | Operations, privacy, packaging | 36 | large |
| 9 | Accessibility and responsive | 9 | small |
| 10 | Evaluation | 8 | external-dependent |
| 11 | Documentation and containment | ongoing | small |

---

## Stage 1 — One release gate that everything obeys

**Closes:** G1, I1, D5, D8, D15, J3, J5, K1, L1, D18, G7, G11

The single highest-value change, and the one every audit ranked first. Today each
consumer assembles its own payload and applies its own filter, so blocking an
idea in one path does not stop another from publishing it. Reproduced: fresh runs
completed with *every* hypothesis failing the claim gate and every claim
`insufficient`, and published all of them.

1. Define one canonical, persisted **publishability decision** per hypothesis,
   incorporating: review disposition, deep-verification verdict, claim
   support/contradiction/abstention, candidate safety status, human adjudication,
   redaction state, and source retraction status.
2. Make every consumer read that decision and nothing else — ranking eligibility,
   evolution parent selection, matchmaking, meta-review and overview inputs,
   leaderboard, idea buckets, Knowledge Base, Q&A context, research contacts,
   completion notification, download/export, public share, and deletion archives.
3. **Filter overview inputs before the LLM call.** Never post-filter prose that
   was already synthesized from blocked ideas.
4. Make `redact` transform content before any durable or public artifact, keeping
   a restricted audit record that ordinary users cannot read.
5. Restrict the share payload to the versioned sanitized report contract.
6. Replace the fabricated Knowledge Base fallback with an honest raw-evidence
   state, and compute "Verified" only from defined verification state.
7. Quarantine retracted sources at ingestion *and* at every consumer, including
   the reserved-slot and underfilled-budget paths.

**Done when:** an integration test injects a retracted source and one of each
kind of blocked idea, then asserts absence from every internal and public
consumer; a redaction fixture proves the original text is unreadable through DB,
API, SSE, log, share, and export.

---

## Stage 2 — Grounding correctness

**Closes:** G2, G3, G5, G6, E2, E3, E8, G9, G10, G12, G14, H1, H3, I4

The defects here silently degrade every downstream judgement, and several are
invisible in tests because they only appear on the real-provider path.

1. **Fix PubMed query construction** (G2): boolean/MeSH/OR expansion, field tags,
   a broadening retry on zero results, and stop sending the prose goal verbatim.
   *Partly done* — verify the remaining cases.
2. **Repair the grounded-debate prompt** (E2) so `{{user_hypotheses}}` and
   `{{instructions}}` render and user-supplied starting hypotheses reach the debate.
3. **Ground assumptions generation on the durable path and disable its cache** (E3).
4. Add semantic/hybrid retrieval with query relevance, source identity, quality,
   recency, and diversity; persist scores, rationale, and version (G5).
5. Add canonical DOI/PMID identity, availability checks, retrieval timestamps,
   and exact stored passages (G12); feed real passages to Q&A, reviews,
   verification, reports, and citations (G9).
6. Verify the proximity graph actually populates and that a non-empty weighted
   graph changes a selected matchup (H1, H3 — *both addressed, unverified*).
7. Add cache invalidation keyed to model, prompt, tool, and source version (I4).

**Done when:** a live-schema proximity response creates weighted edges that alter
a matchup; representative retrieval beats the lexical baseline on a held-out set;
exact passages support or contradict atomic claims.

---

## Stage 3 — Durable-state and safety correctness

**Closes:** F1, F2, F3, F6, F7, F8, F9, J1, J2, J4, J5, J6, J8, J10, B5, A11, N9

1. **Transactionally settle exhausted tasks** to a failed run + terminal event +
   API/SSE/CLI error (F1). Nothing may remain non-terminal with no claimable work.
2. Represent a safety hold as an explicit durable waiting state; approval creates
   a unique successor, rejection settles blocked (F2).
3. Upsert scientist hypotheses and reviews without collisions, preserving id,
   author, provenance, lineage, and safety state (F3, F7).
4. Commit steering consumption and its successor checkpoint atomically (F6).
5. Enable foreign keys on every connection; ship forward-only repair migrations
   (F8). Bound every fan-out and isolate per-item failures (F9).
6. **Strengthen the intake gate to parity with the per-hypothesis gate** (J1).
7. **Make semantic safety fail closed, or at minimum loudly**, on a missing
   provider credential (J2).
8. Wire `held_for_review` to the app and UI so uncertain items stop vanishing (J5).
9. Invalidate the cached graph and tool availability when configuration changes (B5).
10. Make create → upload → start one recoverable user transaction (A11), and
    ensure forced offline makes no external request (N9).

**Done when:** forced-crash tests cover each transaction boundary; held runs
approve and reject end to end; manual input completes through the final report.

---

## Stage 4 — The visible product

**Closes:** all of A (except A2), B1–B4, B6–B10, C1–C8, D1–D4, D6, D7, D9–D14,
D16, D17, D19–D26, M1, M4–M11

Only now. Establish current Google Help as the source for terminology and
actions, and the direct green footage for non-conflicting visible states. Treat
Gemini Enterprise Idea Generation as secondary only.

1. **Rebuild Ideas as a card list** with `HIGH POTENTIAL` / `NON VIABLE` labels
   and **hide Elo, rank, and scores** by default — the tournament is an engine,
   not a UI feature (D1, D3). Put numeric Elo, matches, lineage, claims, and
   safety behind an optional provenance layer (D19–D22).
2. Rename and reorder the report tabs to `Ideas | Knowledge Base | Summary |
   Run Specifications`; land completed runs on Ideas; resolve the
   label↔heading mismatch (D2, D6, D17).
3. Add the **Interview Progress** rail, editable fields, and a safe "Thinking"
   status that never exposes raw chain-of-thought (A1, A3, A5).
4. Add the AI/medical disclaimer, thumbs feedback, and aligned composer copy
   (A6, A13, A14).
5. Replace the tier/focus form with conversational configuration; expose exactly
   Standard and Advanced; enforce 3 + 1 concurrency (B1–B3).
6. Build the execution view with real counts, honest ETA or explicit uncertainty,
   monotonic progress, and user-safe activity text (C1–C4, C7).
7. Show the report mid-run instead of suppressing the tab bar; add a
   live/reconnecting/stale indicator (C5, C6).
8. Wire **Chat with Agent** (run-level and per-idea) to grounded Q&A; add mid-run
   steering and scientist contribution UI (D4, A7, A8).
9. Make share create/list/revoke, download, and permanent deletion reachable
   end to end (D11, D12, N3).
10. Expand the Knowledge Base to a multi-section document with a sticky
    navigator, inline citation chips, and global reference numbering (D7, D9).
11. Re-skin to the green **Hypothesis Generation** identity; remove the
    Affiliation gate, developer logs, offline chip, and static proposals from the
    default surface; label and isolate demos (M1, M5, M6, M9, C8).
12. Resolve D16 (NotebookLM) by checking current Google Help before building.

**Done when:** a fresh account completes the current Help journey with no
clone-specific gate; every control invokes a live backend operation; exact
tab/mode/action strings are asserted in tests.

---

## Stage 5 — Adaptive coalition

**Closes:** F4, F5, F10, F11, F12, E19, I2, I3

The architectural gap. Attempt only after stages 1–3, since it moves the
execution model everything else runs on.

1. Replace the fixed serial spine and single-successor enum with dependency-aware
   queueable tasks for generation, each reflection mode, ranking, each evolution
   strategy, proximity, meta-review, and candidate safety (F4).
2. Give the Supervisor a real allocation contract: enqueue a bounded portfolio of
   independent tasks, observe queue/backlog and measured agent yield, reprioritize
   at safe boundaries. Remove the prompt instruction forbidding workflow planning
   (F4, F5).
3. **Feed the research overview back into Generation** (I2) and make mature
   review outputs causally effective (I3, and E1 from stage 6).
4. Make evolution stagnation-gated (F10); persist the plan, allocations,
   observations, and terminal rationale (E19).

**Done when:** a run demonstrates simultaneous independent specialist leases; a
Supervisor decision measurably changes the task portfolio after observed yield;
a recorded evidence-based terminal decision ends the run.

---

## Stage 6 — Engine reasoning fidelity

**Closes:** E1, E4–E7, E9–E18, E20, H2, H4–H9, K2–K9, G13, A2

1. Make full/simulation/recurrent review outputs actually feed ranking,
   evolution, meta-review, and the report (E1).
2. Add sub-assumption decomposition and decontextualization to deep verification;
   run it on post-tournament leaders, not on an all-tied pool; make provider
   failure an explicit unverified state rather than an implicit pass (E4, E9).
3. Add the sixth evolution operator, split coherence/feasibility out of
   ENHANCEMENT, add literature retrieval to grounding-enhancement, and support
   multi-parent (`parent_ids`) combination (E5, E6, E10).
4. Thread the meta-review critique into Proximity, Literature Review, Safety, and
   the observation review (E7).
5. Re-enable agentic literature exploration and make research expansion a
   distinct technique; implement iterative assumption trees (E11, E12).
6. Make debate turn counts a 3–5 / max-10 range and parse the `HYPOTHESIS` token
   for early termination; re-enable diversity angles on the durable path
   (E13, E14, E16).
7. **Revisit the early review gate** so one first-pass verdict cannot bar an idea
   for the whole run and shrink the evolution pool (K2).
8. Collect scientist evaluation criteria and let them govern ranking, debates,
   and self-improvement (A2, K4).

---

## Stage 7 — Observability

**Closes:** L2–L7, L14, plus the metrics half of F5

Instrument every model and tool call with agent, task, model, prompt, tool,
schema, and policy version, tokens, cost, latency, retries, errors, cache state,
and item yield. Fix the `max_llm_calls` undercount. Add live in-flight metrics, a
health check that reflects real run health, and loud failure when a schema
degrades to empty. Stage 5's allocator cannot work without truthful counters, so
do this alongside it.

---

## Stage 8 — Operations, privacy, packaging, deployment

**Closes:** all of N

Independent of the fidelity work and separately shippable. Ordered by exposure:

1. **Security first:** N1 (spoofable default auth), N2 (bearer token in URLs),
   N7 (unauthenticated MCP with wildcard CORS), N6 (self-declared corpus access),
   N14 (diagnostic disclosure), N32 (missing security headers).
2. **Data lifecycle:** N3 (deletion), N4 (retention/cascade), N5 (upload
   validation and malware policy), N11 (data export), N12 (feedback lifecycle).
3. **Packaging correctness:** N8 (`pypdf` missing from setup), N15 (Tesseract
   missing from images), N16 (`.env` path mismatch), N17 (MCP package discovery),
   N18 (unpinned builds).
4. **Gate honesty:** N19 (`test-all` scope), N20 (CI path filters), N21 (no
   container/deploy gate), N22 (contradictory test contracts), N23 (load-sensitive
   tests), N24 (E2E overwriting tracked evidence), N25 (demo release exemption).
5. **Deployment:** N29 (root containers, no healthcheck), N28 (dev Compose), N30
   (worker topology), N31 (SQLite concurrency), N33 (deployed smoke), N10
   (`tools_config=null` in production — specialized tools registered but never
   authorized in live runs).
6. **Documentation truth:** N26, N27, N35, N36.

---

## Stage 9 — Accessibility and responsive

**Closes:** all of O, M2, M3, M12

Fix the 720-CSS-pixel boundary so 16:9 and 2:1 both render without clipping (M2);
add a visible, semantic mobile Back action and announced master/detail selection
(M3, O2, O3); implement focus trap, inert background, and opener restoration
(O1); remove `role=status` from interactive popovers (O4); keep streaming status
concise and non-live (O5); choose one coherent navigation-or-tab semantic and
implement its keyboard behavior (O6); make shortcuts discoverable or remove them
(M12).

---

## Stage 10 — Evaluation

**Closes:** L8–L12, L15, J7, K3

Mostly evidence acquisition, not code. Build the GPQA / Elo-correctness
concordance harness (L8), a controlled multi-budget scaling curve (L9), strategy
and tool ablations (L11), a blinded expert panel (L10), and evaluation artifacts
with full provenance (L12). Expand the adversarial safety set toward Google's
1,200-goal scale (J7).

**L15 (wet-lab validation) cannot be closed in this repository** and must stay
explicitly open. Never substitute fixtures or marketing anecdotes for it.

---

## Stage 11 — Documentation and containment

**Ongoing.** Rewrite README, architecture, fidelity, parity, env, setup, and
deployment docs from current executable evidence. Version and expose local
provenance. Describe the roster as Supervisor plus six specialists. Keep the
operator CLI, provenance views, pause/cancel, safety admin, pilot feedback, logs,
and themes explicitly **local** and outside the default faithful surface.

Maintain the evidence-boundary register in [FINDINGS.md](FINDINGS.md). Mark an
item resolved only when new primary evidence or actual external validation
appears — never because code was written against a guess.

**No "1:1 complete" claim survives while any boundary item remains open.** All
three audits declined to assign a fidelity score; keep it that way.

---

## Working notes

- **Re-verify before starting.** The `✓` and `~` markers in FINDINGS.md come from
  commit subjects, not verification. The audits are 2 weeks old and the tree has
  moved 224 commits.
- **Beware the reversion pattern.** The 07-12 campaign closed 86 findings; several
  were absent again eight days later. Land behavior with a test that fails
  without it.
- **Two run paths no longer exist** — the legacy streaming path was removed, so
  the durable `engine_tasks` path is the only one to fix. Older audit text
  describing both is stale.
- **Check `AGENTS.md` gotchas first.** Several findings here touch code whose
  current shape is a recorded incident fix (SQLite write lock, VACUUM, thinking
  budgets, Jaccard-vs-coverage, the review gate, echoed schemas). Do not
  re-derive those from first principles.
