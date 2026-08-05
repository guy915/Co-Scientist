# Implementation Prompt — Close the Google Co-Scientist Fidelity Gap (2026-07-21)

You are a coding agent working in the `co-scientist` monorepo (FastAPI backend in
`app/`, LangGraph engine in `engine/`, React/Vite/Tailwind frontend in
`app/frontend/`, reference MCP server in `engine/mcp_server/`). Your job is to make
this system a **1:1 replica** of Google DeepMind's AI Co-Scientist (Nature 2026,
*"Accelerating scientific discovery with Co-Scientist"*, arXiv:2502.18864) and its
Google Labs **Hypothesis Generation** product, by closing the gaps enumerated
below. This prompt is self-contained: it carries every finding and acceptance
condition from the audit. You do **not** need to re-audit.

## Ground rules (read first, they change what "done" means)

1. **Fidelity is the objective, not improvement.** Where our current design
   *exceeds, replaces, or differs from* Google's, change it to match Google, even
   if ours seems "better." Removing an Elo leaderboard is progress here.
2. **The local `references/core/google-co-scientist/` files 02–09 are
   clone-invented and often WRONG about Google.** Do **not** implement to them.
   Specifically, these are NOT Google requirements and must be treated as such:
   the 12-agent roster (paper: 7), the Elo-leaderboard Ideas tab, the
   Standard/Advanced "Configure Run" form, NotebookLM export, the 3-persona
   debate, the Material-3 **blue** palette, AG-UI/CopilotKit, cross-run KSDS
   memory, and the BRIDGE/M2M/GRADE machinery. The authoritative Google sources
   are: `references/core/google-co-scientist/research/` (paper + supplement) and
   `references/core/google-co-scientist/media/hypothesis-generation/*.jpg` +
   `media/google-labs-page/` (product captures). Read those directly.
3. **Verified Google facts you must hold as invariants:** Elo init **1200**;
   Evolution creates **new** hypotheses, never mutates a parent; Meta-review
   critique appended to **all** agents' prompts next iteration; **multi-turn**
   debate for top-ranked, **single-turn** for lower-ranked; debates **3–5 turns,
   max 10**; **4** Generation techniques; **6** Reflection review types; **6**
   Evolution strategies; Evolution reads **top 5**; research overview reads **top
   10** and **feeds back into Generation**; two safety gates (goal intake reject,
   per-hypothesis pre-tournament exclude/don't-develop/don't-show); novelty review
   must be search-grounded; NIH Specific Aims output. K-factor, embedding model,
   `MaxIdeas`/`MaxMatchesPerIdea`, and the "top-ranked" cutoff are
   **paper-unspecified** — keep them configurable, don't invent a Google value.
4. **Product surface (verified from captures):** name **"Hypothesis Generation"**,
   **green** identity; report tabs **`Ideas | Knowledge Base | Summary | Run
   Specification`** (singular, Ideas first); Ideas = **card list** with
   `HIGH POTENTIAL`/`NON VIABLE` labels + an "Agent Insights" prose panel + four
   stat tiles (`High potential ideas / Non-viable ideas / Number of verified ideas
   / Sources analyzed`) — **no Elo/rank/scores shown**; an **Interview Progress**
   3-step stepper; run monitoring with a determinate bar + `Time remaining /
   Sources Analyzed / Ideas explored` tiles + an `ACTIVITY LOG`/`STATUS`
   (`EXECUTING`/`-- : --`) table; a conversational (no form) run config; a
   two-line AI/medical disclaimer under the composer; "Chat with Agent" follow-up.
   Exact verbatim strings are in the product evidence dossier at
   `<scratchpad>/audit/evidence-product.md` §3.13 — reuse them.
5. **Two run paths exist; production is the durable one**
   (`app/app/engine_tasks.py` + `app/app/task_worker.py`). The compiled LangGraph
   (`app/app/engine_adapter/workflow.py`) is offline-demo-only. **Every fix must
   land on the durable path.** Where a fix must be path-symmetric, do both.
6. **Preserve monkeypatch seams and re-export shims** when splitting modules
   (repo convention). Keep engine node key strings stable (durable resume depends
   on them). Run `ruff format/check` + `mypy` (engine + app) and `bun run lint` +
   `tsc` (frontend); both mypy suites are strict-clean today and must stay so.
