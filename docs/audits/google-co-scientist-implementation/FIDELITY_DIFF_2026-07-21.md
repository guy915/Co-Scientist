# Google Co-Scientist — Fidelity Diff (2026-07-21)

> **What this is.** An exhaustive, evidence-backed comparison of the system that
> *actually exists and runs* in this repository against Google DeepMind's AI
> Co-Scientist (the Nature paper) and its Google Labs **Hypothesis Generation**
> product. It records every detectable difference and classifies each as
> `matched` / `partial` / `missing` / `incorrect` / `divergent` /
> `non-faithful-extension` / `unverifiable`. No numerical fidelity score is
> assigned. Companion artifact: `IMPLEMENTATION_PROMPT_2026-07-21.md`.
>
> **Method.** The implementation side was mapped by reading source exhaustively
> (14 subsystem dossiers, every claim anchored to `file:line`); the Google side
> from the primary paper + supplement and the product captures/live pages. Prior
> project fidelity docs (`docs/FIDELITY.md`, `docs/PARITY*.md`, `.remember/`) were
> treated as **unverified assertions** and re-checked against code, never cited as
> evidence. Behaviors were traced to the **production run path** and the
> **real-LLM backend**; anything reachable only via the offline backend, the demo
> seeder, dead code, or a stub is explicitly marked and *not* credited.

---

## 1. Executive conclusion

The repository is a **substantial, genuinely-running multi-agent
hypothesis-generation engine** that reproduces the paper's load-bearing
scientific invariants and a large fraction of the product's surface, but it is
**not a 1:1 replica** of either the paper's behavior or the shipped product. It
is closest on the deep engine mechanics, furthest on the visible product
surface, and carries a set of real defects that silently degrade grounding and
observability.

**What is faithfully implemented (verified against code, on the production
path):** the three "clone vs generic-RAG" invariants all hold — Elo initialises
at exactly 1200 ([constants.py:24](../../../engine/src/co_scientist/constants.py)),
the Evolution agent creates new hypotheses and provably never mutates a parent
(with tests), and the Meta-review critique is threaded into most downstream
agent prompts. Multi-turn debate for top-ranked pairs vs single-turn for
lower-ranked is a genuine multi-round-trip mechanism. The system runs on a real
durable task queue with leases, checkpoints, and working resume — which is
arguably *more* faithful to the paper's stated "asynchronous task execution
framework" than the LangGraph+Temporal design the local reference corpus
proposes. Reflection has all six review types present, five of which fire. Two
safety gates (goal intake and per-hypothesis pre-tournament) exist and are
persisted with a human-adjudication path. Real literature retrieval (PubMed,
OpenAlex, ChEMBL, UniProt) and a genuine LLM claim-entailment gate with
verbatim-quote provenance both run by default. The research overview is
NIH-Specific-Aims-shaped and research contacts are hallucination-gated against
real authors.

**Where it diverges most (all verified):**

1. **Product surface.** Every Goal-Report tab nav label differs from Google's
   (`Ideas | Knowledge Base | Summary | Run Specification`), the order is
   inverted, and — critically — our Ideas view is an **Elo leaderboard** while
   Google's product deliberately *hides* Elo and presents ideas as a card list
   labelled `HIGH POTENTIAL` / `NON VIABLE`. There is no Interview Progress
   stepper, no `HIGH POTENTIAL`/`NON VIABLE` idea labels, no PaperBanana-style
   mechanism diagrams, no AI/medical disclaimer, and the product identity is
   teal/blue "Co-Scientist" rather than green "Hypothesis Generation".

2. **Run model.** Google ships a **conversational** configuration (the interview
   *is* the config). The implementation adds a four-tier
   (`express/standard/extended/ultra`) + four-focus selector — a
   non-faithful-extension — and has retired the "Advanced Run" concept the paper
   and product literature use.

3. **Grounding defects.** The prose-to-PubMed query defect persists (multi-term
   natural-language phrases are ANDed by PubMed with no MeSH/OR expansion and no
   broadening retry), so literature grounding is frequently empty; the UI's
   `verified` citation label is Jaccard token overlap (its own module calls it a
   "mock"); `arXiv`, `bioRxiv`, and `OpenTargets` — the exact sources Google's
   product plan names — are absent from the runnable system.

4. **Silent degradations.** Full/simulation/recurrent reviews are computed at LLM
   cost but never read by any downstream agent; the persisted proximity graph is
   always empty (a schema/index mismatch); the research overview never feeds back
   into Generation; the grounded-debate prompt renders `{{MISSING:...}}` markers
   and drops user-supplied starting hypotheses; a durable task that exhausts its
   retries leaves the run stuck in `running`.

**A crucial correction to the local reference corpus.** Much of what the
project's own `references/` prose describes as "Google requirements" is
**clone-invented** and contradicted by the primary sources: the 12-agent roster
(paper: 7), the 3-persona debate, the KSDS/cross-run memory, the M3-blue design
system, AG-UI/CopilotKit, and — most importantly for scoring — the **Elo-leaderboard Ideas tab, the Standard/Advanced run-type form, and NotebookLM
export**, none of which appear in any Google product capture. A replica that
foregrounds an Elo leaderboard is *less* faithful, not more. This diff scores
against the verified Google behavior, not the invented design.

Bottom line: the engine is a strong, working approximation of the paper's
reasoning loop with several correctness gaps; the product is a recognizable but
clearly distinct re-skin that diverges in nomenclature, information hierarchy,
and the central decision to expose rather than hide the tournament.

---

## 2. Audit rules and classification vocabulary

- **Evidence discipline.** Every implementation claim is anchored to a repo
  `file:line`. Every Google claim is labelled `verified` (directly attested — a
  paper quote, a screenshot I read, a live page), `strong-inference`,
  `weak-inference`, or `unverifiable`.
- **No credit for potential.** Plans, specs, `docs/*.md` claims, comments, mocks,
  stubs, hard-coded demo data, seeded fixtures, dead code, and offline-only paths
  are **not** implemented behavior.
- **Name ≠ behavior.** A matching class/enum/prompt-file/config-key/component was
  never accepted as proof; the call path was traced to confirm the behavior is
  reachable on the real provider path.
- **Two run paths.** The **durable task path**
  ([engine_tasks.py](../../../app/app/engine_tasks.py) + [task_worker.py](../../../app/app/task_worker.py))
  is the only path a user run takes. The **streaming/compiled-LangGraph path**
  ([engine_adapter/workflow.py](../../../app/app/engine_adapter/workflow.py)) is
  reached only by the offline demo seeder. Behaviors are stated per path.
- **Fidelity-first.** A feature that *exceeds, replaces, simplifies, or
  intentionally differs from* Google's design is a violation
  (`non-faithful-extension` / `divergent`), never an advantage.

### Classifications

`matched` — behavior verified equivalent to Google's. `partial` — present but
incomplete or behaviorally weaker. `missing` — Google behavior absent.
`incorrect` — present but wrong/broken. `divergent` — present, deliberately
different. `non-faithful-extension` — capability Google does not have.
`unverifiable` — Google behavior can't be established from available evidence.

---

## 3. Map of both systems

### 3.1 Google — verified ground truth

**The paper** (now *"Accelerating scientific discovery with Co-Scientist"*,
Nature 2026, DOI 10.1038/s41586-026-10644-y; arXiv:2502.18864, retitled from
*"Towards an AI co-scientist"*): a multi-agent system on Gemini 2.0 with an
**asynchronous task-execution framework**; **seven agents** (Supervisor +
Generation, Reflection, Ranking, Proximity, Evolution, Meta-review); a
persistent **context memory** for iterative computation and restart. Canonical
flow: Generation → Reflection → Ranking (tournament) → Evolution / Proximity /
Meta-review operate on tournament state → self-improving loop. Verified
invariants: Elo init **1200**; **multi-turn** debate for top-ranked, **single-turn** for lower-ranked; debates **3–5 turns typical, max 10**; match pairing
prioritises Proximity-similar + newer/top-ranked; Evolution generates new
hypotheses and **never modifies existing ones**; Evolution reads **top 5**; final
research overview reads **top 10**; Meta-review critique **appended to all
agents' prompts next iteration** (learning without back-prop); constrained
decoding to **NIH Specific Aims**; four Generation techniques; six Reflection
review types; six Evolution strategies; four expert-in-the-loop interactions; two
safety gates (goal intake → reject; per-hypothesis pre-tournament → exclude,
don't develop, don't show). Termination predicate: `NumberOfIdeas < MaxIdeas AND
NumberOfMatchesPerIdea < MaxMatchesPerIdea` (values unstated). Evolution is
**stagnation-gated** in the pseudocode, not every-cycle. Reflection's novelty
judgement must be **search-grounded** (6.14→2.38/10 ablation). Elo K-factor,
embedding model, and memory schema are **paper-unspecified** (clone-defined).

**The product** (Google Labs "Hypothesis Generation", *Built with Co-Scientist*;
gated trusted-tester; **green** identity; verified from screenshots + live
pages): splash "Hypothesis Generation" + "Create a run" + three chips (Research
Challenge / Focus Areas / Preferences). Goal entry: "What's your research
challenge?" free-text. A conversational **Agent** interview with thumbs up/down,
placeholder "Type your thoughts here..", a two-line medical disclaimer, and an
**Interview Progress** stepper (3 numbered steps → green checks). Plan handoff via
a document chip with the run title + "Open" (disabled→enabled). Run monitoring:
title + "Executing Idea Tournament.." + a determinate progress bar + three tiles
(**Time remaining / Sources Analyzed / Ideas explored**) + an `ACTIVITY LOG` /
`STATUS` table with `EXECUTING` and `-- : --` states. Goal Report tabs, exactly:
**Ideas | Knowledge Base | Summary | Run Specification** (singular). Ideas tab: a
collapsible **Agent Insights** prose panel + four ⓘ stat tiles (**High potential
ideas / Non-viable ideas / Number of verified ideas / Sources analyzed**), then
idea **cards** with a `HIGH POTENTIAL` / `NON VIABLE` pill, a long
mechanism-naming title, an abstract paragraph, an expandable **mechanism
diagram** ("Generated by PaperBanana"), and a "Chat with Agent" follow-up — **no
Elo, no rank, no scores shown**. Knowledge Base: 12+ serif sections each with a
"Summary" + "Show more", inline citation chips, a sticky section navigator, and a
"References" list with "Search references" + `[n]` + "Open". Run configuration is
**conversational** (no settings form). No export/share affordance is visible in
any Hypothesis Generation capture.

### 3.2 Implementation — what actually runs

A FastAPI backend (43 routes) + React/Vite/Tailwind frontend + a LangGraph-based
engine installed as a library. User runs execute on a **durable SQLite-backed
task queue** (8-worker cohort, leases, per-node checkpoints, working resume). The
engine node chain: `supervisor → [literature_review] → generate → [reflection] →
review → comprehensive_reflection → safety_screen → deep_verification → ranking →
orchestrator`, then an LLM-directed adaptive loop over `{generate, reflect, rank,
evolve, proximity}` under deterministic guardrails, terminating on iteration
budget / LLM-call budget / convergence, then `research_overview → finalize`.
Agents: Supervisor (plan + per-cycle allocation), Generation (debate +
assumptions; literature-tools dead), Reflection (6 review types, 5 fire),
Ranking (real Elo tournament, K=24), Proximity (LLM-judged clustering, no
embeddings), Evolution (5 operators, new-only), Meta-review (+ research
overview + contacts), Safety (regex gates + optional LLM). Persistence: 22-table
SQLite store, per-run only. Product: session-home chat → model-driven interview →
research-plan card (with tier/focus selectors) → durable run → 4-tab settled
report. Models: DeepSeek by default (worker `v4-flash`, supervisor/chat
`v4-pro`), two-tier allocation, per-node temperatures.

---

## 4. Corpus-integrity corrections (read before the register)

The project's own `references/core/google-co-scientist/` files 02–09 are
**clone-authored design, not Google canon** (the corpus README says so). The
following, frequently treated as "Google requirements," are **inventions with no
paper/product basis** and must not drive fidelity scoring:

| Clone-invented item (in local refs) | Reality |
|---|---|
| "12 agents" | Paper specifies **7** (Supervisor + 6). |
| Ideas tab = **Elo leaderboard** with per-idea Elo/rank/novelty/confidence, tournament viewer, debate transcripts | Product shows a **card list** with `HIGH POTENTIAL`/`NON VIABLE` labels and **no Elo/rank**. |
| **Standard vs Advanced** run-type "Configure Run" form + parameter tables | Product config is **conversational**; no run-type form appears in any capture. |
| **NotebookLM export**, PDF/Word/LaTeX/BibTeX export from Hypothesis Generation | Unattested; NotebookLM underpins the *Literature Insights* experiment, a different product. |
| 3-persona debate (Innovator/Pragmatist/Contrarian) | Paper specifies debate **turn counts**, never personas. |
| Material-3 **blue** (`#0b57d0`) design system, Spline/DM Sans | Hypothesis Generation reads **green**; uses Google Sans. |
| AG-UI / CopilotKit / ~17 SSE event types | Not a Google-stated requirement. |
| KSDS blackboard / cross-run "Ideation Memory" | Paper's context memory is **per-run** (state + restart). |
| BRIDGE / M2M / 9-category fidelity harness, GRADE, knowledge-graph novelty math | Clone evaluation design, not Google behavior. |
| "Termination predicates unspecified" (`source-system-reference.md`) | Paper **specifies** `MaxIdeas`/`MaxMatchesPerIdea` (values unstated). |

Also corrected: the local `product-surface-and-ux.md` renders the 4th tab as
plural "Run Specifications"; the product shows singular **"Run Specification"**.

---

## 5. Complete evidence-backed comparison (by domain)

Each row: **G** = Google (with confidence), **U** = us (with `file:line`), **Δ** =
the exact difference, **⇒** = fidelity consequence, class.

### A. Research-goal creation, interview refinement, scientist steering

- **A1 — Goal entry surface.** G(verified): a single free-text card headed
  *"What's your research challenge?"*. U: a chat composer with greeting *"What
  breakthrough should we make today?"*, floating label *"Start a new research
  goal to begin"*, placeholder-less textarea + a lock icon
  ([chat_home_stage.tsx:234](../../../app/frontend/src/workbench/pages/chat_home_stage.tsx), [chat_composer.tsx:170-251](../../../app/frontend/src/workbench/pages/chat_composer.tsx)).
  Δ: different copy; greeting vs question framing; a decorative `encrypted` lock
  icon implying encryption that doesn't exist. ⇒ textual/visual divergence.
  **divergent**
- **A2 — Interview loop.** G(verified): conversational Agent interview, one
  question at a time. U: a real model-driven interview, one question at a time,
  streaming chain-of-thought, JSON-schema-constrained
  ([interviews.py:242-321](../../../app/app/interviews.py)). Δ: none material in
  mechanism. ⇒ **matched**
- **A3 — Interview field vocabulary.** G(verified): Research Challenge / Focus
  Areas / Preferences. U: Research Challenge / Focus Area / Preferences (+ Title)
  ([interviews.py:58-63](../../../app/app/interviews.py)). Δ: "Focus Area"
  singular vs Google's "Focus Areas"; extra "Title" field. ⇒ minor terminology
  drift. **partial**
- **A4 — Interview Progress stepper.** G(verified): a right-hand *"Interview
  Progress"* panel, 3 numbered steps → green checks. U: **none** — the only
  in-flight indicator is "Thinking…"; fields are invisible until completion
  ([impl-fe-chat §5](.)). Δ: the stepper is absent. ⇒ a signature product element
  missing. **missing**
- **A5 — Research-plan summary + approve.** G(verified): plan shown, "Open"
  enables when ready. U: a `RunSpecCard` with the four fields read-only + "Start
  research" ([chat_timeline_run_spec_card.tsx](../../../app/frontend/src/workbench/pages/chat_timeline_run_spec_card.tsx)).
  ⇒ **matched** (mechanism), with copy differences.
- **A6 — Plan field editing.** G(unverifiable). U: the four fields are **not
  editable**; the "Edit research plan" button opens no editor and a post-edit
  submit likely 409s ([impl-fe-chat §6](.)). Δ: a misleading affordance. ⇒
  **incorrect**
- **A7 — Thumbs up/down feedback on turns.** G(verified). U: **none** on any
  message; the only feedback UI is a pilot popover gated to `sbi_ucd`
  ([impl-fe-chat §9](.)). ⇒ **missing**
- **A8 — AI/medical disclaimer.** G(verified): *"Hypothesis Generation is a
  research tool. AI can be inaccurate; double check it."* / *"Consult a
  professional for medical advice or diagnosis."* U: **no disclaimer anywhere**
  (grep-verified). ⇒ **missing**