7. **Tests are acceptance.** For each work item, add or extend a behavioral test
   that exercises the real path (not the offline stub). The single most important
   engine test to keep green: evolution never mutates a parent
   (`engine/tests/test_evolve.py`).

Do the work in the tiers below **in order** — Tier 0 fixes silently-broken
science and must land first.

---

## TIER 0 — Correctness defects that silently break the science

### T0.1 — Fix prose-to-PubMed query construction (register R1)
**Problem.** `engine/src/co_scientist/agents/generation/literature_review/queries.py`
generates natural-language phrases (prompt
`literature_review_query_generation_pubmed.md` even says "avoid boolean
operators"), and the final fallback sends `state["research_goal"]` verbatim. These
reach `Entrez.esearch(term=...)`, which ANDs every token → near-zero recall. There
is no MeSH mapping, no OR expansion, no field tags, and **no broadening retry on
zero results**.
**Do.** Rewrite PubMed query generation to emit boolean queries (MeSH terms where
resolvable, OR-groups of synonyms, `[tiab]`/`[mesh]` field tags), cap term count
sensibly, and add a **broadening retry ladder** on a zero-result response (drop
the most specific clause, then fall back to a 2–3 keyword OR query) in
`engine/mcp_server/.../pubmed_client.py` / `search_pubmed.py`. Remove the
prose-goal fallback in `queries.py:176-178`; fall back to extracted key entities
instead. Fix the second prose site (`validate_search.py:104`) if you re-enable the
tool path (see T2.5).
**Accept.** A unit test asserting a multi-concept goal produces an OR/MeSH boolean
query, not a bag-of-words AND; and a zero-result first query triggers a broadened
second query. Measure the "insufficient evidence" rate on a smoke run before/after.

### T0.2 — Repair the grounded-debate prompt (register R5)
**Problem.** `prompts/templates/generation_debate_and_literature.md` references
`{{user_hypotheses}}` (line ~20) and `{{instructions}}` (line ~51), but
`prompts/generation_debate.py::_build_debate_prompt_variables` supplies neither,
so the production path renders literal `{{MISSING:user_hypotheses}}` /
`{{MISSING:instructions}}` on every debate turn and **user-supplied starting
hypotheses never reach the debate**.
**Do.** Populate both variables in `_build_debate_prompt_variables` (map
`{{user_hypotheses}}` from `state["starting_hypotheses"]`, `{{instructions}}` from
the task instruction / supervisor guidance). Also reconcile the prompt's "maximum
of 10 turns" wording with actual behavior (see T2.4).
**Accept.** A test rendering the grounded debate prompt with a non-empty
`starting_hypotheses` asserts zero `{{MISSING:...}}` markers and that the user
hypothesis text appears in the rendered prompt.

### T0.3 — Ground + de-cache assumptions generation on the durable path (R21)
**Problem.** `app/app/engine_tasks.py:~1274` calls `generate_with_assumptions(state,
count)` **without** `articles_with_reasoning`/`reference_index` even when
literature is available (the streaming path passes them); and
`assumptions.py::generate_with_assumptions` doesn't pass `use_cache=False`, so two
identical goals get byte-identical hypotheses.
**Do.** Pass literature + reference index on the durable path (mirror the
`debate_lit` branch just above it). Set `use_cache=False` for assumptions
generation (diversity-critical), matching debate/draft.
**Accept.** A test asserting the durable assumptions call receives the literature
context, and that two runs of the same goal produce different assumptions
hypotheses.

### T0.4 — Make full/simulation/recurrent reviews causally effective (R3)
**Problem.** These three review types run at LLM+retrieval cost but their outputs
(`enrichments["full"|"simulation"|"recurrent"]`) are read by **nothing** in
ranking, evolution, meta-review, report, or UI.
**Do.** Feed them downstream: inject full/simulation verdicts and
failure-points into the ranking judge prompt (alongside the existing
reflection_notes / deep-verification block in `prompts/ranking.py`), into the
evolution feedback ledger (`agents/evolution/evolve.py`), and into the
meta-review synthesis input (`agents/meta_review/meta_review.py`). Surface at
least the full-review verdict + simulation failure points in the Ideas detail
pane.
**Accept.** Tests asserting each review type's output appears in the ranking prompt
context and the meta-review input; a UI test showing the full-review/simulation
content renders.

### T0.5 — Feed the research overview back into Generation (R4)
**Problem.** `state["research_overview"]` has **no consumer**; it's strictly
terminal (`research_overview → END`). The paper requires it to steer the next
Generation cycle.
**Do.** Route so the overview is produced *during* the loop (not only terminally)
and inject it into the Generation prompt for subsequent cycles (Generation
technique #4, "research expansion", uses the overview + meta-review feedback). Add
a `{{research_overview}}` slot to the generation templates and populate it from
state. Preserve a final terminal overview for the report.
**Accept.** A multi-iteration test asserting a non-empty research overview reaches
the second-cycle Generation prompt (snapshot diff).

### T0.6 — Fix the always-empty persisted proximity graph (R14)
**Problem.** `agents/proximity/proximity_graph.py::_cluster_member_ids` resolves
members by an echoed `text` field, but the live `PROXIMITY_SCHEMA` emits only
`index` (with `additionalProperties:false`), so `edges` is always `[]`. Commit
`58b25900` fixed `proximity.py` but not `proximity_graph.py`.
**Do.** Make `proximity_graph.py` resolve members by `index` (0-based, matching
`proximity.py::_match_cluster_member`), and delete the obsolete `text` path. Fix
the stale `test_proximity_graph.py` fixtures that still feed `{"text":...}`. While
here, anchor the proximity prompt to 0-based indices (render an index-labelled
list) so a 1-based model response can't silently shift clusters.
**Accept.** A test asserting a real index-shaped proximity response produces
non-empty `edges`, and that evolution's `proximity_neighbors` and the proximity
event `clusters` map are populated.

### T0.7 — Re-enable parallel-debate diversity on the durable path (R28)
**Problem.** The 8 `_DEBATE_DIVERSITY_ANGLES` are inert on the durable path because
`_enqueue_generation_fanout` emits one task per hypothesis with `count=1`, so
inside each debate `total_debates=1`/`debate_id=0` and the angle selector returns
`None`. `strategy_index` is written to task inputs but never read.
**Do.** Thread `strategy_index` → `debate_id` and pass the batch size as
`total_debates` so each durable debate task selects a distinct diversity angle.
Fix the colliding `debate_id: 0` provenance.
**Accept.** A durable-path test asserting N debate tasks apply N distinct diversity
angles and carry distinct `debate_id`s.

### T0.8 — Surface durable-path task failure as run failure (R18)
**Problem.** When a durable engine task exhausts its 3 retries, the *task* row goes
`failed` but the *run* stays `running` forever (no `status` event, SSE never
closes, `cosci runs wait` hangs until `--max-wait`).
**Do.** In `app/app/task_worker.py` (the `fail_task` path) or a run-level watcher,
transition the run to `RunStatus.FAILED` with the task error and emit a `status`
`{status:"failed", error}` event when a non-retryable/exhausted engine task fails
its run's critical path. Distinguish isolated fan-out item failures (already
tolerated) from a fatal node failure.
**Accept.** A test injecting a permanently-failing node task asserting the run
reaches `failed`, an event is emitted, and the SSE stream closes.

### T0.9 — Strengthen safety: intake parity, fail-closed, wire UNCERTAIN (R16, R17, R34)
**Problem.** (a) The intake content policy (`safety.py::review_content_safety`
`_CONTENT_PROHIBITED`) is far narrower than the per-hypothesis policy
(`review_hypothesis_safety`), so goals that block per-hypothesis (e.g. "bioweapon
… mass-casualty") only trip dual-use (a no-op) at intake. (b)
`app/app/safety.py::screen_contextual` **fail-opens silently** (returns the
deterministic baseline, no log) when the configured semantic model's provider key
is absent. (c) `held_for_review` (UNCERTAIN hypotheses) is never wired to the
app/UI — those hypotheses vanish.
**Do.** (a) Bring intake screening to parity with the per-hypothesis classifier
(share the `_PROHIBITED`/`_ETHICAL` pattern sets, or run the per-hypothesis
classifier on the goal at intake). (b) On a missing credential, at minimum log a
WARNING and, ideally, fail **closed** to `hold` for high-risk content rather than
silently regex-only. (c) Persist `held_for_review` and surface UNCERTAIN
hypotheses in the safety-audit section / a "held for review" list, adjudicable via
the existing endpoint.
**Accept.** Tests: an intake goal matching a per-hypothesis prohibited pattern is
blocked at intake; a missing-credential path logs and doesn't silently allow
high-risk content; a UNCERTAIN hypothesis appears in a run-scoped API/UI surface.

### T0.10 — Honest citation labeling (R12)
**Problem.** `app/app/citations.py::classify_citation` computes the four-state UI
label (`verified/partial/unsupported/unavailable`) from **Jaccard token overlap**;
the module's own docstring calls it a "mock." It runs on the real path, so the UI
says "verified" for what is string overlap.
**Do.** Drive the citation state from the **real claim-entailment result** that
already exists (`app/app/claims.py` / `claim_verifier.py` produce
SUPPORTS/CONTRADICTS/INSUFFICIENT per claim with verbatim-quote provenance). Map
entailment → citation state; retire the Jaccard classifier for the "verified"
label (or, if you must keep a fast label, rename it to something that doesn't
claim verification). Fix the title-exact-match abstract lookup that guarantees
`unsupported` for any source with no stored abstract.
**Accept.** A test asserting a claim the entailment judge SUPPORTS yields
`verified`, and a CONTRADICTS/INSUFFICIENT claim does not.

---

## TIER 1 — Product-surface fidelity (the visible 1:1)

### T1.1 — Rename + reorder report tabs (R6, R43)
Change the nav labels in
`app/frontend/src/workbench/pages/run_detail_shell.tsx` and the route segments in
`workbench/run_tabs.ts` to **`Ideas | Knowledge Base | Summary | Run
Specification`**, in that order (Ideas first). Make the tab nav label match the
in-page `<h2>` heading for each view (today "Learning" renders "Knowledge Base",
etc.). Keep legacy-alias redirects so old URLs resolve.
**Accept.** A test asserting the four nav labels and order, and that each tab's
heading matches its nav label.

### T1.2 — Rebuild Ideas as a labelled card list; hide Elo/rank (R2, R20, R29)
Replace the Elo-descending leaderboard in
`app/frontend/src/workbench/components/tabs/ideas_tab.tsx`. Ideas render as
**cards** with a `HIGH POTENTIAL` / `NON VIABLE` pill (from the report
`idea_buckets`), a long mechanism-naming title, an abstract paragraph, and a "Chat
with Agent" affordance (T1.6). **Remove the visible rank number chip, the "Elo
rating: N" chip, and any score display** — the tournament is an engine, not a UI
feature. Keep Elo internal (persisted, used for ordering) but do not show it. Fix
the Summary tab's stat tiles so "Number of verified ideas" reflects the real
verification axis (not a duplicate of "High Potential"), and align the four tile
labels to Google's verbatim strings.
**Accept.** UI tests: no Elo/rank text appears on an idea card; `HIGH POTENTIAL`
and `NON VIABLE` labels render; the four Summary tiles carry Google's labels and
"verified" ≠ "high potential" count.

### T1.3 — Add the Interview Progress stepper (R7)
Add a right-hand **"Interview Progress"** panel to the interview view
(`app/frontend/src/workbench/pages/chat_workspace*.tsx`) with three numbered steps
**Research Challenge → Focus Areas → Preferences** that convert to green checks as
each field is derived. The backend already persists progressive `Interview.fields`
/ `current_question` (`app/app/interviews.py`) — read them (they're currently
never surfaced).
**Accept.** A UI test asserting the 3-step stepper renders and advances as fields
fill.

### T1.4 — Disclaimer, thumbs feedback, composer copy (R22, R53, R42)
Add the two-line disclaimer under the composer verbatim: *"Hypothesis Generation is
a research tool. AI can be inaccurate; double check it."* / *"Consult a
professional for medical advice or diagnosis."* Add thumbs-up/down on Agent turns.
Align composer placeholder to *"Type your thoughts here.."* and the goal-entry
heading to *"What's your research challenge?"*. Use "Focus Areas" (plural).
**Accept.** UI tests asserting the disclaimer strings, thumbs controls, and the
placeholder/heading copy.

### T1.5 — Green "Hypothesis Generation" identity (R19)
Re-skin from teal/blue "Co-Scientist" to the **green** Hypothesis Generation
identity: product name in the shell (`layout_header.tsx`), palette in
`styles/reference_surface.css` (measure the green from the product captures in
`references/.../media/hypothesis-generation/`). Keep Google Sans typography.
**Accept.** Visual verification in both light and dark themes (measure dark from
the actual dark capture; do not eyeball).

### T1.6 — Follow-up "Chat with Agent" + mid-run steering UI (R23)
Wire the existing but UI-less endpoints. Add a per-run/per-idea **"Chat with
Agent"** surface backed by `POST /api/runs/{id}/messages/ask` (`askRunQuestion`),
and a mid-run **steering** input backed by `POST /api/runs/{id}/messages`
(`sendRunSteering`) — the backend steering path already changes agent behavior.
**Accept.** UI tests asserting a follow-up question streams a grounded answer and a
steering message reaches the run.

### T1.7 — Mid-run visibility + determinate progress (R37, R36)
Stop suppressing the tab bar while a run is active
(`run_detail.tsx:75-77`) — show the report/ideas progressively. Replace the
permanently-indeterminate progress: make the durable task plan report a determinate
fraction (fix `store/tasks.py::task_progress`'s `dynamic_plan` gate for
`engine.*`), humanize task labels (not "Engine Node Generate"), give the activity
log **per-item status** (`EXECUTING` / `-- : --`), and populate a real "Time
remaining" ETA instead of "Estimating…".
**Accept.** UI tests asserting a determinate bar, humanized activity labels,
per-item status, and a non-"Estimating…" ETA on a running fixture.

### T1.8 — Conversational config; retire the tier/focus form (R8, R38)
Replace the four-tier + four-focus selector on the plan card with a conversational
config (depth/scope emerge from the interview), or at minimum hide the numeric
selectors and reconcile nomenclature (the product has no Standard/Advanced form;
if you keep a depth control, do not resurrect "Advanced Run" in some surfaces and
"Ultra" in others). Make the four interview fields actually editable, or remove the
misleading "Edit research plan" button that opens no editor.
**Accept.** UI test asserting no Standard/Advanced form; consistent nomenclature;
either working field edit or no edit affordance.

### T1.9 — Knowledge Base as a multi-section monograph (R30)
Expand the Knowledge Base beyond ≤3 sections toward a multi-section technical
monograph with a **sticky section navigator** and **inline citation chips** in the
prose. Stop the fallback that restates hypotheses as "topics"
(`app/app/report_render.py::_knowledge_base_topics`); when synthesized topics are
empty, generate real synthesis rather than echoing hypotheses.
**Accept.** A test asserting >3 sections render with a navigator, and that the
fallback does not simply mirror the ideas list.

### T1.10 (optional) — Mechanism diagrams for expanded idea cards (R39)
If in scope, generate a multi-panel mechanism figure for expanded idea cards
(Google labels these "Generated by PaperBanana"). Otherwise document as a known
gap.

---

## TIER 2 — Engine-behavior fidelity

### T2.1 — Deep verification: sub-assumptions + decontextualization (R9)
In `agents/reflection/deep_verification.py` + `schemas/review.py`, add a second
decomposition level (each assumption → fundamental **sub-assumptions**) and a
**decontextualization** step (evaluate each sub-assumption independently of the
hypothesis, then judge whether a failed one is *fundamental*). Keep the existing
fundamental-ness boolean.
**Accept.** A test asserting the schema/prompt produce nested sub-assumptions and a
decontextualized evaluation.

### T2.2 — Evolution: 6th operator, split ENHANCEMENT, grounded enhancement, multi-parent (R10, R11, R27)
In `agents/evolution/evolution_operators.py`: add an **inspiration-from-existing**
operator and split **coherence/practicality/feasibility** out of `ENHANCEMENT`
(6 operators total, matching the paper). Give the grounding-enhancement operator
**real literature retrieval** (generate hypothesis-specific queries and fetch, like
deep-verification does — evolution currently retrieves nothing). Add
**multi-parent** lineage: introduce `parent_ids: list[str]` on `Hypothesis`
(keep `parent_id` as the primary for back-compat), populate it for COMBINATION, and
persist it (`app/app/store` + `drain.py`). Relax the 0.95 Jaccard rejection so a
genuine combination isn't vetoed, and remove the contradictory "stay distinct"
directive from the COMBINATION prompt.
**Accept.** Tests: all 6 operators fire and appear in prompts; grounding-enhancement
issues a retrieval call; a COMBINATION child records ≥2 `parent_ids`; the
new-only/immutability test still passes.

### T2.3 — Meta-review reaches all agents (R15)
Thread `_format_meta_review_context` into the **Proximity**, **Literature-Review**,
and **Safety** prompts, and ensure the **observation** review receives a non-empty
critique (today the observation node is only reached pre-meta-review; restructure
so a later cycle's observation review sees it, or route the critique in). The paper
says "all agents."
**Accept.** A test asserting the meta-review block reaches proximity/literature/
safety/observation prompts on a second iteration.

### T2.4 — Debate turn counts + verdict tokens (R24, R25, R26)
Make debate turn counts a **3–5 typical / max 10** range (config-driven), not a
fixed 5 (generation) / 3 (ranking). **Parse the `HYPOTHESIS` token** in the
generation debate loop for early termination instead of always running the fixed
count. For ranking, keep the JSON verdict but also accept/parse the `better idea:
<1 or 2>` form for fidelity, and either parse or drop the 7 unused comparison
criteria. Fix the generation-debate prompt's "max 10" vs hard-coded-5 mismatch.
**Accept.** Tests: an early `HYPOTHESIS` terminates the debate; turn count varies in
the 3–5 range; the ranking verdict parser handles the token form.

### T2.5 — Restore agentic literature-exploration + research-expansion (R33)
Wire `enable_tool_calling_generation` for the app so the agentic
draft→novelty-validate literature-exploration technique (`literature_tools/`) is
reachable on the production path (it's currently dead code — the app never sets the
flag). Make **research expansion** a distinct technique (its own prompt/behavior
using the research overview), not a relabel of a repeat GENERATE cycle. This gives
all four Generation techniques genuinely distinct behavior.
**Accept.** A run where all four Generation techniques (literature exploration,
debate, assumptions, research expansion) demonstrably fire with distinct behavior.

### T2.6 — Add the databases Google names; real retraction checking (R13, R44)
Add runnable MCP backends for **OpenTargets** and **bioRxiv** (the exact sources
Google's product plan names), and ideally arXiv/ClinicalTrials/Semantic Scholar.
Add real retraction checking: a Retraction Watch / Crossref-update / PubMed
`pubtype` lookup, since PubMed metadata currently carries no retraction field and
`citation_resolver.py` (referenced by `claims.py`) does not exist.
**Accept.** Tests hitting the new backends (behind a live-MCP flag) and a retraction
lookup that flags a known-retracted DOI.

### T2.7 — Adaptive agent sampling; stagnation-gated evolution (R31, R32)
Use the already-computed `generation_vs_evolution` effectiveness and the unused
`performance_assessment` to implement **weighted/adaptive** agent selection (the
paper's "strategically weighting and sampling"), rather than the current
one-task-per-cycle LLM pick with tie-alternation. Make Evolution **stagnation-gated**
(fire when hypothesis quality has stopped improving), matching the pseudocode,
instead of tie-alternating.
**Accept.** A test asserting evolution fires on a stagnation signal and not on a
fresh-progress signal; and that effectiveness statistics bias task selection.

---

## TIER 3 — Observability, evaluation, hygiene

### T3.1 — Token/cost/latency accounting; fix the budget undercount (R35, L5-L7)
Capture `response.usage` in `engine/src/co_scientist/llm_request.py` (currently
discarded); add token + (optional) USD accounting and per-agent latency
(`phase_times` today has one producer). Fix the `max_llm_calls` undercount:
Generation, literature review, and the orchestrator allocation call don't report
`llm_calls_delta`, so runs exceed the nominal ceiling — have every LLM call site
report. Expose **live** in-flight metrics (today `run_metrics` is written only at
finalization).
**Accept.** A run reports non-trivial token counts, per-agent latency, and a
`llm_calls` figure that matches actual provider calls; metrics readable mid-run.

### T3.2 — Persist Elo journal, transcripts, meta-review (R45, R46)
Add an Elo-history/journal (or write `matches` incrementally with a real
`iteration`, not the hard-coded 0, and not only at final drain so cancelled runs
retain matches). Persist debate transcripts (ranking + generation) and meta-review
critiques to SQL so they survive and are queryable.
**Accept.** Tests asserting per-match Elo history is queryable, transcripts persist,
and a cancelled mid-run retains its judged matches.

### T3.3 — Evaluation harness (R41, R51)
Build a GPQA-style Elo-vs-quality concordance harness and an **AML repurposing** +
**liver-fibrosis epigenetic-target** gold-set benchmark (candidate names in the
paper: Binimetinib, Pacritinib, KIRA6, Leflunomide). Expand the adversarial safety
set beyond the current 13 near-tautological items toward the 1,200-goal scale (with
a benign-biology false-positive arm).
**Accept.** A runnable `evaluations/` harness producing a concordance number and
gold-set hit counts.

### T3.4 — Architecture hygiene (R54, R55, M2, M6)
Decide the compiled LangGraph's fate: either make it the production executor or
delete it (today it's built every bootstrap but only offline-demo-invoked). Enforce
runtime foreign keys (currently `PRAGMA foreign_keys=ON` only on schema-init).
Remove the never-enqueued `run.workflow` task type. Reconcile the two
`Dockerfile.api` variants and the stale root `.env.example` (retired "Mock Mode",
`MODEL_NAME=deepseek/deepseek-chat`, phantom `ELO_INITIAL`/`ALLOWED_ORIGINS`, port
8000 vs 8008).
**Accept.** A single production execution path; FK-enforced deletes; a clean
`.env.example`.

---

## Definition of done (for the whole effort)

- All Tier 0 items land and their tests pass on the **durable** path.
- Report tabs read `Ideas | Knowledge Base | Summary | Run Specification`
  (Ideas-first); Ideas is a card list with `HIGH POTENTIAL`/`NON VIABLE` labels
  and **no visible Elo/rank/score**; the Interview Progress stepper, disclaimer,
  and green "Hypothesis Generation" identity are present.
- The five paper invariants remain intact and test-covered: Elo 1200; evolution
  new-only; meta-review critique to all agents (now including
  proximity/literature/safety/observation); multi-turn/single-turn split; research
  overview feeds back into Generation.
- In a single ≤30-minute real-provider trace: all 4 Generation techniques fire,
  all 6 Reflection review types fire and **affect output**, all 6 Evolution
  operators fire with new-only lineage, debates run 3–5/max-10 turns, PubMed
  queries are boolean with a broadening retry, citations labelled from real
  entailment, and a failing task surfaces as a `failed` run.
- `ruff format/check` + `mypy` (engine + app, strict) and `bun run lint` + `tsc`
  (frontend) are clean. No product regression in the existing suites.
- Every change is verified in **both** light and dark themes where visual.

## Where to look (do not re-audit; use these)

- Full findings + evidence with `file:line`: `FIDELITY-DIFF.md` (this
  folder), register rows R1–R58.
- Per-subsystem implementation dossiers and the paper/product evidence dossiers:
  the audit scratchpad at
  `/private/tmp/claude-501/-Users-guy-Code-Co-Scientist--claude-worktrees-co-scientist-audit-0da40d/2ded5e84-7fad-4058-b22f-9271c04c7158/scratchpad/audit/`
  (`impl-*.md`, `evidence-paper.md`, `evidence-product.md`) — if that path is
  gone, the FIDELITY_DIFF carries every finding.
- Authoritative Google sources: `references/core/google-co-scientist/research/`
  (paper + supplement) and `.../media/hypothesis-generation/` +
  `.../media/google-labs-page/` (product captures; note three media filenames are
  transposed — trust image contents, not names).
- Do **not** implement to `references/core/google-co-scientist/` files 02–09 or to
  `docs/FIDELITY.md` / `docs/PARITY*.md` — they contain clone-invented "Google"
  behavior contradicted by the primary sources.