- **A9 — Mid-run scientist steering (UI).** G(verified paper interaction #1/#4):
  refine goal / direct follow-up. U: backend steering **works** and changes agent
  behavior ([opts.py:120-128](../../../app/app/engine_adapter/opts.py),
  [policy.py:305-316](../../../engine/src/co_scientist/scheduling/policy.py)), but
  **no UI calls it** — `sendRunSteering` has zero call sites. ⇒ capability exists,
  unreachable by users. **partial**
- **A10 — Contribute-your-own-hypothesis / manual review.** G(verified paper
  interaction #2/#3). U: endpoints + admission-through-safety exist
  ([runs.py:788-845](../../../app/app/runs.py)) but **no UI**. ⇒ **partial**
- **A11 — Voice input.** G: not shown in captures (likely none). U: none. ⇒
  **matched** (both absent).
- **A12 — Interview turn cap.** G(unverifiable). U: **no** turn cap; a model that
  never sets `completed` interviews indefinitely ([interviews.py:403](../../../app/app/interviews.py)). ⇒ **unverifiable** (robustness note).
- **A13 — Offline interview degradation.** U: on a keyless/offline deployment the
  interview silently falls to a canned 3-question script with no UI signal
  ([interviews.py:324-361](../../../app/app/interviews.py)). ⇒ offline-only defect;
  **incorrect** in that failure mode.

### B. Standard/Advanced runs, configuration, execution behavior

- **B1 — Run-type model.** G(verified): configuration is **conversational**; no
  Standard/Advanced form appears in the product; the paper parses the goal into a
  minimal free-text config (Preferences/Attributes/Constraints). U: a **four-tier**
  selector `express/standard/extended/ultra` on the plan card, each mapping to six
  numeric knobs ([run_modes.py:59-92](../../../app/app/run_modes.py)). Δ: a
  settings form Google doesn't surface; "Advanced Run" explicitly migrated away
  ([run_modes.py:104-110](../../../app/app/run_modes.py)). ⇒ **non-faithful-extension**
- **B2 — "Advanced Run" terminology.** G(verified in paper/product literature as
  the deep mode). U: absent from UI; the shared public report labels tiers
  "Advanced Run"/"Standard Run" ([shared_goal_report.tsx](../../../app/frontend/src/workbench/pages/shared_goal_report.tsx))
  but the live workspace shows Express/Standard/Extended/Ultra. Δ: nomenclature
  mismatch and internal inconsistency. ⇒ **divergent**
- **B3 — What tiers actually change.** U(verified): `initial_hypotheses_count`
  (4/8/12/16), `max_iterations` (1/2/3/4), `evolution_max_count` (4/8/12/16),
  `tournament_pairs` (6/12/20/32), `evidence_count` (4/8/12/16), `max_llm_calls`
  (1200/2500/7000/14000) — all reach engine state. G(strong-inference): Advanced
  = deeper DBs, more tournaments, ≥10 evolutionary cycles, deep verification. ⇒
  the *depth-scaling intent* is matched; the surfacing is not. **partial**
- **B4 — Focus selector.** U: four foci (Prefer evidence / Balance / Prefer
  novelty / Breakthrough) that alter prompt text only
  ([run_modes.py:159-183](../../../app/app/run_modes.py)). G: no such control. ⇒
  **non-faithful-extension**
- **B5 — Connector toggles.** U: PubMed / Web search / Lab papers toggles on the
  composer ([chat_workspace.tsx:46-50](../../../app/frontend/src/workbench/pages/chat_workspace.tsx)).
  G(strong-inference): sources are chosen by the agent, named in plan prose
  (OpenTargets/PubMed/bioRxiv), not toggled by the user. ⇒ **non-faithful-extension**
- **B6 — Estimated time/cost panel.** G(the product shows *"Time remaining 6h
  23m"* during a run, not at config). U: no pre-run estimate; a "Time remaining"
  tile that permanently shows "Estimating…" (see G3). ⇒ **partial**

### C. User journey, screens, terminology, controls, states, progress, visuals

- **C1 — Product name.** G(verified): "Hypothesis Generation". U: "Co-Scientist"
  in the shell ([layout_header.tsx:99](../../../app/frontend/src/workbench/layout_header.tsx)).
  ⇒ **divergent**
- **C2 — Color identity.** G(verified): green. U: teal seed `#1A6B6B` + Gemini
  blue `#0b57d0` palette ([reference_surface.css](../../../app/frontend/src/styles/reference_surface.css)).
  ⇒ **divergent**
- **C3 — Typography.** G(verified): Google Sans family. U: self-hosted 'Google
  Sans' / 'Google Sans Text' woff2 ([index.css:14-66](../../../app/frontend/src/index.css)).
  ⇒ **matched** (note: the local reference doc's advice to avoid Google Sans is
  itself off-target for 1:1 product fidelity; a licensing concern, not a fidelity
  gap).
- **C4 — Run state machine.** G(strong-inference, product shows Executing→report;
  paper: scoping/running/paused/completed/failed/aborted). U: 9 statuses
  `draft/queued/running/synthesizing/completed/cancelled/failed/blocked/paused`
  ([store/models.py:19-32](../../../app/app/store/models.py)). Δ: extra
  `synthesizing`/`blocked`; `aborted`→`cancelled`. ⇒ superset, mostly compatible.
  **partial**
- **C5 — Report tab *nav labels*.** G(verified): `Ideas | Knowledge Base |
  Summary | Run Specification`. U nav labels: `Goal Details | Learning | Research
  Overview | All Ideas` ([run_detail_shell.tsx:10-13](../../../app/frontend/src/workbench/pages/run_detail_shell.tsx)).
  Δ: **all four differ**, and the order is inverted (Google leads with Ideas; we
  lead with Goal Details / end with All Ideas). ⇒ **divergent** (high impact).
- **C6 — Report tab *document headings*.** U(verified): the internal `<h2>`
  titles are "Run Specifications" / "Knowledge Base" / "Summary" — which *do*
  match Google's tab names, creating a deliberate label↔heading mismatch (the
  "Learning" tab is headed "Knowledge Base"). ⇒ inconsistent nomenclature.
  **partial**
- **C7 — Mid-run visibility.** G(verified): the run view + a live report. U: while
  a run is active the **tab bar is suppressed** — ideas/report are unviewable
  until the run settles ([run_detail.tsx:75-77](../../../app/frontend/src/workbench/pages/run_detail.tsx)).
  ⇒ **divergent**
- **C8 — Idea labels on cards.** G(verified): `HIGH POTENTIAL` / `NON VIABLE`
  pills on each idea card. U: **no such labels on cards**; the buckets exist only
  as report stat tiles. Idea rows instead show a **rank number + "Elo rating: N"
  chip + "Unverified" chip** ([ideas_tab.tsx:255-299](../../../app/frontend/src/workbench/components/tabs/ideas_tab.tsx)).
  ⇒ **missing** (labels) + **non-faithful-extension** (Elo exposed).
- **C9 — Follow-up "Chat with Agent".** G(verified): a per-idea follow-up. U: Q&A
  endpoint exists ([qa.py](../../../app/app/qa.py)) but **no UI**; the started-run
  card only offers "View session details" / "Start a new … session". ⇒ **missing**
  (surface).
- **C10 — Mechanism diagrams.** G(verified): expanded idea cards render a
  generated multi-panel figure ("Generated by PaperBanana"). U: **none**. ⇒
  **missing**
- **C11 — Navigation.** U: back-arrow + arrow-key tab cycling + `g n` shortcut. G:
  top bar + tabs (no rich nav evidenced). ⇒ **unverifiable**/roughly compatible.

### D. Goal Report — Ideas, Knowledge Base, Summary, Run Spec, exports, follow-up

- **D1 — Ideas = leaderboard vs card list.** G(verified): a card list, **Elo
  hidden**, tournament is an engine not a UI feature. U: an **Elo-descending
  leaderboard** with rank chips ([lib/hypotheses.ts:12-14](../../../app/frontend/src/lib/hypotheses.ts)).
  ⇒ the single most consequential product divergence. **non-faithful-extension**
- **D2 — Agent Insights panel.** G(verified): a collapsible prose panel. U: an
  "Agent Insights" section with Key findings / Uncertainties / Contradictions /
  Recommended directions / Next experiments ([run_detail_overview.tsx:213-243](../../../app/frontend/src/workbench/pages/run_detail_overview.tsx)).
  ⇒ **matched** (concept), richer subsections.
- **D3 — Report stat tiles.** G(verified): `High potential ideas / Non-viable
  ideas / Number of verified ideas / Sources analyzed`. U: `High Potential /
  Non-Viable / Verified ideas / Sources Analyzed`
  ([run_detail_overview.tsx:156-161](../../../app/frontend/src/workbench/pages/run_detail_overview.tsx)).
  Δ: label wording/casing differs; and **"Verified ideas" displays the same
  number as "High Potential"** (both bound to `highPotential`), whereas Google's
  "verified" is an independent axis (4+20≠15). ⇒ **incorrect** (duplicated tile) +
  **partial** (labels).
- **D4 — Knowledge Base layout.** G(verified): 12+ serif sections each with
  "Summary" + "Show more", inline citation chips, sticky navigator, "References" +
  "Search references" + `[n]` + "Open". U: up to **3** sections with "Summary" /
  "Show more" / "Details", a "References" block with "Search references" + `[n]` +
  "Open" ([run_detail_learning.tsx](../../../app/frontend/src/workbench/pages/run_detail_learning.tsx)).
  Δ: far fewer sections; no sticky navigator; no inline citation chips in prose;
  and the common fallback restates hypotheses rather than a synthesized monograph.
  ⇒ **partial**
- **D5 — Summary tab contents.** G(unverifiable — no capture). U: a rich "Research
  Overview" view (lead stat, stat tiles, Agent Insights, research directions, NIH
  aims, contacts, winning ideas, tournament count). ⇒ **unverifiable** vs Google's
  actual Summary contents.
- **D6 — Run Specification contents.** G(unverifiable — no capture). U: a "Run
  Specifications" view echoing goal/focus-area/preferences/title/run-type/focus +
  a safety-audit section + private-corpus upload. ⇒ **unverifiable** vs Google's.
- **D7 — Tournament/Elo/debate visibility.** G(verified): **not** surfaced. U:
  Elo is surfaced (D1), but debate transcripts, Elo history charts, brackets, and
  a match list are all **absent** ([impl-fe-report §7](.)). ⇒ mixed:
  **non-faithful-extension** (Elo shown) yet **missing** (the leaderboard the
  local refs describe isn't fully built either).
- **D8 — Lineage view.** G(unverifiable). U: text-only "Generation N / evolved
  from an earlier hypothesis"; parent never named/linked; no tree; `/proposals`
  graph is static author content. ⇒ **partial**
- **D9 — Export.** G(unverifiable — no export control in any capture; NotebookLM
  export is clone-invented for this product). U: `report.md` download URL + share
  endpoints exist but **no UI links them**; no PDF/DOCX/CSV/slides
  ([impl-app-backend §9](.)). ⇒ **unverifiable** target; capability effectively
  absent in-product.
- **D10 — Public share.** U: `/shared/:token` renders, but **no UI mints a token**
  ([shares.py](../../../app/app/shares.py)). ⇒ **partial** (unreachable).

### E. Agent coalition — roles, prompts, inputs, outputs, observable behavior

- **E1 — Roster size.** G(verified): **7** agents. U: engine registers ~8 agent
  packages (Supervisor, Generation, Reflection, Ranking, Proximity, Evolution,
  Meta-review, Safety) + Literature-Review + Research-Overview + Orchestrator +
  Deep-Verification as distinct nodes ([agents/](../../../engine/src/co_scientist/agents/)).
  Δ: safety/literature/citation are explicit — closer to the paper's 7 than the
  clone-corpus's 12. ⇒ **matched** in spirit (7 canonical roles all present).
- **E2 — Generation techniques.** G(verified): 4 (literature exploration;
  simulated debate; iterative assumptions; research expansion). U: debate
  (genuine, 5 turns) + assumptions (single call, not iterative) fire; **agentic
  literature-exploration is dead code** (`enable_tool_calling_generation` never
  set); **research-expansion is a relabel**, no distinct prompt/function
  ([impl-generation §2,§8,§9](.)). ⇒ 2 of 4 genuinely distinct. **partial**
- **E3 — Debate personas.** G(verified): none specified (turn counts only). U:
  none. ⇒ **matched** (the clone-corpus's 3 personas are correctly absent).
- **E4 — Reflection review types.** G(verified): 6. U: all 6 present; initial +
  full + simulation + deep-verification fire; observation fires only with MCP;
  recurrent fires on iteration ≥2 ([impl-reflection](.)). ⇒ **partial** (below).
- **E5 — Deep verification depth.** G(verified): decompose into assumptions →
  **sub-assumptions**, **decontextualize**, judge **fundamental-ness**. U:
  one flat assumption level; **no sub-assumptions**, **no decontextualization**;
  fundamental-ness present ([deep_verification.py](../../../engine/src/co_scientist/agents/reflection/deep_verification.py),
  [schemas/review.py:231-271](../../../engine/src/co_scientist/schemas/review.py)).
  ⇒ **partial** (two of three defining behaviors missing).
- **E6 — Full/simulation/recurrent reviews are write-only.** U(verified): computed
  at LLM+retrieval cost, serialized to `enrichments`, but **nothing in ranking,
  evolution, meta-review, report, or UI reads them** ([impl-reflection §7](.)). G:
  reviews "provide feedback to all other agents." ⇒ **incorrect** (no causal
  effect; wasted compute).
- **E7 — Initial-review tool-free.** G(verified). U: genuinely tool-free single
  LLM call ([review.py](../../../engine/src/co_scientist/agents/reflection/review.py)).
  ⇒ **matched**
- **E8 — Full-review search grounding.** G(verified): search-grounded, gated on
  initial pass. U: real MCP retrieval feeds the prompt (retrieve-then-prompt, not
  agentic); **without MCP it runs ungrounded** ([comprehensive_reflection.py:163-166](../../../engine/src/co_scientist/agents/reflection/comprehensive_reflection.py)).
  ⇒ **partial** (grounded only when MCP is up).
- **E9 — Evolution strategies.** G(verified): 6. U: **5** operators
  (`ENHANCEMENT, SIMPLIFICATION, COMBINATION, ANALOGY, OUT_OF_BOX`);
  "coherence/feasibility" folded into ENHANCEMENT; "inspiration from existing"
  absent; selected by **round-robin**, so ENHANCEMENT never fires on express
  ([evolution_operators.py](../../../engine/src/co_scientist/agents/evolution/evolution_operators.py)).
  ⇒ **partial**
- **E10 — Enhancement-through-grounding retrieval.** G(verified): retrieve
  articles, fill gaps. U: **no retrieval anywhere in evolution**; only stale
  run-wide synthesis text ([impl-evolution §2](.)). ⇒ **missing** (the retrieval
  half of the strategy).
- **E11 — Ranking judge prompt.** G(verified): pairwise, criteria
  novelty/correctness/testability, verdict token `"better idea: <1 or 2>"`. U: a
  single "Tournament Judge" on 7 criteria; verdict is a **JSON enum `["a","b"]`**,
  not the literal token ([ranking.py:200-220](../../../engine/src/co_scientist/agents/ranking/ranking.py)).
  Δ: functionally equivalent, literally different; and 7 criteria are collected
  but **not parsed**. ⇒ **divergent**
- **E12 — Meta-review synthesis.** G(verified): synthesize reviews + debates → a
  critique. U: synthesizes both reviews and debate transcripts
  ([meta_review.py:265-273](../../../engine/src/co_scientist/agents/meta_review/meta_review.py)).
  ⇒ **matched**
- **E13 — Supervisor persona.** G(verified): administrative planner. U: a plan
  call producing *domain guidance* (explicitly forbidden from planning execution)
  + a per-cycle allocation call ([supervisor.py](../../../engine/src/co_scientist/agents/supervisor/supervisor.py)).
  ⇒ **matched** (role), with 3 of 6 guidance blocks unused.
- **E14 — Prompt termination tokens.** G(verified): debate ends on `HYPOTHESIS`;
  comparison ends on `better idea:`. U: the `HYPOTHESIS` token is instructed but
  **never parsed** (loop runs a fixed 5 turns then re-asks for JSON); the debate
  prompt also states "max 10 turns" while hard-coding 5
  ([impl-generation §5](.)). ⇒ **divergent** (tokens are decorative).

### F. Supervisor planning, orchestration, parallelism, task allocation, termination

- **F1 — Goal → plan config.** G(verified): parse goal into a plan config
  (Preferences/Attributes/Constraints). U: a Supervisor LLM call produces
  6-field domain guidance; the *numeric* config comes from the app's tier table,
  and the Supervisor is forbidden from changing it
  ([supervisor.md:7,94](../../../engine/src/co_scientist/prompts/templates/supervisor.md)).
  ⇒ **partial**
- **F2 — Summary statistics.** G(verified): hypotheses generated, requiring
  review, tournament progress, generation-vs-evolution effectiveness. U: **all
  four computed** ([orchestrator.py:114-166](../../../engine/src/co_scientist/agents/supervisor/orchestrator.py)).
  ⇒ **matched**
- **F3 — Weighted sampling / re-weighting.** G(verified): "strategically weighting
  and sampling the specialized agents." U: **no weighted sampling**; an LLM picks
  one of five tasks per cycle under deterministic guardrails; the per-agent
  `performance_assessment` that would drive re-weighting is computed but **unused**
  ([supervisor_decision.py](../../../engine/src/co_scientist/agents/supervisor/supervisor_decision.py)).
  ⇒ **partial**
- **F4 — Async worker framework.** G(verified): agents as async worker processes
  off a durable queue managed by the Supervisor. U: a **real** durable SQLite task
  queue with leases/heartbeats/retries/idempotency, 8-worker cohort, per-node
  fan-out ([task_worker.py](../../../app/app/task_worker.py), [store/tasks.py](../../../app/app/store/tasks.py)).
  ⇒ **matched** (strong; arguably more faithful than the local-ref LangGraph
  design).
- **F5 — Parallelism.** U: genuine intra-node fan-out (review/generation/mature-reflection/deep-verification) at ≤8 concurrency; the node-type chain is
  sequential; tournament runs waves of 5 ([impl-supervisor §5](.)). G(strong-inference): parallel worker exploration. ⇒ **partial**
- **F6 — Termination predicates.** G(verified): `NumberOfIdeas < MaxIdeas AND
  NumberOfMatchesPerIdea < MaxMatchesPerIdea`. U: terminates on **iteration
  budget** (COMPLETED), convergence (top-Elo stable 2 cycles), or **LLM-call
  budget**; `MaxIdeas`/`MaxMatchesPerIdea` are not the predicate
  ([policy.py](../../../engine/src/co_scientist/scheduling/policy.py)). ⇒
  **divergent** (different, reasonable termination model).
- **F7 — Evolution trigger cadence.** G(verified pseudocode): Evolution is
  **stagnation-gated**. U: Evolution fires via a generation-vs-evolution
  effectiveness tiebreak that, on a tie (the common both-zero case), **alternates**
  — so it can fire without stagnation ([policy.py:110-140](../../../engine/src/co_scientist/scheduling/policy.py)).
  ⇒ **partial**
- **F8 — Dead termination reasons.** U: `CANCELLED`/`SAFETY`/`MAX_TASKS`/`WALL_CLOCK` reasons exist but their state keys are never written; cancellation is
  enforced outside the engine ([impl-supervisor §2,§6](.)). ⇒ dead code, not a
  Google gap.

### G. Retrieval, tools, databases, grounding, evidence, citation verification

- **G1 — Reachable databases.** G(verified): web search + PubMed + domain DBs;
  product plan names **OpenTargets, PubMed, bioRxiv**. U(verified): PubMed
  (Entrez), OpenAlex, ChEMBL, UniProt, INDRA CoGex (non-default), web search
  (key-gated). **arXiv, bioRxiv, ClinicalTrials.gov, OpenTargets, Semantic
  Scholar, Crossref, Google Scholar** are named in config but have **no runnable
  backend** ([impl-retrieval "absent" table](.)). ⇒ **partial**; specifically
  **missing** the exact sources Google's product names (OpenTargets, bioRxiv).
- **G2 — Query construction (the prose-to-PubMed defect).** G(verified): grounded,
  effective retrieval is "critical." U: multi-term natural-language phrases are
  sent verbatim to `Entrez.esearch`, which **ANDs every token**; no MeSH, no OR
  expansion, no field tags, **no broadening retry on zero results**, and the final
  fallback sends the entire prose goal ([queries.py:176-184](../../../engine/src/co_scientist/agents/generation/literature_review/queries.py),
  [pubmed_client.py:194-219](../../../engine/mcp_server/...)). ⇒ **incorrect**
  (frequently-empty grounding — the documented root cause of the ~99%
  "insufficient" evidence rate).
- **G3 — Hybrid/semantic/vector search.** G(paper-unspecified; embeddings hinted
  "e.g."). U: **none** — no vector index, no embeddings, no RRF; all retrieval and
  ranking is lexical/heuristic ([impl-retrieval §5](.)). ⇒ clone-defined choice;
  acceptable per the paper but **partial** vs a grounded ideal.
- **G4 — Knowledge/evidence graph.** G(paper: not integrated — a stated
  limitation). U: no scientific entity graph; a real per-claim `claim_evidence`
  provenance table exists ([store/db.py:695-711](../../../app/app/store/db.py)).
  ⇒ **matched** (both lack a KG); entity extraction is regex, not NER.
- **G5 — Citation label ("verified").** G(verified product): "clickable
  citations"; ideas "linked to a … knowledge base of verified references." U: the
  four-state label is **Jaccard token overlap ≥0.35/0.10**, and the module calls
  itself a "mock" ([app/citations.py:87-105](../../../app/app/citations.py)). It
  runs on the real path. ⇒ **incorrect** ("verified" ≠ verification).
- **G6 — Claim-level NLI entailment.** Not a Google-stated mechanism, but the
  faithful realization of "grounded/verified claims." U: a **real** LLM entailment
  judge (SUPPORTS/CONTRADICTS/INSUFFICIENT) with verbatim-quote provenance and an
  anti-hallucination span-locate downgrade, default-on
  ([claims.py](../../../app/app/claims.py), [claim_verifier.py](../../../app/app/claim_verifier.py)).
  ⇒ **matched** (a genuine strength); its lexical retrieval stage is a limiter.
- **G7 — Retraction checking.** G(unverifiable for the product). U: OpenAlex
  `is_retracted:false` filter only; **PubMed carries no retraction field**, no
  Retraction Watch, no Crossref update check; the named `citation_resolver.py`
  **does not exist** ([impl-retrieval §7](.)). ⇒ **partial**/**incorrect**.
- **G8 — ID re-resolution.** U: PMIDs/DOIs captured but never dereferenced;
  `available` = "URL string non-empty." ⇒ **partial**
- **G9 — Private-repository indexing.** G(verified paper): index a scientist's
  private publications. U: per-run attachment upload + a BM25-style keyword
  retriever ([run_corpus.py](../../../app/app/run_corpus.py)). ⇒ **matched**
  (run-scoped).
- **G10 — AlphaFold / specialized models.** G(verified, qualitative). U: none. ⇒
  **missing** (but Google's is qualitative-only).

### H. Hypothesis lifecycle — proximity, clustering, debate, ranking, Elo, evolution

- **H1 — Elo init 1200.** G(verified ×3). U: `INITIAL_ELO_RATING = 1200`
  ([constants.py:24](../../../engine/src/co_scientist/constants.py)). ⇒ **matched**
- **H2 — Multi-turn top / single-turn low.** G(verified). U: 3-turn debate when
  either side ≥ pool-median Elo, else 1-turn; genuine multiple LLM round-trips,
  position-balanced, majority vote ([ranking.py:328-418](../../../engine/src/co_scientist/agents/ranking/ranking.py)).
  ⇒ **matched** (threshold is clone-defined — paper doesn't specify the cutoff).
- **H3 — Debate turn counts.** G(verified): 3–5 typical, max 10. U: generation
  debate hard-coded to **5** (prompt says "max 10"); ranking debate fixed at
  **3**/1 ([constants.py:37-98](../../../engine/src/co_scientist/constants.py)). ⇒
  **partial** (fixed, not the 3–5/10 range).
- **H4 — Match pairing.** G(verified): Proximity-similar + newer/top-ranked. U:
  weighted matchmaking with recency + rank + a dominant +2.0 same-cluster bonus
  ([ranking_matchmaking.py](../../../engine/src/co_scientist/agents/ranking/ranking_matchmaking.py)).
  ⇒ **matched**
- **H5 — Elo K-factor.** G(unverifiable — paper-unspecified). U: fixed **24**, no
  annealing, no margin scaling, no draws ([ranking_elo.py](../../../engine/src/co_scientist/agents/ranking/ranking_elo.py)).
  ⇒ clone-defined; **matched** to "reasonable configurable choice" (though it
  departs from the annealed schedule the local refs document).
- **H6 — Proximity embeddings.** G(paper: "e.g. text embeddings" — unspecified).
  U: **LLM-judged** qualitative similarity (high/medium/low → 0.3/0.6/1.0), no
  embeddings ([proximity_graph.py](../../../engine/src/co_scientist/agents/proximity/proximity_graph.py)).
  ⇒ clone-defined; **partial** (functional for dedup/matchmaking).
- **H7 — Persisted proximity graph.** U: **always empty** — the graph builder
  reads a `text` field the schema no longer emits (index/text mismatch from commit
  `58b25900`), so `edges=[]` every run; `proximity_neighbors` in evolution and the
  proximity event `clusters` map are consequently always empty
  ([impl-ranking §11](.)). Cluster IDs still reach matchmaking. ⇒ **incorrect**
  (a real regression).
- **H8 — Evolution new-only invariant.** G(verified). U: children are fresh
  `Hypothesis` objects with `parent_id`, generation+1, fresh Elo 1200, 0 matches,
  0 reviews; parent never mutated; guaranteed by the append-only reducer; locked
  by tests ([evolve_results.py:76-96](../../../engine/src/co_scientist/agents/evolution/evolve_results.py)).
  ⇒ **matched**
- **H9 — Multi-parent combination.** G(verified strategy): combine several top
  hypotheses. U: lineage is **single `parent_id`** (no `parent_ids`); COMBINATION
  gets 200-char peer snippets + a contradictory "stay distinct" directive + a 0.95
  Jaccard rejection gate ([impl-evolution §3](.)). ⇒ **partial** (structurally
  crippled).
- **H10 — Evolution reads top-5, overview reads top-10.** G(verified). U:
  `evolution_max_count` per tier (4/8/12/16, not fixed 5); research overview
  `RESEARCH_OVERVIEW_TOP_K = 10` ([constants.py:114](../../../engine/src/co_scientist/constants.py)).
  ⇒ **partial** (overview matched; evolution set-size differs).
- **H11 — Diversity across parallel debates.** U: 8 diversity angles exist but are
  **inert on the durable path** (each debate task runs with `total_debates=1`)
  ([impl-generation §10](.)). ⇒ **incorrect** (mechanism disabled in production).

### I. Persistent context, memory, feedback propagation, long-running state

- **I1 — Context memory model.** G(verified): a persistent context memory for
  iterative computation + restart, **per-run**. U: 22-table SQLite store + per-run
  checkpoints + working resume ([impl-app-store](.)). ⇒ **matched** (the
  clone-corpus's cross-run KSDS is invented; per-run is faithful).
- **I2 — Meta-review critique appended to all agents.** G(verified): appended to
  all agents' prompts next iteration. U: threaded into 9 of ~12 prompt surfaces
  (generation, review, ranking, evolution, deep-verification, comprehensive
  reflection[RECURRENT only], supervisor, research-overview); **not** into
  Proximity, Literature-Review, or Safety; and it **never reaches the Reflection
  (observation) node in practice** due to topology
  ([impl-evolution §7](.)). ⇒ **partial** (substantially wired; not "all").
- **I3 — Research overview feeds back into Generation.** G(verified). U: **no
  consumer** — `research_overview` is strictly terminal
  ([impl-evolution §9](.)). ⇒ **missing**
- **I4 — Feedback from tournament to Reflection (recurrent).** G(verified). U:
  recurrent review reuses full-review with injected tournament state
  ([comprehensive_reflection.py:210-216](../../../engine/src/co_scientist/agents/reflection/comprehensive_reflection.py)),
  but its output is write-only (E6). ⇒ **partial**
- **I5 — Elo history / journal.** U: no journal table; matches store before/after
  snapshots but `iteration` is hard-coded 0 and matches are written **only at
  final drain** (a cancelled run persists zero) ([impl-app-store §3](.)). ⇒
  **partial** (observability gap).
- **I6 — Debate transcript persistence.** U: transcripts exist in state but are
  **never written to SQL** (dropped by the drain); recoverable only from the
  checkpoint blob ([impl-app-store §4](.)). ⇒ **partial**
- **I7 — Meta-review persistence.** U: no meta-review table; survives only in the
  report payload + checkpoint. ⇒ **partial**
- **I8 — Cross-run memory.** G: none (paper memory is per-run). U: none. ⇒
  **matched**

### J. Safety behavior and scientific misuse controls

- **J1 — Two-gate design.** G(verified): goal intake (reject) + per-hypothesis
  pre-tournament (exclude, don't develop, don't show). U: intake gate + a
  per-hypothesis `safety_screen` node run **before every ranking**, plus a final
  output gate ([safety_screen.py](../../../engine/src/co_scientist/agents/safety/safety_screen.py),
  [engine_tasks.py:692](../../../app/app/engine_tasks.py)). ⇒ **matched**
- **J2 — Classifier type.** G(verified): "automated safety evaluation" on Gemini
  (model-based). U: the **primary classifier is a regex list**; the LLM is an
  optional escalation ([safety.py](../../../engine/src/co_scientist/safety.py)). ⇒
  **partial**
- **J3 — Intake vs hypothesis asymmetry.** U: the intake content policy is
  materially **weaker** than the per-hypothesis policy — a goal like "design a
  bioweapon for mass-casualty deployment" blocks per-hypothesis but is only
  dual-use (a no-op in standard mode) at intake ([impl-safety §1](.)). ⇒
  **incorrect** (weak intake).
- **J4 — Fail-open on missing credential.** U: if the configured semantic-safety
  model's provider key is absent, the LLM layer is **silently skipped** (regex-only
  safety) with no log line; default model is DeepSeek, so a DashScope deployment
  without `DEEPSEEK_API_KEY` is regex-only ([safety.py:117-167](../../../app/app/safety.py)).
  ⇒ **incorrect** (silent fail-open).
- **J5 — Continuous mid-flight monitoring / halt.** G(verified safeguard #4):
  meta-review continuously monitors and alerts. U: **no mid-flight halt** —
  `safety_blocked` is read but never written (dead code); the meta-review overview
  is produced but not used as a safety monitor ([impl-safety §4](.)). ⇒ **partial**
- **J6 — UNCERTAIN handling.** U: uncertain hypotheses are dropped from the pool
  and added to `held_for_review`, but that list is **never wired to the app/UI** —
  they vanish silently ([impl-safety §5](.)). ⇒ **incorrect** (no surface).
- **J7 — Persistence + human adjudication.** G(verified safeguards #5/#6:
  reasoning trace + logging). U: `safety_decisions` table across 5 stages + a
  working `POST /safety/{id}/adjudicate` + UI approve/reject buttons. ⇒ **matched**
- **J8 — Tool-call gating.** U: MCP/web/PubMed calls pass through **no** safety
  filter ([impl-safety §2](.)). ⇒ **missing** (unattested for Google too).
- **J9 — Adversarial benchmark.** G(verified): **1,200** goals / 40 topics, plus
  ~2,000 safe controls. U: a **13-item** hand-written suite, near-tautological,
  self-acknowledged as "NOT Google's 1,200-goal set" ([safety_eval.py](../../../evaluations/safety_eval.py)).
  ⇒ **partial** (token coverage).
- **J10 — Reviewer safety score.** U: `REVIEW_SCHEMA` collects a `safety` score
  but **no code reads it to reject**; rejection uses only soundness + novelty. ⇒
  **partial**

### K. Scientific reasoning, novelty, testability, diversity, output quality

- **K1 — Five default output criteria.** G(verified): alignment, plausibility,
  novelty, testability, safety. U: prompts embed these; review scores 8 axes;
  rejection gates on soundness+novelty. ⇒ **matched** (criteria) / **partial**
  (only two gate).
- **K2 — Novelty must be search-grounded.** G(verified ablation 6.14→2.38). U:
  full-review novelty is search-grounded **only when MCP is up**; when down it
  reproduces exactly the un-tooled failure mode Google measured. ⇒ **partial**
- **K3 — Hypothesis output structure.** G(verified real outputs): long
  mechanism-naming title + abstract prose + mechanism + experiment. U: schema
  fields hypothesis/explanation/literature_grounding/experiment/category
  ([schemas/generation.py:63](../../../engine/src/co_scientist/schemas/generation.py)).
  ⇒ **matched** (shape).
- **K4 — Categorize + summarize.** G(verified). U: an optional `category` field
  (not always populated; absent from the prompt body) + `explanation`; no separate
  summarizer ([impl-generation §14](.)). ⇒ **partial**
- **K5 — Grounded-debate prompt defect.** U: the grounded debate template renders
  `{{MISSING:user_hypotheses}}` / `{{MISSING:instructions}}` on **every turn of
  the production path**, dropping user-supplied starting hypotheses and leaving the
  task-instruction slot empty ([impl-generation §7](.)). ⇒ **incorrect**
- **K6 — Assumptions ungrounded + cacheable.** U: on the durable path
  `generate_with_assumptions` is called **without** literature even when available,
  and is cache-enabled (byte-identical across identical goals)
  ([impl-generation §8](.)). ⇒ **incorrect** (grounding + diversity loss).
- **K7 — Diversity mechanism.** U: parallel-debate diversity angles inert in
  production (H11); evolution near-dup rejection is lexical Jaccard. ⇒ **partial**

### L. Test-time compute scaling, latency, recovery, observability, evaluation

- **L1 — Test-time compute scaling.** G(verified): more compute → higher Elo, no
  saturation. U: tiers scale hypotheses/iterations/tournament/evolution/budget
  monotonically; convergence + budget stop it. ⇒ **matched** (scaling exists;
  no Elo-vs-quality concordance harness to prove the *effect*).
- **L2 — Observability: tracing.** G(paper claims LangSmith). U: langsmith
  installed but **never configured**; no OTel/Prometheus/Sentry; on the durable
  path the graph isn't invoked as a graph anyway ([impl-ops A1](.)). ⇒ **missing**
- **L3 — Token/cost accounting.** U: `response.usage` discarded; **no token or USD
  accounting anywhere** ([impl-ops A2](.)). ⇒ **missing**
- **L4 — Per-agent latency.** U: `phase_times` has exactly one producer
  (safety_screen); no per-agent latency ([impl-ops A4](.)). ⇒ **missing**
- **L5 — Cost/budget ceiling.** G(product shows a run ETA; the local-ref "$/ceiling
  meter" is invented). U: a real `max_llm_calls` termination ceiling — but it
  **undercounts** (generation, literature review, orchestrator allocation don't
  report), so runs exceed the nominal cap; no monetary budget; wall-clock budget
  intentionally disabled ([impl-ops B1-B3](.)). ⇒ **partial**
- **L6 — Progress reporting.** G(verified): a determinate progress bar + ETA +
  activity log with per-item `EXECUTING`/`-- : --` status. U: an **indeterminate**
  bar (always "Progress pending"), "Time remaining" permanently "Estimating…",
  raw task strings ("Engine Node Generate"), an activity log with **no per-item
  status** ([impl-fe-report §8, impl-ops A7](.)). ⇒ **partial**/**incorrect**.
- **L7 — Live metrics.** U: `run_metrics` written **only at finalization**; no
  in-flight read ([impl-ops A3](.)). ⇒ **partial**
- **L8 — Recovery.** G(verified): restart after failure. U: checkpoint + resume
  works (streaming path test-verified; durable path by code+test)
  ([impl-app-store §10](.)). ⇒ **matched**
- **L9 — Durable-path failure surfacing.** U: a task that exhausts 3 retries
  leaves the **run stuck in `running`** (no `failed` transition, SSE never closes,
  `cosci runs wait` hangs) until a process restart ([impl-ops E2](.)). ⇒
  **incorrect**
- **L10 — Silent LLM degradation.** U: 8 schemas (review, batch review,
  meta_review, deep_verification, research_overview, evolution, …) return **empty
  structures** after 5 failed attempts, visible only as a WARNING
  ([impl-ops D2](.)). ⇒ **partial** (hidden quality loss).
- **L11 — Health check.** U: `/health` is store-reachability only; a wedged run,
  failed task, stalled worker, or full disk all report `healthy`
  ([impl-ops E4](.)). ⇒ **partial**
- **L12 — GPQA / expert-eval harness.** G(verified: GPQA 78.4%, 203 goals, expert
  panels). U: an `evaluations/` folder with a small parity/safety/citation set; no
  Elo-vs-expert concordance, no GPQA, no AML/liver-fibrosis gold-set benchmark. ⇒
  **missing**

### M. Architecture, stack, persistence, API/event contracts, deployment

- **M1 — Stack.** G(unverifiable internals). U: FastAPI + React/Vite/Tailwind +
  LangGraph-lib + SQLite (WAL). ⇒ **unverifiable** vs Google internals.
- **M2 — Two-path drift.** U: the compiled LangGraph is built on every bootstrap
  but **never invoked for real runs** (only offline demo seeding); production is
  the hand-rolled durable executor ([impl-supervisor §exec-framing](.)). ⇒ dead
  code; maintenance risk.
- **M3 — Event contract.** U: an append-only `run_events` log over SSE; durable
  path emits mostly `scientific_task` events, so canonical node events + the
  `supervisor.plan` payload are **streaming-path-only / hard-coded**
  ([impl-app-backend §6](.)). ⇒ **partial**
- **M4 — Auth.** U: `auth_mode="compatibility"` by default — self-asserted client
  id, no real authentication; 404 (not 403) on non-owned runs. ⇒ note (not a
  Google-comparable behavior).
- **M5 — Deployment.** U: Vercel (frontend) + 2 Railway services (api, mcp); the
  api process is also the worker; no healthcheck on `Dockerfile.api`. ⇒ note.
- **M6 — FK enforcement.** U: foreign keys declared but `PRAGMA foreign_keys=ON`
  only on the schema-init connection, so runtime FKs are off (compensated by
  explicit child deletes) ([impl-app-store §1](.)). ⇒ note/risk.

---

## 6. Exhaustive difference register

Ordered by severity (impact on reaching a 1:1 replica), then domain. Class key as
§2. "Sev" ∈ {Critical, High, Medium, Low}.

| # | Sev | Domain | Finding | Class |
|---|---|---|---|---|
| R1 | Critical | G | Prose-to-PubMed AND defect: NL phrases sent verbatim to Entrez, no MeSH/OR/broadening-retry; prose-goal fallback → grounding usually empty | incorrect |
| R2 | Critical | D/C | Ideas surfaced as an **Elo leaderboard** with rank/Elo chips; Google hides Elo and shows `HIGH POTENTIAL`/`NON VIABLE` card labels | non-faithful-extension |
| R3 | Critical | E | Full/simulation/recurrent reviews are **write-only** — computed at cost, read by nothing | incorrect |
| R4 | Critical | I | Research overview **never feeds back into Generation** (paper says it does) | missing |
| R5 | Critical | K | Grounded-debate prompt renders `{{MISSING:...}}` and **drops user-supplied starting hypotheses** every turn | incorrect |
| R6 | High | C | All four report-tab **nav labels differ** + order inverted (Goal Details/Learning/Research Overview/All Ideas vs Ideas/Knowledge Base/Summary/Run Specification) | divergent |
| R7 | High | A | No **Interview Progress** stepper | missing |
| R8 | High | B | Four-tier + four-focus config selector replaces Google's conversational config; "Advanced Run" retired | non-faithful-extension |
| R9 | High | E | Deep verification omits **sub-assumption decomposition** and **decontextualization** | partial |
| R10 | High | E | Only **5 evolution operators** (paper: 6); "inspiration-from-existing" absent; "coherence/feasibility" folded in | partial |
| R11 | High | E | Enhancement-through-grounding performs **no literature retrieval** | missing |
| R12 | High | G | UI "verified" citation label is **Jaccard token overlap** (module self-describes as a mock) | incorrect |
| R13 | High | G | **arXiv, bioRxiv, OpenTargets, ClinicalTrials, Semantic Scholar, Crossref, Google Scholar** have no runnable backend (Google names OpenTargets/PubMed/bioRxiv) | missing |
| R14 | High | H | Persisted **proximity graph is always empty** (schema/index mismatch); evolution `proximity_neighbors` + event `clusters` always empty | incorrect |
| R15 | High | I | Meta-review critique reaches only 9/~12 surfaces; **not** Proximity/Literature/Safety; never the observation node in practice | partial |
| R16 | High | J | Intake safety gate materially **weaker** than the per-hypothesis gate | incorrect |
| R17 | High | J | Semantic safety **fail-open** (silent regex-only) when the model's provider key is missing | incorrect |
| R18 | High | L | Durable-path task-failure leaves the **run stuck in `running`** | incorrect |
| R19 | High | C | Product identity: **green "Hypothesis Generation"** vs teal/blue **"Co-Scientist"** | divergent |
| R20 | High | C/D | **`HIGH POTENTIAL`/`NON VIABLE` labels not on idea cards** | missing |
| R21 | High | K | Assumptions generation **ungrounded on the durable path** and cacheable (byte-identical) | incorrect |
| R22 | Medium | A | No AI/medical **disclaimer** anywhere | missing |
| R23 | Medium | A/C | No mid-run **steering UI** and no **follow-up "Chat with Agent"** UI (endpoints exist) | missing |
| R24 | Medium | E | Debate `HYPOTHESIS` token instructed but **never parsed**; "max 10 turns" prompt vs hard-coded 5 | divergent |
| R25 | Medium | E | Ranking verdict is a **JSON enum**, not the `better idea: <1 or 2>` token; 7 criteria collected but unparsed | divergent |
| R26 | Medium | H | Debate turn counts **fixed** (5 gen / 3 rank) vs paper's 3–5 typical, max 10 | partial |
| R27 | Medium | H | Multi-parent **combination crippled**: single `parent_id`, 200-char snippets, contradictory "stay distinct" + 0.95 rejection | partial |
| R28 | Medium | H | Parallel-debate **diversity angles inert** on the durable path | incorrect |
| R29 | Medium | D | "Verified ideas" stat tile **duplicates "High Potential"**; Google's is an independent axis | incorrect |
| R30 | Medium | D | Knowledge Base shows ≤3 sections (Google 12+), no sticky navigator, no inline citation chips; common fallback restates hypotheses | partial |
| R31 | Medium | F | No **weighted sampling / dynamic re-weighting**; `performance_assessment` computed but unused | partial |
| R32 | Medium | F | Evolution not strictly **stagnation-gated** (tie-alternation can fire it) | partial |
| R33 | Medium | E | Agentic literature-exploration generation is **dead code**; research-expansion is a relabel | partial |
| R34 | Medium | J | Uncertain hypotheses dropped silently (`held_for_review` not wired to app/UI) | incorrect |
| R35 | Medium | L | No **token/cost/tracing/per-agent-latency** observability; `max_llm_calls` **undercounts** | missing/partial |
| R36 | Medium | L | Progress bar permanently **indeterminate**; "Time remaining" = "Estimating…"; raw task strings; no per-item status | partial |
| R37 | Medium | C | **Mid-run tab bar suppressed** — report unviewable until settle | divergent |
| R38 | Medium | A | Plan fields **not editable**; "Edit research plan" opens no editor | incorrect |
| R39 | Medium | D | Mechanism **diagrams absent** (no PaperBanana-style figure) | missing |
| R40 | Medium | L | 8 schemas **silently degrade** to empty on repeated LLM failure (WARNING only) | partial |
| R41 | Medium | L | GPQA / Elo-vs-expert concordance / AML+liver-fibrosis gold-set harness **absent** | missing |
| R42 | Low | A | "Focus Area" singular vs Google "Focus Areas"; extra "Title" field | partial |
| R43 | Low | C | Report tab **document headings** match Google's tab names, creating a label↔heading mismatch | partial |
| R44 | Low | G | Retraction check OpenAlex-only; PubMed none; `citation_resolver.py` referenced but absent | partial |
| R45 | Low | I | No Elo-history/journal table; `matches.iteration` hard-coded 0; matches written only at final drain | partial |
| R46 | Low | I | Debate transcripts + meta-review critiques not persisted to SQL | partial |
| R47 | Low | E | Ranking judge's 7 comparison criteria collected but never parsed | partial |
| R48 | Low | H | Elo K fixed at 24 (no annealing/margin/draws) — clone-defined but departs from documented annealed schedule | matched* |
| R49 | Low | D | No export UI (report.md/share endpoints unlinked); no PDF/DOCX/CSV | partial |
| R50 | Low | D | Public-share token cannot be minted from any UI or CLI | partial |
| R51 | Low | J | 13-item adversarial suite (near-tautological) vs Google's 1,200-goal set | partial |
| R52 | Low | J | Reviewer `safety` score collected but never gates | partial |
| R53 | Low | A | No thumbs up/down feedback on messages | missing |
| R54 | Low | M | Compiled LangGraph never invoked for real runs (offline-only) — dead code | note |
| R55 | Low | M | Runtime foreign keys off; `run.workflow` task type never enqueued; two `Dockerfile.api` variants; `.env.example` stale | note |
| R56 | Low | A | Offline interview silently degrades to a canned 3-question script | incorrect |
| R57 | Low | K | Category field optional + absent from prompt body → inconsistent categorization | partial |
| R58 | Low | E | Interview has no turn cap / server-side forced termination | note |

\*R48 is `matched` to "a reasonable configurable choice for a paper-unspecified
parameter," recorded here because it departs from the local reference corpus's
documented schedule.

---

## 7. Inferred and unverifiable Google behavior register

Items where Google's behavior can't be established from available evidence, with
the most-likely reading and its basis. A replica should not be *scored* against
these, but they bound what "1:1" can mean.

| # | Item | Most-likely behavior | Basis / confidence | What would settle it |
|---|---|---|---|---|
| U1 | Summary tab contents | Goal recap + key findings + next steps + limitations | weak-inference (tab name only; no capture) | A Summary-tab screenshot or product doc |
| U2 | Run Specification tab contents | Echo of the run's config/params | strong-inference (name + Computational-Discovery analog) | A Run-Spec screenshot |
| U3 | Export/share affordances | Likely minimal or none in-product (NotebookLM export is a *Literature Insights* feature) | strong-inference (no control in any capture) | Product footage of an export action |
| U4 | Pause/resume/cancel/mid-run steering | Some steering exists (paper interaction #1/#4) but UI unknown | weak-inference | Run-view footage |
| U5 | Token/cost metering in-product | Not exposed to users | weak-inference (no meter in captures) | Product footage |
| U6 | Elo K-factor / annealing | Unspecified | verified-unspecified (paper says so) | Not resolvable from public evidence |
| U7 | Proximity embedding model | Unspecified ("e.g. text embeddings") | verified-unspecified | Not resolvable |
| U8 | `MaxIdeas`/`MaxMatchesPerIdea` values | Unspecified | verified-unspecified | Not resolvable |
| U9 | Definition of "top-ranked" for the debate split | Unspecified (no percentile/cutoff) | verified-unspecified | Not resolvable |
| U10 | Idea-card ordering (rank shown or not) | Internally ranked, **rank not displayed** | strong-inference (no rank in captures) | Larger idea-list capture |
| U11 | Whether inline KB citation chips link to the References list | Yes | weak-inference (design convention) | Interaction footage |
| U12 | Number of debate personas | None (turn counts only) | verified (paper); the clone's 3 personas are invented | — |
| U13 | Report-tab load behavior | Progressive/independent per-tab | strong-inference (per-tab spinners captured) | — |
| U14 | Run durations | Multi-hour (ETA "6h 23m") | verified from one capture | More run captures |
| U15 | Recurrent-review ownership | Reflection executes under Meta-review-authored guidance | strong-inference (paper text vs SI note tension) | SI clarification |
| U16 | Voice input | Likely none | weak-inference (not in captures) | Product footage |

---

## 8. Fidelity-first roadmap

Ordered strictly by importance for reaching a 1:1 replica. Each item cites the
register rows it closes. (Implementation detail is in the companion prompt.)

**Tier 0 — Correctness defects that silently break the science (do first).**
1. Fix the prose-to-PubMed query construction: boolean/MeSH/OR expansion, field
   tags, and a broadening retry on zero results; stop sending the prose goal
   verbatim. (R1)
2. Repair the grounded-debate prompt so `{{user_hypotheses}}` and
   `{{instructions}}` render and user-supplied starting hypotheses reach the
   debate. (R5)
3. Ground assumptions generation on the durable path and disable its cache. (R21)
4. Make full/simulation/recurrent review outputs actually feed ranking / evolution
   / meta-review / report. (R3)
5. Feed the research overview back into Generation. (R4)
6. Fix the empty persisted proximity graph (index/text schema mismatch). (R14)
7. Re-enable parallel-debate diversity angles on the durable path. (R28)
8. Surface durable-path task failure as a `failed` run + `status` event. (R18)
9. Strengthen the intake safety gate to parity with the per-hypothesis gate; make
   the semantic-safety layer fail-closed (or at least loudly) on a missing
   credential; wire `held_for_review` to the app/UI. (R16, R17, R34)
10. Replace the Jaccard "verified" citation label with the real claim-entailment
    result (which already exists) or rename it honestly. (R12)

**Tier 1 — Product-surface fidelity (the visible 1:1).**
11. Rename the report tabs to `Ideas | Knowledge Base | Summary | Run
    Specification`, reorder Ideas-first, and resolve the label↔heading mismatch.
    (R6, R43)
12. Rebuild the Ideas view as a **card list** with `HIGH POTENTIAL`/`NON VIABLE`
    labels; **hide Elo/rank/scores** by default (tournament as engine, not UI).
    (R2, R20, R29)
13. Add the **Interview Progress** stepper (Research Challenge → Focus Areas →
    Preferences). (R7)
14. Add the AI/medical disclaimer, thumbs up/down on turns, and align composer
    copy/greeting. (R22, R53, R42)
15. Re-skin to green "Hypothesis Generation" identity. (R19)
16. Add a mid-run **follow-up "Chat with Agent"** surface and mid-run steering UI
    (wire the existing endpoints). (R23)
17. Show the report/ideas mid-run instead of suppressing the tab bar; replace the
    indeterminate progress with a determinate bar + ETA + per-item activity status
    ("EXECUTING"/"-- : --"). (R37, R36)
18. Replace the four-tier/four-focus config selector with a conversational config
    (or hide it behind the interview), and reconcile "Advanced Run" nomenclature.
    (R8, R38)
19. Expand the Knowledge Base to a multi-section monograph with a sticky navigator
    and inline citation chips; stop the hypothesis-restating fallback. (R30)
20. Optionally add mechanism-diagram generation for expanded idea cards. (R39)

**Tier 2 — Engine-behavior fidelity.**
21. Add sub-assumption decomposition + decontextualization to deep verification.
    (R9)
22. Add the 6th evolution operator (inspiration-from-existing), split
    coherence/feasibility out of ENHANCEMENT, add literature retrieval to
    grounding-enhancement, and support multi-parent (`parent_ids`) combination.
    (R10, R11, R27)
23. Thread the meta-review critique into Proximity, Literature-Review, and Safety,
    and to the observation review. (R15)
24. Make debate turn counts a 3–5/max-10 range; parse the `HYPOTHESIS` token for
    early termination; align the ranking verdict/criteria surfacing. (R24, R25,
    R26)
25. Re-enable/complete the agentic literature-exploration generation mode and
    research-expansion as a distinct technique. (R33)
26. Add the missing databases the product names (OpenTargets, bioRxiv) and real
    retraction checking. (R13, R44)
27. Add weighted/adaptive agent sampling using the computed
    generation-vs-evolution effectiveness; make evolution stagnation-gated. (R31,
    R32)

**Tier 3 — Observability, evaluation, and hygiene.**
28. Add token/cost accounting, per-agent latency, and fix the `max_llm_calls`
    undercount; add live in-flight metrics. (R35, L5-L7)
29. Persist an Elo journal, debate transcripts, and meta-review critiques; write
    matches incrementally. (R45, R46)
30. Build a GPQA / Elo-vs-expert concordance harness and an AML + liver-fibrosis
    gold-set benchmark; expand the safety adversarial set toward the 1,200-goal
    scale. (R41, R51)
31. Make the compiled LangGraph either the production executor or delete it;
    enforce runtime FKs; remove the dead `run.workflow` path; reconcile the two
    `Dockerfile.api` variants and the stale `.env.example`. (R54, R55)

---

## 8.5 Empirical verification (executed against the audit-branch code)

The two gaps the workflow left open — running the suites and a live end-to-end
run — were closed directly. All commands ran the **worktree's** audit-branch code
(`PYTHONPATH` override onto the main-checkout venvs, confirmed to resolve to the
worktree modules), on the **offline** backend, which exercises the *real engine
control flow* (node routing, invariant values, lineage) with deterministic
content.

- **Engine test suite:** `1141 passed in 5.95s` (offline, cache off).
- **Targeted app tests** (safety, hypothesis screening, hypothesis safety,
  citations, run modes, goal-report sections, claims, claim verifier):
  `62 passed`. (The app-store subsystem agent separately ran and passed
  `test_store*` / `test_engine_drain` = 44 and `test_resume*` = 12.)
- **Offline end-to-end run** (2 iterations, 4 initial hypotheses; probe at
  `<scratchpad>/audit/e2e_verify.py`) — **observed** values:

| Invariant | Observed | Confirms |
|---|---|---|
| Elo initialisation | evolved children enter at ~1200 then play; `INITIAL_ELO_RATING=1200` | H1 **matched** |
| Evolution new-only + lineage | 4 evolved hypotheses, **all have `parent_id`**, **all ids disjoint from parents**, parents unmutated | H8 **matched** |
| Generation methods that fired | `debate:3, assumptions:1, research_expansion:4` — `literature_tools` **absent** | R33: research-expansion is a **relabel**, agentic lit-tools **dead** — confirmed |
| Reflection review types | `full:12, simulation:12, recurrent:8` present in `enrichments`; **observation absent** (no MCP); deep-verification verdicts `holds:6` | E4/E6 (write-only reviews) + observation-needs-MCP — confirmed |
| Debate depth | all 6 matches ran **3 turns** (every hypothesis ≥ median Elo early on) | H2/H3 — confirmed |
| Node topology | `supervisor→generate→review→safety_screen→deep_verification→tournament→orchestrator→meta_review→evolve→review→…→proximity→…→research_overview` | production path (rank via safety+deep-verif; evolve via meta_review; proximity after pool grows; overview terminal) — confirmed |
| Meta-review / overview | meta-review 5 keys; `nih_specific_aims` present; `research_contacts:0` (offline has no real authors) | E12/K3 + offline-contacts-empty — confirmed |
| **Persisted proximity graph** | **`edges = 0`** | **R14 confirmed empirically** — the graph is always empty |

These upgrade H1, H8, R14, R33, E4/E6, H2/H3, and the node-topology claims from
*source-reading* to *observed*. (The offline backend fills content synthetically,
so it does not exercise real-provider retrieval, real citation entailment, or the
prose-to-PubMed defect (R1) — those remain source-verified. Evolution-operator
coverage per child was not surfaced by the probe's field location but is
established by `test_evolution_operators.py` and the evolution dossier.)

## 9. Reproduction notes

- **Repo state audited:** branch `claude/co-scientist-audit-0da40d`, HEAD
  `11a31082`, worktree
  `/Users/guy/Code/Co-Scientist/.claude/worktrees/co-scientist-audit-0da40d`.
- **Implementation dossiers** (per-subsystem, every claim `file:line`-anchored)
  and **evidence dossiers** (paper + product) were produced by a 36-agent
  workflow and are the backing detail for §5–§6. The compare/verify/critique
  phases were interrupted by a weekly usage limit; the register in §5–§6 was
  synthesized directly from the completed dossiers plus first-hand verification of
  the load-bearing invariants (Elo 1200, evolution new-only, meta-review threading,
  tab labels, run tiers, proximity method, debate multi-turn) by the auditor.
- **Primary Google evidence:** `references/core/google-co-scientist/research/`
  (paper + supplement, verified against the live arXiv abstract and Nature record)
  and `references/core/google-co-scientist/media/hypothesis-generation/*.jpg` +
  `media/google-labs-page/` (product captures + live page). Note the corpus's
  media filenames are transposed for three files (documented in the product
  evidence dossier); claims here are keyed to *what the images show*, not the
  filenames.
- **Not credited:** `docs/FIDELITY.md`, `docs/PARITY*.md`, `docs/ui-fidelity.md`,
  `.remember/`, and reference files 02–09 — treated as unverified assertions.
- **Empirically run (§8.5):** the engine suite (1141 passed), a targeted app
  suite (62 passed), and an offline end-to-end run confirming the invariant values
  and node topology. Commands used the main-checkout venvs with a `PYTHONPATH`
  override onto the worktree src (verified to resolve to audit-branch modules),
  `COSCIENTIST_FORCE_OFFLINE=1`.
- **Not run under a real provider:** an end-to-end run against a live LLM +
  retrieval backend was not performed (no provider key exercised here), so
  real-provider-only behaviors — the prose-to-PubMed defect (R1), real citation
  entailment, live retrieval quality — remain source-verified rather than observed.
- **Audit byproducts removed:** the runtime agent's evaluation-result JSONs were
  deleted; the only tree changes from this audit are the two deliverable docs.
