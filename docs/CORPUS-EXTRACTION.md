# Corpus extraction checklist

What is left to take out of `references/core/google-co-scientist/` (188 files,
36 MB) before the folder can be deleted without losing anything.

This document is a **checklist, not a plan and not a change**. Nothing here has
been implemented. No ledger row, ADR, test, or line of code was edited to
produce it. The owner reviews this first; the work it names is done afterwards,
from this list.

The precedent is `references/peripheral/`, which was read, drained into four
ADRs under `docs/decisions/`, and deleted.

## Result

**931 candidate rows** were swept out of the corpus. All **182 files** are
accounted for — see "Coverage" at the end, which also records what the first
pass missed. They reduce to **97 region rows** plus **17 deletion rows**, and a later
**mirror-fidelity pass** — commissioned once the owner set the governing rule
that published artifacts must be copied, not paraphrased — added **31 more**
(`MO-*` outputs, `MP-*` prompts, `MC-*` pseudocode, `MA-*` architecture).

| Status | Region rows | |
|---|---|---|
| `work` | **67** | Real, unrecorded. This is the checklist. |
| `done` | 21 | Already implemented, recorded, or pinned. |
| `reject` | 19 | Clone-authored, invented, or an accepted divergence. |
| `unclear` | 14 | Could not be decided; each says what would settle it. |
| `adapted` | 3 | Justified difference, but with a runtime effect worth a decision. |
| `external` | 4 | Needs data, access, or expertise this repo lacks. |
| **deletion** | **+17** | Separate: what must happen before the folder can go. |

**The three findings that would change the most if fixed**, all from the mirror
pass: `MP-1` (the tournament judge is instructed to do the opposite of what the
published prompt says, on the highest-volume call in a run), `MP-2` (the
evolution agent is never told the research goal), and `MA-1` (the parity ledger
cites a clone's summary 51 times and the papers zero times).

Plus a 14-source retrieval table in R6 (8 `done`, 6 `reject`).

Rows are consolidated: two independent verification passes covering R10 and
R2–R9 row by row produced 249 further verdicts between them (R10: 39 `done`,
17 `external`, 13 `reject`, **0 `work`**; R2–R9: 53 `done`, 123 `reject`,
2 `unclear`, 2 `work`). Their findings are folded in above rather than listed
separately — see "Verification depth".

**Regions that yielded nothing, on the record:**

- **R7** (`context-engineering-and-memory.md`) — of 162 lines, exactly two rows
  trace to a paper claim, and both are the file pointing back at file 01 rather
  than contributing anything. The KSDS blackboard, the dual Ideation /
  Experimentation memory, E-mem, `AUTOCOMPACT_BUFFER_TOKENS`, the context-budget
  percentages and the 15-table schema are all unattributed clone elaboration.
  The region was predicted to yield almost nothing and it did.
- **R2** (`product-surface-and-ux.md`) — 47 rows, **zero** paper-backed.
- **R6** (`retrieval-grounding-and-verification.md`) — 71 rows, **zero**
  paper-backed. Its one useful contribution is the source list, and checking it
  produced no work at all.
- **R4** (`agent-coalition-specifications.md`) — the invented twelve-agent
  roster and everything built on it.

**The three highest-value `work` items:**

1. **`R8-1` — a published prompt instruction was silently lost.** The published
   pairwise judge is told to "disregard these scores… as they may not be
   directly comparable across reviews". That instruction is absent from
   `templates/ranking.md`, which nonetheless injects review content into the
   judge. We feed the judge exactly what the published prompt warns about,
   without the warning. It comes from the region everyone had marked finished,
   which is what makes it matter (`R8-2`).
2. **`R12-1` / `R12-2` — the run-plan vocabularies are Google's, and the ledger
   says the opposite.** The tier and focus vocabularies transcribed from
   Google's own footage match `run_modes.py` name-for-name and order-for-order,
   and a pin test has been asserting it all along — while FINDINGS `B1` and `B2`
   record both as local extensions with no Google basis.
3. **`R1-13` — our scaling harness measures the wrong thing.** The paper
   partitions one run's hypotheses into ten equal temporal buckets and shows Elo
   rising across them. Ours varies tier across runs, which its own residual
   admits "measures the harness rather than the model". The paper's method is
   cheaper and more faithful.

**Every `unclear`, with what would settle it**, is listed in the region tables:
`R10-7` (the scale behind `Answer: N`), `R10-8` (the per-idea `Critiques`
rollup), `R10-9` and `R1-18` (the glossary vocabulary), `R11-3` (review-label
vocabulary), `R11-4` (a 20th hypothesis referenced but absent), `R12-12`
(references list vs citation audit), `R12-13` (`Top ideas` appearing twice),
`R12-15` (assumption-verdict wording), `R12-16` (research-contact fields),
`R13-6` (whether anything cites `google-labs-page/`), `R8-4` (ranking-05's
prompt-only content).

## The verbatim corpus — the part that must be mirrored

**The governing rule for this class: where Google published something —
a prompt, a pseudocode listing, a real output, or a specification of the
architecture and execution flow — ours should be a copy of it, adjusted only
where our system genuinely needs something different, and every adjustment
should be able to name what need justifies it.** An unjustified difference is
drift, not a design choice.

This matters because the folder holds **two kinds of content, and the rule
applies to exactly one of them.**

| | Volume | What it is | Rule |
|---|---|---|---|
| **Verbatim published artifacts** | **11,070 lines** — 8 prompts (260), 7 pseudocode listings (240), 20 real outputs (1,536), one complete published run of 22 files (9,034), plus the MASH report (4,187) | Google's own text, transcribed | **Mirror it.** Differences need a stated justification |
| **Clone-authored consolidations** | ~2,270 lines — the 11 root `.md` files (R1–R9) | A previous effort's *design writing about* the system, largely unattributed | **Do not mirror it.** The audit's own reading rule 4 is explicit that scoring against these makes the system *less* faithful |

Getting this backwards is the expensive mistake available here, and it is easy to
make because both kinds sit in the same folder and read with the same
confidence. A row citing `prompts/ranking-04-pairwise-comparison.md:26` is
quoting Google. A row citing `tournament-evolution-and-evaluation-criteria.md`
is quoting someone's plan for a clone. Every row in this document names its file
for exactly this reason.

### The architecture trap, specifically

Architecture and execution flow are the place this distinction bites hardest,
because the corpus contains a file **named** as though it were the architecture
specification — `system-architecture-and-orchestration.md` — and it is not one.
Of its 49 claims, **exactly one is paper-backed** (the Elo 1200 initialisation,
`R3-2`, already `verified` and pinned). The rest — a Postgres schema, AG-UI /
CopilotKit with ~17 SSE event types, a `ResearchLoop` control plane, Temporal,
Celery/Redis, pgvector, named NLI models — is a proposed stack for a clone.
`docs/PARITY.md`'s closing section already states outright that this stack is
not the product's.

So "emulate the published architecture more closely" must mean **the papers and
the pseudocode**, never this file. The primary sources for flow are:

| Source | What it carries |
|---|---|
| `research/papers/towards-an-ai-co-scientist.md` | The system decomposition, the asynchronous task-execution framework, the Supervisor's role, context memory, and test-time compute scaling — in prose and in the Figure 1/2 captions, which in this paper often carry the actual specification |
| `research/supplements/…-supplementary-information.md` | The Nature version of the same, which **differs from the arXiv in places** — see `R10-11` |
| `research/extracted-artifacts/pseudocode/01-supervisor.md` (71 lines) | The only line-by-line statement of the orchestration loop anywhere in the corpus, and the longest of the seven listings |

A verbatim transcription of what those three actually specify about
architecture and flow — with a `mirrored` / `adapted` / `drift` /
`unspecified` verdict against **both** of our execution paths, the LangGraph
streaming path and the durable task path production really runs — is in
progress and lands in this section.

The `unspecified` verdict is the one to watch. A great deal of confident
"Co-Scientist architecture" in circulation is not in the papers at all, and the
consolidations are where much of it came from. Recording what Google *did not*
specify protects against mirroring something they never published.

### How faithfully do we mirror it today

The eight prompts were sentence-diffed against our templates (`R8-1` … `R8-6`)
and the answer was mixed: four templates carry their source faithfully, one
substantive instruction had gone missing silently, and one framing sentence was
absent while the ledger recorded the opposite. That result — *derivation was
recorded, preservation was never checked* — is why the same measurement is now
being applied to the pseudocode and the output shapes rather than assumed.

Element-by-element mirror diffs for all three artifact classes are in progress;
their results land in this section. What is already known:

- **Prompts.** `R8-1` is one confirmed instruction lost in transfer, with real
  behavioural consequence — our tournament judge is shown review scores and,
  unlike the published judge, is never told they are not comparable across
  reviews. `R8-6` is a framing sentence absent on our side while a ledger row
  asserts the source does not contain it.
- **Pseudocode.** Partly guarded already: `engine/tests/test_published_pseudocode_invariants.py`
  pins named constants out of six of the seven listings (`DEL-2` … `DEL-7`).
  Constants are the easy half; ordering, guards and idempotency conditions are
  not pinned by anything.
- **Output shapes.** Partly guarded by `engine/tests/test_published_artifact_shapes.py`
  and `app/tests/test_published_plan_config.py` (`DEL-8` … `DEL-12`). The
  published *field vocabularies* — the exact words used for verdicts, labels and
  section names — are largely unpinned, and `R12-15`, `R12-16` and `R12-21` are
  each an instance of the same question.

### Mirror pass 1 of 4 — output shapes (complete)

All 14 published real outputs were read in full and compared element by element
against our schemas (`engine/src/co_scientist/schemas/`) and renderers
(`app/app/report_markdown*.py`). **78 structural elements: 25 mirrored,
27 renamed, 24 missing, 2 extra.**

**What is already a faithful mirror**, and machine-pinned — confirmed rather
than re-derived: the tier vocabulary (`Express / Standard / Extended / Ultra`),
the focus vocabulary (`Prefer evidence / Balance / Prefer novelty /
Breakthrough`), the tournament verdict (`Better idea: 1` / `2`), the deep
verification probe triple (`Question:` / `Answer:` / `Reasoning:`), and the
cf-PICI overview headings. These are the model for what the rest should look
like.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| MO-1 | `research-overviews/als-research-overview-and-contact.md`, `cf-pici-research-overview.md` | Each research direction nests a **named sub-topic one level below it**, carrying its own "why", "what", and specific questions | `work` | **The highest-impact shape gap, because the overview is the run's primary deliverable.** `synthesis.py:92-93` flattens `research_directions[]` straight to `importance` plus a bare `suggested_experiments` string array — there is no sub-topic level at all | `RESEARCH_OVERVIEW_SCHEMA` + the overview renderer | L |
| MO-2 | `meta-review-critiques/als-meta-review-critique.md` | A 5-theme critique taxonomy, 2-3 levels deep | `work` | **Structure is lost twice over.** The schema already flattens it to `recurring_themes[].{theme, description, frequency}` — then `agents/meta_review/meta_review.py:337-351` **drops `description` and `frequency`** before the app renders anything, so "Emerging themes" prints bare names. The second loss is the cheap fix and is pure waste today: the fields are computed and paid for, then discarded | `meta_review.py` state-shaping first, schema depth second | S then M |
| MO-3 | `reviews/als-reflection-reviews.md:19,28` (Figure A.11) | The novelty review is **two named lists**: `Aspects already explored:` and `Novel Aspects:` | `work` | **No schema field distinguishes them anywhere** — confirmed by direct search, not inferred from omission. This is the shape `R10-8`'s `Novelty review` block and `R12-3` both circle without naming | `REVIEW_SCHEMA` novelty section | M |
| MO-4 | `validated-outputs/kira6-detailed-output-validated.md:165-171` | Per-assumption labels are printed as `Plausible:`, `Plausible, but requires careful investigation:`, `Unknown:` | `work` | **We carry two different enums for one judgement, and they disagree with each other.** `review.py:284-289` (`DEEP_VERIFICATION_SCHEMA.sub_assumptions[].status`) is `supported / uncertain / unsupported`; `review.py:328-331` (`FULL_REVIEW_SCHEMA.assumptions[].support`) is `supported / uncertain / likely_false`. Neither matches the other, and neither matches the published wording. This supersedes `R12-15`, which saw only half of it | Unify the two enums; then decide separately whether to adopt the published words | S |
| MO-5 | `kira6-detailed-output-validated.md:185,220` | Each of the two appended reviews closes with a bare **`Answer: 4`** and **`Answer: 3`** | `unclear` (narrows `R10-7`) | Google's corpus now shows **three** scoring conventions: this bare closing number, the paper's "review score ≥ 4" with "five review score groups" 1–5 (`R10-3`), and the 15-axis Likert (`R10-10`). Ours has its own two: the 1–10 `_SCORE_CRITERIA` (`review.py:15-24`) and the 1–5 attribute rubrics (`planning.py:141-149`). Values of 3 and 4 fit either scale, so these two exemplars do not settle it — but a separate reading found per-dimension `Answer: N` at values **2 through 9**, which rules 1–5 out for *that* block. The likeliest reading is that a per-dimension score is 1–10 and the 1–5 is an aggregate selection gate — **not yet proven** | The same decision as `R10-3` / `R10-7`; do not change the scale until one reading is established | S |
| MO-6 | `als-generation-output.md`, `kira6-detailed-output-validated.md` | Every proposal opens with scene-setting: an `Introduction` and `Recent findings and related research` | `work` | No field carries per-hypothesis background. A reader goes from title straight into mechanism with no framing. Note `R12-23` found the same omission at run level (`Main Research Directions`); this is its per-idea twin | `GENERATION_SCHEMA` | M |
| MO-7 | `als-research-overview-and-contact.md` | Each contact is tagged `Research Direction: X`, tying the researcher back to the direction that surfaced them | `work` | `research_contacts[]` is a flat undifferentiated list; the linkage is gone. Sharpens `R12-16`, which asked whether our contact schema *adds* fields — the answer is that it also **drops** one | Contacts schema + renderer | S |
| MO-8 | `tool-use/alphafold-oct4-protein-design.md` | AlphaFold is used to score a **novel modified sequence**, with ESM-2 and RoseTTAFold as independent validators | `reject`, with a sharper note than `R10-6` | FINDINGS `G13` closes this `=` as a deliberate local choice. The new detail is worth recording anyway: our one AlphaFold-adjacent skill (`alphafold_database_fetch_and_analyze`) **explicitly refuses this exact case** — its own SKILL.md says to ask for a UniProt ID first. So the gap is not "unimplemented", it is "the available tool declines the published use case", which is a different sentence to write in a ledger | `none`; add the sharper wording to `G13` | S |
| MO-9 | `als-reflection-reviews.md`, `kira6-…-validated.md` | Every assumption is printed with a **free-text reasoning paragraph** | `work` | Present on the wrong schema. `DEEP_VERIFICATION_SCHEMA.sub_assumptions[].verification` carries prose; `FULL_REVIEW_SCHEMA.assumptions[]` carries only the closed enum. A hypothesis reviewed via full review alone therefore **loses the reasoning text entirely** | `FULL_REVIEW_SCHEMA` | S |
| MO-10 | `kira6-detailed-output-validated.md` (`Safety and toxicity`) | The **proposal itself** carries a pharmacological safety and toxicity section | `work` | Not the same thing as the reviewer's `safety_ethical_concerns` (dual-use and ethics). There is no proposer-side toxicity field on the generation schema at all — and for a drug-repurposing system this is the section a domain reader looks for first | `GENERATION_SCHEMA` | S |
| MO-11 | `research-goals/cf-pici-research-goal.md` | The research goal is intake as **three named parts**: `Title`, `Goal`, `Background` | `work` | `CreateRunRequest.research_goal` is one free-text field; nothing solicits or stores the three separately. Note the interview already elicits comparable material and then discards its structure — the same shape as `R12-18` | Run intake + interview | M |
| MO-12 | `als-research-overview-and-contact.md:29-32` vs `cf-pici-research-overview.md:45,54` | Two published overviews use **different vocabularies for the same slot**: ALS is `Rationale:` / `Recent Findings:` / `Areas of Research:`; cf-PICI is `Why Research This Area?` / `What to Research in This Area?` | `work` | We mirror the cf-PICI pair only (`importance` / `suggested_experiments`, pinned). The ALS third slot, **`Recent Findings`**, has no home — the same "what is already known" field `MO-6` finds missing per idea. Both exemplars also use a **doubled structure** (a brief preview list, then full detail) that our single array cannot express | Overview schema; decide which published vocabulary is canonical | M |

**A vocabulary warning this pass surfaced.** The word `Attributes` names two
differently-shaped things in Google's own documents: a bare list in
`als-research-goal-and-plan-config.md:23-25`, and name-plus-1-5-rubric in the
MASH plan (`R12-17`). Mirroring "Attributes" without saying *which* published
document is meant will reproduce the wrong one.

### Mirror pass 2 of 4 — the eight prompts (complete)

**`R8-1` was understated. The instruction is not missing, it is inverted.**
The published judge is told *"Disregard these scores in your comparative
analysis, as they may not be directly comparable across reviews"*
(`ranking-04:26`). Ours is told, verbatim at
`engine/src/co_scientist/prompts/ranking.py:443-446`:
*"Consider these scores, but make your judgment based on comprehensive
comparison, not just scores."* We do not omit the warning; we instruct the
opposite. Verified directly.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| MP-1 | `prompts/ranking-04-pairwise-comparison.md:26` | "Disregard these scores… not directly comparable across reviews" | `work` — **supersedes `R8-1`** | `prompts/ranking.py:443-446` says "Consider these scores…". This is the highest-volume call in a run (O(n²) per cycle), so the inverted instruction is applied on every match | One line, reversed | S |
| MP-2 | `evolution-06:…`, `evolution-07:…` — both published evolution prompts open with `Goal: {goal}` | The evolution agent is told the research goal | `work` | **The evolution prompt never states the goal.** `templates/evolution.md`'s placeholders are `articles_with_reasoning, domain_context, domain_evolution_guidance, enhancement_grounding, falsified_assumptions_section, lab_constraints_section, meta_review_insights, original_hypothesis, partner_context, review_feedback, run_guidance, specialist_feedback, supervisor_guidance` — **no `goal`**. The only `research_goal` in all of `agents/evolution/` is `evolve_grounding.py:142`, the literature-retrieval path, not the rewrite. Verified directly. So every evolved hypothesis is rewritten by a model that was never told what the run is for | `evolution.md` + its context builder | S |
| MP-3 | same two prompts | Evolution also receives the scientist's preferences and criteria | `work` | No plumbing for `preferences` into the evolve prompt path at all. Same edit as `MP-2` | Same | S |
| MP-4 | `meta-review-08-meta-review-generation.md` | Meta-review receives the preferences | `work` | Absent — and this one **propagates**: `meta_review_context` is re-injected into 6+ downstream node types (`prompts/_common.py:149-178`), so every consumer inherits the omission | `meta_review` context builder | S |
| MP-5 | `evolution-07:874-876` | "This should not be a mere aggregation of existing methods or entities. Think out-of-the-box." | `work` | Absent from every operator — **including `COMBINATION`, the one it most directly polices** | `evolution.md` | S |
| MP-6 | `ranking-04`, `ranking-05` (`{preferences}`) | The ranking judge is given the scientist's preferences | `work` | We substitute `criteria` for `preferences`. The substitution is justified (`A2`/`K4` rationale) but leaves ranking **silently blind to scientist input whenever only `preferences` was supplied** — which, per `R12-18`, is what the chat interview always produces | Ranking context builder | S |
| MP-7 | `evolution-06:861` | A three-step reasoning scaffold: domain overview -> synopsis of recent work -> reasoned argument -> core contribution | `work` | Dropped, not merely reformatted into the JSON schema | `evolution.md` | M |
| MP-8 | `evolution-07` (title: out-of-the-box thinking) | — | `work` (naming) | Our operator named `OUT_OF_BOX` takes no partner hypotheses, while the operator that structurally matches A.7 (multi-concept analogy, "adapted rather than replicated") is `INSPIRATION`. The name and the content are attached to different operators | Rename, or correct the mapping note | S |

**Most faithful:** `reflection-03` is a near-exact mirror, and `ranking-05`'s
turn envelope is genuinely enforced in code at the published values (3-5
typical, 10 max) — both verified before granting the verdict.

### Mirror pass 3 of 4 — the seven pseudocode listings (complete)

**This one is largely a faithful mirror.** 68 algorithmic steps: **32 mirrored,
24 adapted with a named and citable reason, 11 additive extras, 1 unjustified
drift.** The adaptations are overwhelmingly the durable-task model doing what a
straight-line listing cannot.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| MC-1 | `pseudocode/04-ranking.md:28` | "Prioritize new hypotheses or those with **similar Elo ratings**" | `work` | **We do the first half and not the second, and two documents claim otherwise.** `ranking_matchmaking.py::_priority` scores recency, `rank` — which rewards *higher* Elo, not closer — and coverage; `_partner_score` adds only a same-**cluster** bonus, which is proximity, not Elo. No term anywhere scores Elo closeness. Verified directly. **PARITY `RANK-PAIRING-001` and the pinning test's own docstring both assert the property exists**, so the gap is invisible to CI and to the ledger — a false claim of agreement, the defect class this repo has been bitten by before | Add an Elo-closeness term; **and correct the PARITY row and the test docstring** | S |
| MC-2 | `pseudocode/07-meta-review.md` | Meta-review runs as **periodic** system feedback | `adapted`, but with a runtime effect larger than that word implies | It fires only immediately before an EVOLVE dispatch, never independently. **A run that never evolves never runs meta-review** — and every downstream consumer (generation prompts, the ranking judge, the final overview) then silently gets nothing | Worth an explicit decision, not a silent adaptation | S |
| MC-3 | `pseudocode/03-reflection.md` | Deep verification precedes tournament entry | `adapted`, consequential | Ours runs **after** ranking, so a hypothesis with unsound core assumptions can win matches and be bred from before verification inspects it. FINDINGS `E9` already records the ordering; the breeding consequence is the part worth stating | `E9`'s note | S |
| MC-4 | the listings, by absence | — | `work` (record only) | Our blocking, never-revisited initial-review disposition gate **has no counterpart in any published listing**. `engine/CLAUDE.md`'s own gotcha records it disqualifying 20 of 22 ideas in one production run. An invented gate with that much authority should be labelled as invented | A ledger row naming it a local addition | S |
| MC-5 | `pseudocode/06-proximity.md` | "for each pair" | `adapted` | Similarity is computed only **within** LLM-declared clusters, so two hypotheses in different clusters get no edge at all rather than a low-weight one — narrower than the listing's literal quantifier | Note the narrowing | S |

### Mirror pass 4 of 4 — architecture and execution flow (complete)

Read from the primary sources only — the arXiv paper, the Nature SI including
its own Supplementary Note 8 pseudocode (SI L905-1099), and never the
clone-authored consolidations.

**The most consequential finding in this study.** `docs/PARITY.md` cites the
corpus **65 times across 51 rows**, all four of them consolidations
(`SSR`, `TE`, `ARCH`, `RGV`) — and **zero rows cite either paper by name**.
Many are labelled `PAPER — SSR §7`, which reads as "the paper says this", while
pointing at a clone's summary. The legend does define SSR honestly as "the
canonical local consolidation", so the document is not lying; the row labels
are what conflate. Given this study's own measurements — R2 47 rows zero
paper-backed, R3 **49 rows, one** paper-backed, R6 71 rows zero paper-backed —
a large share of those 51 rows cite something with no published basis. This
extends `DEL-13` from "rewrite paths before deleting" to "re-source the rows".

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| MA-1 | `docs/PARITY.md:22-58` and its rows | The ledger's four corpus shorthands | `work` | 51 rows / 65 citations point at consolidations; 0 point at the papers; the `PAPER — SSR §n` label conflates the two. **This is the answer to "where do they specify the flow" — the ledger currently does not say** | Re-source every row against the papers; drop or relabel what has no published basis | L |
| MA-2 | Nature SI Note 8, `DecideNextSteps`, L950-972 | Independent `IF`s let one decision pass **stack several follow-up tasks** — rank *and* evolve *and* meta-review *and* report | `work` | `scheduling/policy.py` is a strict single-winner precedence chain: one task per orchestrator cycle, no stacking. This is a real behavioural difference in how fast a run makes progress | `scheduling/policy.py` | M |
| MA-3 | paper, task-framework section | Per-hypothesis independent task chaining | `work` | **Our two execution paths differ from each other here.** The LangGraph engine reviews a whole batch as one synchronous barrier per node; only the durable `app/` path recovers per-hypothesis fan-out. The "reference" engine and the shipped product genuinely diverge — a known hazard in this repo | Name the divergence; decide which is canonical | M |
| MA-4 | paper, Figure 2 caption | One continuously-adaptive **Supervisor** | `work` (naming + behaviour) | Split into a one-shot `supervisor_node` that plans once and is never revisited, plus a continuously-running `orchestrator_node` — **a name appearing in neither primary source**. `R12-17`/`R12-18` are downstream of the same fact: the Supervisor synthesizes once and nothing revisits it | Either revisit the plan mid-run, or record the split as deliberate | M |
| MA-5 | paper L205 | The research overview is **periodic** and **feeds back into Generation** | `work` | Ours runs exactly once, at termination, with no edge back into `generate`. One of the paper's two described self-improvement channels is reporting-only in our system | Graph edge + periodicity | M |
| MA-6 | paper L7 | "Flexible compute scaling" as the headline framing | `work` | Realized as four fixed tier presets chosen once at run creation, not continuous mid-run adaptation | Record as a labelled divergence, or implement | L |

**Mirrored exactly**, verified: initial Elo 1200; the debate turn envelopes
(3-5 typical, 10 max) for *both* generation and ranking debates; two-stage
safety gating at goal intake and per hypothesis; meta-review critique feedback
reaching generation prompts.

**Thirteen things the papers do not specify**, recorded so nothing gets
mirrored that Google never published: no storage technology or wire format for
the task queue or context memory; no concurrency model for "worker processes";
no weighting formula behind "assigns weights and resources to each agent"; no
predicate for "quality has stopped improving"; no definition of "enough time
has passed" (used twice as a trigger); no Elo K-factor, annealing, or margin
scaling; no pool size, match count, or iteration ceiling — `MaxIdeas` and
`MaxMatchesPerIdea` appear as named variables with **no values**; no queue
priority or fairness scheme; no durability semantics beyond one sentence about
restarts; no statement of how the NL interface, queue and memory physically
relate; no fixed-DAG-versus-dynamic-graph requirement; no safety-classifier
internals. `constants_tournament.py:20-38` already documents several of these
gaps correctly in its own comments — that is the pattern the rest should follow.

### What the pins do and do not buy

Five test modules read this corpus, and they are the reason the mirror has held
where it has held. But they pin **literals**, not fidelity: a constant asserted
equal, a heading list compared. Nothing today asserts that a prompt still
carries its source's instructions, that an algorithm still runs its steps in the
published order, or that an output still uses the published words. `R8-1` is the
proof — it survived every existing check.

---

## How to read a row

| Field | Meaning |
|---|---|
| `ID` | `R<region>-<n>`, stable. Cite these when acting on a row. |
| `Source` | The corpus file, plus section or line. Every row is a claim about a file. |
| `What it states` | One sentence, in the corpus's own terms. |
| `Status` | See below. |
| `Decided by` | The repo file that settles the status — a code path, a test nodeid, a PARITY ID, a FINDINGS ID. Never empty for `done` or `reject`. |
| `Proposed sink` | Where it lands if it is work: a PARITY row, a pin test, a code change, an ADR, or `none`. |
| `Effort` | S / M / L. |

**Status vocabulary**

- `done` — already implemented, recorded, or pinned. The cited evidence proves it.
- `work` — a real, unrecorded item. This is the checklist.
- `reject` — clone-authored, invented, an accepted divergence, or inside a
  recorded evidence boundary.
- `external` — needs data, access, or expertise this repo cannot supply.
- `unclear` — could not be decided from the corpus and the tree together.

## Rules this study followed

1. **Every row was checked against the current tree before being written.** A
   behaviour that already exists is `done`, not work.
2. **Accepted divergences were not re-litigated.** `docs/fidelity-audit/FINDINGS.md`
   marks deliberate local choices `=`. Contradicting one required *new primary
   evidence from the corpus*; where that happened the row says so and quotes the
   source.
3. **Much of the corpus is clone-authored.** Files 02–09 present local design as
   "Google requirements"; the corpus-integrity corrections table in FINDINGS.md
   is the list. Rows drawn from those files carry an attribution judgement.
4. **Evidence boundaries are not work.** Anything unknowable from public sources
   is `reject` or `external`, never a code task that could falsely "complete".

## Region map

| # | Region | Files | Verdict in one line |
|---|---|---|---|
| R1 | `source-system-reference.md` | 1 (202 L) | Largely paper-backed; the one consolidation that is *not* substantially invented |
| R2 | `product-surface-and-ux.md` | 1 (248 L) | Mostly clone-invented product surface |
| R3 | `system-architecture-and-orchestration.md` | 1 (407 L) | Local design (Postgres, AG-UI/SSE, ResearchLoop) |
| R4 | `agent-coalition-specifications.md` | 1 (179 L) | The invented 12-agent roster lives here |
| R5 | `tournament-evolution-and-evaluation-criteria.md` | 1 (194 L) | Elo math and operators real; 3-persona debate invented |
| R6 | `retrieval-grounding-and-verification.md` | 1 (192 L) | Source lists checkable; GRADE/KG-novelty invented |
| R7 | `context-engineering-and-memory.md` | 1 (162 L) | Expected to yield nothing — see the region's own note |
| R8 | `prompting-architecture-and-prompt-library.md` | 1 (361 L) | Part A already extracted; B and C clone-authored |
| R9 | `build-methodology-…` + `tech-stack-findings` + `README` | 3 (328 L) | Clone evaluation design; §7 and §15 may hold live decisions |
| R10 | `research/papers/` | 2 (2,566 L) | **Highest-value unmined region** — primary Google source |
| R11 | `research/supplements/` | 26 (~11,400 L) | Nature SI Notes 1–7 largely unmined; one full published run |
| R12 | `research/extracted-artifacts/outputs/` | 45 files | Richest per file read; the 4,187-line MASH report sits here |
| R13 | `media/` | 5 folders (36 MB) | Mostly moot or out of scope; **holds the only unrecoverable content** |

---

## R13 — `media/`

Handled first because it is the only region that constrains *how* the folder can
be deleted, not just what must be taken out of it.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R13-1 | `media/live-footage/` (2 mp4, 16 MB) | The only screen recordings of the real product in motion; the source of the plan-config transcription | `work` | `.gitignore:46` ignores `media/**/*.mp4`, and `git status --ignored` reports the whole folder ignored — it is not in git history, so deletion is unrecoverable. **Measured across the whole region: 80 of 82 media files are tracked; only these two mp4s (16.4 MB — 30.0 s at 3102×1424 and 80.0 s at 2490×1954, both H.264) are not.** They are the corpus's only unrecoverable content | Owner decision: archive outside the repo, or extract and commit the frames that are cited | S to decide, L to extract |
| R13-2 | `media/live-footage/`, via `docs/decisions/2026-06-21-gemini-and-video-tweaks.md` | That ADR reads a tier selector of **Explore / Express / Standard** (three options) and a focus selector of evidence / novelty / balance / breakthrough from this footage | `work` | The ADR itself, vs `plan-configs/mash-…-research-plan.md`, which reads **Express / Standard / Extended / Ultra** (four) from the same folder | A note on every row resting on either capture, naming which one | S |
| R13-3 | `media/live-footage/mash-fibrosis-research-plan-and-run.mp4` frame ≈66 s | `docs/UI-FIDELITY.md` cites this exact frame as the evidence for the four-tab mapping, and calls the corpus "the FUNCTIONAL SOURCE OF TRUTH (still on disk)" | `work` (**downgraded** — this row overstated the risk) | `docs/UI-FIDELITY.md:36-41`, `:109-111`. The frame itself is unrecoverable, but the claim it supports is not: `media/hypothesis-generation/esn-knowledge-base-analytical-pipelines.jpg` is **tracked in git** and shows the tab bar directly — `Ideas \| Knowledge Base \| Summary \| Run Specification`, Knowledge Base active with a green underline. The citation needs re-pointing, not frame extraction | Re-point the UI-FIDELITY citation at the tracked JPG | S |
| R13-4 | `media/computational-discovery/` (10 files, 612 K) | Captures of the Computational Discovery product surface | `reject` | The feature was removed 2026-08-26; recorded in the memory of that removal and absent from the tree | `none` | S |
| R13-5 | `media/literature-insights/` (10 files, 764 K) | Captures of Google's **Literature Insights**, a different product | `reject` | Never in scope for this repo; FINDINGS' corpus-integrity table already notes NotebookLM belongs to that product, not this one | `none` | S |
| R13-6 | `media/google-labs-page/` (13 MB — the single largest item in the corpus) | A saved HTML capture of `labs.google/science/` with its `_files/` assets, saved 2026-06-23 | `work` (**was `unclear`; the triage settles it**) | All 41 `_files/` were opened: **18 are inert tooling** (GTM ×2, YouTube player runtime ×2, widget-API + iframe loader, Lottie, cookie bar ×2, Fonts CSS ×2, closure bootstrap, site CSS/JS ×2, `www-player.css` ×2) and carry nothing. But the **HTML itself carries Google's own product copy** — see R13-7 — which my earlier row wrongly assumed only the PNGs held | Extract the copy (R13-7), then prune to the HTML, 2 PNGs and 3 SVGs | S |
| R13-7 | `google-labs-page/experiments-on-the-future-of-ai-driven-science-google-labs.html`, extracted with `textutil` | Google's own description of this product. `og:title` is **"Gemini for Science"**; the page offers **"Express interest"** (a waitlist, not self-serve). Three cards, each credited to its underlying technology; ours is **Hypothesis Generation — "Built with Co-Scientist"**, tagline *"Generate novel research ideas through a multi-agent system that simulates the scientific method to help identify knowledge gaps and propose testable research plans."* Its four claimed capabilities are **Collaborative Research Partner** (chat to refine challenge, preferences and focus areas *before* initiating a run), **Tournament-Style Evaluation**, **Grounded Knowledge Base** ("ideas are linked to a comprehensive knowledge base of verified scientific references used by the agent during the run"), and **Critical Flaw Detection** ("distinguish high-potential directions from non-viable ones") | `work` (record only) | This is the product's own statement of what it is, and it is not quoted anywhere in `docs/`. All four capabilities have analogues in the tree, so this is not a gap list — it is the missing **primary citation** for framing claims that `EXPLAINER.md` and `FIDELITY.md` currently make in their own voice | A short quoted block in `docs/FIDELITY.md`, cited to this file | S |
| R13-8 | `hypothesis-generation/esn-ideas-agent-insights.jpg` (tracked) | The finished-run **Agent Insights** panel carries a synthesis paragraph and exactly four plain-count tiles: **High potential ideas 4**, **Non-viable ideas 20**, **Number of verified ideas 15**, **Sources analyzed 444** | `done`, with a fixture worth keeping | Corroborates the counts rule in `AGENTS.md` from the product side: verified (15) is **larger** than high-potential (4) and the two buckets (4 + 20 = 24) partition the run, so the three numbers are three independent axes. That is exactly the shape that made FINDINGS `D15` visible when our tile was handed the High Potential count | A regression fixture using these four published values | S |
| R13-9 | `hypothesis-generation/esn-high-potential-idea-poma-hub.jpg` and `esn-ideas-rmsa-high-potential-and-mip-non-viable.jpg` (both tracked) | Idea cards are plain cards — a small uppercase categorical badge (**HIGH POTENTIAL** green / **NON VIABLE** amber), title, abstract, and a "Chat with Agent" link. **No numeric score, rank or Elo appears on any card.** The published MASH report likewise carries no score in any of its 9 idea entries | `done` | **Corroborates FINDINGS `D1`, which is already closed `=`** on precisely this reading ("Google deliberately hides Elo and shows a card list"). The new weight is that these captures *are* D1's primary evidence, and that Computational Discovery's own screens in the same corpus **do** show numeric Score / Rank / Parent fields — so hiding the number in this product is a deliberate choice, not a platform limit | `none`; but see DEL rows — D1's evidence must not become unciteable | S |
| R13-10 | `hypothesis-generation/esn-run-executing-idea-tournament.jpg` (tracked) | The run-in-progress view is a status line ("Executing Idea Tournament..") plus a progress bar, three tiles — **Time remaining 6h 23m**, **Sources Analyzed 490**, **Ideas explored 25** — and an **ACTIVITY LOG** table. Not a bracket or leaderboard | `unclear` | Two things are new here and neither is in the ledger: a **"Time remaining" estimate** on a running job, and the fact that Sources Analyzed *falls* from 490 mid-run to 444 at completion, implying the final figure counts sources actually used rather than fetched. Whether we estimate remaining time at all needs checking against the run view | Progress model — needs a verify pass | S to check |
| R13-11 | `hypothesis-generation/esn-knowledge-base-*.jpg` (tracked) | The **Knowledge Base** is a first-class tab with a right-hand table-of-contents rail listing ~11 topic sections, each rendered as a Summary paragraph behind a "Show more" toggle | `work` | Independent product-side confirmation of `R12-6` — which found we compute the knowledge base, persist it, and render it in the UI, but omit it from the exported markdown. These captures show the published surface it is modelled on | Folds into `R12-6` | S |
| R13-12 | `hypothesis-generation/esn-poma-hub-hypothesis-full-detail-with-diagram.jpg`; `_files/-nmisG2OTKY.html` | Two corpus-integrity notes. (a) That JPG's **content does not match its filename** — it shows a Computational Discovery splash screen credited to "Carl Elkin", not an ESN/POMA-Hub hypothesis detail. (b) The saved YouTube iframe carries a real video title, *"Hypothesis Generation: Unlocking the Secret Defenders of the Immune System \| Gemini for Science"* — an artifact that is **recoverable externally**, unlike the two mp4s | `work` (a) / `external` (b) | (a) Any future row citing that filename would cite the wrong image. (b) Named so the deletion plan can distinguish externally-recoverable pointers from genuinely unique content | (a) A rename or a note; (b) record the title beside `R13-1` | S |

---

## What blocks deletion

Three distinct blockers. The first is the dangerous one.

### 1. Four test modules read the corpus, and the way they fail depends on *how* you delete

Every pin guards with `if not _REFERENCES.is_dir(): pytest.skip(...)`, then
`assert path.is_file()`. `references/` now contains only `core/`. So:

- Deleting `references/core/google-co-scientist/` but **leaving `references/` on
  disk** → every pin **fails loudly** on its assert. Safe.
- Deleting `references/` **entirely** → every pin **silently skips**. This is the
  failure the audit warns about, and it is triggered by removing the directory
  itself, not by emptying it.

The owner's decision is that each pin must carry its published values and
vocabularies **inline**, with a citation comment, before the folder goes.

| ID | Pin | What it reads out of the corpus | Effort |
|---|---|---|---|
| DEL-1 | `engine/tests/_published_corpus.py` | The shared locator: `published_output()` and `published_pseudocode()`. Both engine pin modules go through it | S |
| DEL-2 | `engine/tests/test_published_pseudocode_invariants.py` → `04-ranking` | The tournament entry rating, asserted `== INITIAL_ELO_RATING` (1200); and the pairing line about new and similarly-rated ideas, asserted against `weights.recency/.rank/.similarity_bonus > 0` | S |
| DEL-3 | same → `01-supervisor` | Literals `NumberOfIdeas < MaxIdeas` and `NumberOfMatchesPerIdea < MaxMatchesPerIdea`, asserted against termination reasons `{max_ideas, max_matches_per_idea}` | S |
| DEL-4 | same → `05-evolution` | The parent count, asserted `== EVOLUTION_PARENT_COUNT`; literals `Treat it like a brand new idea` and `Agent: Reflection, Action: "ReviewHypothesis"` | S |
| DEL-5 | same → `07-meta-review` | The top-N, asserted `== RESEARCH_OVERVIEW_TOP_K`; the line about reading reviews and debate transcripts | S |
| DEL-6 | same → `03-reflection` | The assumption-decomposition lines, asserted against the schema item `{assumption, verification, status}` | S |
| DEL-7 | same → `02-generation` | Literals `Strategy 1: Use existing knowledge` and `Strategy 2: Simulate debate`, asserted against `{literature_tools, debate}` | S |
| DEL-8 | `engine/tests/test_published_artifact_shapes.py` → 3 `specific-aims/` exemplars | Depth-4 heading labels, asserted equal to `_AIMS_PAGE_BLOCKS \| _AIMS_PER_AIM_BLOCKS`, plus the "schema adds nothing the exemplars lack" assertion | M |
| DEL-9 | same → `reviews/reparixin-deep-verification-probing.md` | Labels asserted `== ["question", "answer", "reasoning"]` | S |
| DEL-10 | same → `ranking-tournament/als-tournament-debate.md` | Asserted multi-turn (`len(turns) > 2`), a verdict exists, and the template contains `better idea:` | S |
| DEL-11 | same → a research-overview exemplar | Overview required keys `== {summary, research_directions}` plus the direction's required keys | S |
| DEL-12 | `app/tests/test_published_plan_config.py` → `plan-configs/mash-…-research-plan.md` | Offered Tier options `== list(RUN_TIER_DEFAULTS)`; offered Focus options `== list(RUN_FOCUS_VALUES)`; plan carries `{Requirements, Attributes, Criteria, Focus, Tier}` plus `Goal`. **This pin is also the evidence for R12-KL1**, so inlining must preserve the citation, not just the values | S |

### 2. Prose citations that need a destination

| ID | Where | What it cites | Effort |
|---|---|---|---|
| DEL-13 | `docs/PARITY.md:23-25`, `:55-58` | Names `source-system-reference.md` as the canonical local consolidation in its **source hierarchy**, and defines the shorthands SSR / TE / ARCH / RGV. Measured citation counts: **`SSR §` 41, `TE §` 8, `ARCH §` 9, `RGV §` 7 — 65 in total** across four corpus files | L |
| DEL-14 | `docs/UI-FIDELITY.md:36-41`, `:109-111` | Calls the corpus the functional source of truth and cites a specific mp4 frame — see R13-3 | M |
| DEL-15 | `engine/src/co_scientist/prompts/templates/README.md:5` | Cites `prompting-architecture-and-prompt-library.md` §4 as where the eight published prompts are reproduced | S |
| DEL-16 | `docs/EXPLAINER.md:5`, `:350`; `docs/FIDELITY.md:14`; `AGENTS.md:14` | Point readers at the folder and at `media/` | S |
| DEL-17 | `docs/fidelity-audit/README.md:65`, `FINDINGS.md:480` | Cite "files 02–09" as the clone-invented set — a reference to the folder's own structure | S |

**DEL-13 is not a mechanical path rewrite.** R1 turned out to be roughly
two-thirds paper-backed, so an `SSR §n` citation behind a PAPER-class row should
be re-pointed at the paper itself, while one behind a CLONE-class row should be
restated as a local decision with no external citation at all. That judgement is
per citation.

### 3. The only content that is not recoverable

`media/live-footage/*.mp4` — gitignored, therefore never in history. Everything
else in the folder is tracked and can be recovered with
`git log --diff-filter=D --name-only`. See R13-1.

---

## R12 — `research/extracted-artifacts/outputs/`

`R12-1` … `R12-19` were verified directly rather than by sweep, because they
carry the study's named leads. The remainder of the region continues below them.

### The run-plan vocabularies (Known Lead 1) — confirmed, and it contradicts the ledger

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R12-1 | `plan-configs/mash-…-research-plan.md` `## Tier` | The product offers **Express / Standard / Extended / Ultra**, in that order, with the selected option bolded | `work` | `app/app/run_modes.py:15` `RUN_TIER_PATTERN = "^(express\|standard\|extended\|ultra)$"`; asserted equal by `app/tests/test_published_plan_config.py::test_run_tiers_are_the_ones_the_product_offers` | A PARITY row citing the pin test, **and a correction to FINDINGS `B1`** | S |
| R12-2 | same, `## Focus` | The product offers **Prefer evidence / Balance / Prefer novelty / Breakthrough**, in that order | `work` | `app/app/run_modes.py:17-22` `RUN_FOCUS_VALUES`; asserted equal by `…::test_run_focus_values_are_the_ones_the_product_offers` | A PARITY row, **and a correction to FINDINGS `B2`** | S |
| R12-3 | same, whole file | The plan is the goal plus five sections: Requirements, Attributes, Criteria, Focus, Tier | `done` | `app/tests/test_published_plan_config.py::test_the_plan_carries_every_section_the_product_shows`; built by `run_modes.setup_config` | `none` | — |

FINDINGS `B1` reads "Four tiers replace Google's exactly-two Standard/Advanced"
and `B2` reads "Four-way focus selector has no Google basis". Both are marked
`=` — closed as deliberate local extensions. **The transcription of Google's own
footage contradicts both**, and a pin test has been asserting the match all
along without any ledger row recording it. This is the bar FINDINGS itself sets
for reopening a boundary item: new primary evidence.

**Carry this caveat.** R12-1 and R12-2 rest on the plan-config capture. The
2026-06-21 ADR read an *earlier* capture from the same footage folder showing a
three-option tier selector (Explore / Express / Standard) — see R13-2. Any row
written from this must name which capture it rests on.

### The rest of the plan block

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R12-4 | `plan-configs/mash-…` `## Criteria` | Three named settings with values: `Idea correctness: Required`, `Idea novelty: Required`, `Maximize impact: Yes` | `work` | `app/app/run_modes.py:39-44` — `DEFAULT_CRITERIA` is four free prose strings ("Scientific soundness", "Novelty over known mechanisms", "Discriminating experimental design", "Translational feasibility"). Different in both shape and content | PARITY row / `run_modes` change | S |
| R12-5 | `plan-configs/mash-…` `## Attributes` | A **structured per-run scoring rubric**: five named attributes, four defined on an explicit 1–5 scale with anchor text at 1/3/5 (Mechanism Novelty, Human Relevance, Clinical Translatability, Validation Plan Strength) and one categorical with an enumerated value set (Target Area: Epigenetics / Stellate Cell Biology / Stromal-Immune Crosstalk) | `work` | `app/app/run_modes.py:140` — ours is `attributes: list[str]` of free strings via `clean_string_list`; `app/app/runs_crud_resolve.py:83` maps the UI's `focus_area` into it. The pin test checks only that the heading exists | PARITY row + run-spec schema | M |

R12-5 is the rubric FINDINGS `A2` said was missing — "no rubric governs ranking,
debates, or self-improvement". `A2` is marked `✓`, but it was closed on the
*criteria* half only; the attributes half, which is where the actual 1–5 scales
and anchors live, is still free text.

### The MASH Goal Report (Known Lead 2)

`research-overviews/mash-liver-fibrosis-reversal-therapeutic-hypothesis.md` is
4,187 lines, but the substance is lines 1–832: lines 832–4,185 are one flat
`References` list of linked article titles, and line 4,186 repeats `Top ideas`.

Our renderer (`app/app/report_markdown.py::render_report_markdown`, 429-455)
emits, in order: title and provider, `## Summary`, `## Top hypotheses`,
`## Meta-review insights`, `## Citation audit`, `## Research Overview`,
`## NIH Specific Aims`, `## Research Contacts`, data sources.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R12-6 | MASH report L459-745 | A `Knowledge Base` section that is a bare wrapper over a `Knowledge Summary` holding **7 distinct subject headings** (one bold-only, three H1, three H2 mis-nested under an unrelated topic — the heading levels are a conversion artifact, so the count is by subject, not by markup). Each subdivides into H4 sub-sections of dense encyclopedic prose. It carries **zero citations of any kind** — no bracket markers, no links, verified by grep over the whole span — while report sections 1-9 cite inline throughout | `work` | **Computed but never rendered.** `report_content._knowledge_base_topics` / `_synthesized_knowledge_base_topics` compute it, `report_build.py:206-224` assembles it, `report_markdown.py:176` persists it into the payload, and the UI renders it — but `ReportMarkdownInputs` (`report_markdown.py:420-427`) has no such field and `render_report_markdown` emits no such section | Report markdown renderer + a PARITY row | M |
| R12-7 | MASH report L331 (`8 Key Findings and Unexpected Molecular Connections`) and L818 (`Unexpected Connections`) | The report surfaces cross-idea molecular connections as their own sections | `work` | **Computed, consumed by prompts, never rendered.** `agents/meta_review/meta_review.py:355` produces `potential_connections` and `prompts/_common.py:127` re-injects it downstream, but `_META_REVIEW_BULLET_SECTIONS` (`report_markdown.py:212-216`) renders only common_strengths / common_weaknesses / emerging_themes plus strategic_recommendations | Report markdown renderer | S |
| R12-8 | MASH report L3-40 (`Research Goal Details`: Goal / Requirements / Attributes / Criteria) and L53 (`2 Evaluation Criteria`) | The published report opens with the run's full configuration, and separately restates the criteria | `work` | `report_markdown.py:459-470` — our header is only `# Research Report — {goal}`, a provider line, and an optional Summary. Requirements, attributes and criteria are collected by `run_modes` but never rendered | Report markdown header | S |
| R12-9 | MASH report L277, L299, L315 | Sections `5 Comparison of Candidate Ideas`, `6 Comparison of Candidate Ideas`, `7 Comparison to Existing Solutions` | `work` | **Absent entirely** — grep over `engine/src/co_scientist/schemas/`, `app/app/report_*.py` and `agents/meta_review/` finds no `existing_solution`; the `comparison` hits are `schemas/ranking.py` pairwise-match comparison, a different thing | Report renderer + a synthesis schema field | L |
| R12-10 | MASH report L746, L789, L795 | Sections `Open Questions`, `Clear Patterns`, `Unexpected Patterns` | `work` | **Absent entirely** — no `open_questions` and no `clear_pattern` anywhere in the schemas, report code, or meta-review agent | Report renderer + synthesis schema | M |
| R12-11 | MASH report L345 (`9 Recommendation and Strategic Roadmap`) | A recommendation section presented as a staged roadmap | `work` | Partly present: `report_markdown.py:222` renders `### Strategic recommendations` as a bullet list, not a roadmap | Report renderer | S |
| R12-12 | MASH report L832-4185 | A flat `References` list of **3,259 unique entries** — bulleted markdown links (never numbered), no topic grouping, **zero duplicate targets**, every URL wrapped in a `google.com/url?q=` redirect. Hosts: NCBI 2,599 (74%), bioRxiv 473 (13%), arXiv 273 (8%), 70 distinct hosts in all | `unclear` | **The absence is confirmed**: no bibliography exists anywhere — `report_markdown_sources.py:57-133` emits per-source *search counts* and the deduplicated *questions* they served, explicitly not a source list, and grep for `bibliography` / `reference_list` finds nothing. What stays open is whether a flat list is *wanted*: ours is `## Citation audit` (per-claim labels) plus data sources, a different artifact rather than a subset. **The verify pass called this `work`; it is kept `unclear` because the decision is the owner's, not the code's** | Owner decision | S |
| R12-13 | MASH report L43 and L4186 | `Top ideas` appears twice — the report opens and closes with it | `unclear` | Ours emits `## Top hypotheses` once. This may be an artifact of the transcription rather than the product's design | `none` unless the owner wants it | S |

**Caveat on R12-6 … R12-13.** This is *one* published report from *one* run.
It is strong evidence that these sections exist and weak evidence that every
Google run emits them. Rows should say "present in the one published complete
report", never "Google always emits".

### Published scoring and verdict vocabularies

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R12-14 | `validated-outputs/kira6-detailed-output-validated.md`, corroborated by `supplements/ai-assisted-drug-re-purposing-…-file-1.md` | A score composition is printed: `score = novelty + details + usefulness + pairwise rank = 11` | `work` (record only) | Ours is the mean of the review rubric's axes (`agents/reflection/review_helpers.py`). A sum of four terms reaching 11 is neither a 1–5 nor a 1–10 mean | A ledger row recording our composition as a labelled local choice against this published one | S |
| R12-15 | `kira6-detailed-output-validated.md`, "Reasoning about assumptions" | Per-assumption wording: Plausible / Plausible-but-requires-investigation / Plausible-but-requires-testing / Unknown | `unclear` | Ours is a closed enum `{supported, uncertain, unsupported}` (`engine/src/co_scientist/schemas/review.py:283-289`) with the verdict enum `holds/weakened/undermined` (`:243-246`). But Google's is **prose in a rendered document**, so one exemplar is weak evidence that a closed vocabulary exists at all | Review schema vocabulary, only if the owner wants it | S |
| R12-16 | `research-overviews/als-research-overview-and-contact.md` | The only research-contacts exemplar carries exactly two observable fields: researcher name(s), plural-capable and redacted in source as `[Researcher names]`, and a free-text relevance paragraph. No affiliation, institution, or email field appears | `unclear` | Ours renders `### {contact name}` plus an evidence line (`report_markdown_overview.py:273-290`). Whether our schema invents fields the exemplar lacks needs the same check `test_specific_aims_schema_adds_nothing_the_exemplars_lack` already applies to Specific Aims | A pin test, if it does add fields | S |
| R12-17 | MASH report L19-25 (`Attributes`) | The run's Attributes are **named rating scales, not labels**: four carry a 1-5 scale with worked anchor examples at 1, 3 and 5 (Mechanism Novelty, Human Relevance, Clinical Translatability, Validation Plan Strength) and one is categorical with a fixed value set and no scale (Target Area). They are printed to the reader at the top of the report | `work` | **Half-built, and the built half is invisible.** The reader-facing list is plain strings (`run_modes.py:140` `list[str] \| None`, `DEFAULT_ATTRIBUTES` at `:34-38`), joined into generation prompts by `prompts/generation_formatting.py:20-23`. But the Supervisor already synthesizes the published shape: `schemas/planning.py:127-146` defines `config_synthesis.attributes` as "up to 3 axes used to stratify and compare ideas, each with a 1-5 scoring rubric", `prompts/review.py:179-185` injects them as **"Stratification attributes (score each 1-5)"**, and `drain_supervisor_plan.py` persists them every run. Two gaps: nothing renders them (zero `config_synthesis` hits across `app/frontend/src`, and `render_report_markdown` never touches them), and they are **prose guidance, not a scored field** — the review schema is the fixed 8-axis 1-10 rubric at `schemas/review.py:14-45`. FINDINGS `K4` covers the fixed-8-axis half from the gating angle only | Surface `config_synthesis.attributes` in the run plan and report header; decide separately whether reviewers score against them | M |
| R12-18 | MASH report L31-35 (`Criteria`) vs L49-59 (`2 Evaluation Criteria`) | Two different things share the word. The run's **Criteria** are three fragments — "should be correct", "should be novel", "should maximize impact" — which are verbatim the paper's A.3.1 *Constraints*. The report's **section 2** is six goal-specific criteria synthesized for this run, with names like "Kinetic Feasibility and Experimental Readouts" and "Human Data Integration and Accuracy" | `work` | **We synthesize the second kind and then hide it** — the same half-built shape as `R12-17`. Reader-facing criteria are always `DEFAULT_CRITERIA` (`run_modes.py:39-44`) or raw user strings. The interview — the only LLM path that derives planning fields from the goal — produces exactly `research_challenge`, `focus_area`, `preferences` (`interviews_models.py:41-43`); `runs_crud_resolve.py:81-84` maps two of them and never sets `criteria`, so every chat-created run falls through to the defaults. The frontend renders criteria read-only. Engine-side, the Supervisor **does** emit goal-specific criteria: `schemas/planning.py:80` declares `workflow_plan.review_phase.critical_criteria` as a string array, `templates/supervisor.md:117` defines it as "domain-specific criteria reviewers should emphasize", and `prompts/review.py:142-143` injects it into the review prompt. It stops there — no frontend or report-render reference exists, and it is unscored prose, not a named axis. Separately, `review_gate.py:73-85` substring-maps *supplied* criteria onto two fixed gate axes. FINDINGS `A2` is closed, but it asks whether *supplied* criteria govern anything (they do) — not whether any are ever *derived* | Criteria synthesis in the interview or supervisor, and a PARITY row | M |
| R12-19 | MASH report §3.2 `[17 (unsupported)]`, §3.3 `[31 (leaning accurate)]` | An inline citation marker inside body prose can carry its own **verification verdict as a parenthetical tag** | `work` | Absent, and there is a second defect underneath it. Our nearest analogue is `_render_claim_evidence` (`report_markdown.py:298-312`), a **separate bulleted block after the prose** — `- **Supported · categorical** — <claim>` — plus a counts-only `## Citation audit` (`:394-405`). Neither annotates a marker in a sentence. Underneath: `generation_debate.py:144-156` prompts the model to write `[C1]`-style inline keys into `literature_grounding`, and **`report_markdown.py` never renders `literature_grounding` at all** (only `mechanism` and `expected_effect`, `:331-336`) — so those keys are generated, paid for, and discarded | Inline verdict tags, **and** a decision on whether `literature_grounding` should render | M |
| R12-20 | MASH report L41 | The report carries a provenance and caution line: **"Prepared by AI co-scientist on 2026-06-12. For research purposes only."** | `work` | Absent. `_render_report_header` (`report_markdown.py:459-471`) emits only the goal title, an italic provider line, and an optional Summary — no date, no system attribution, no caution. Grep for "For research purposes only", "Prepared by", "disclaimer", "not medical advice" across `app/app` and `app/frontend/src` returns **zero hits**. FINDINGS `A6` ("No AI/medical disclaimer anywhere") is open but scoped to the chat UI banner; the provenance half — who produced this and when — has no row at all. Note this is a **two-line fix on the artifact most likely to leave the building** | Report header | S |
| R12-21 | MASH report, each of the 9 ideas | Every idea closes with a bold `Category Description` block of five fields — Primary Target, Focus Area, Mechanism of Reversal, Validation Model, Safety Considerations — then a `Judgment:` field holding **qualitative prose**, never a number | `reject`, with one residual | The five names are this goal's vocabulary for the fixed structured shape we already implement faithfully — `findings-boundaries.md` lists "structured hypothesis shape: mechanism-naming title, prose, mechanism, experiment" under confirmed matches. Re-labelling our fields to one goal's wording is not a system capability. **The residual is the `Judgment:` field**: a short qualitative verdict per idea, which we have no analogue for — our claim-evidence block is structured, not a judgement | `none` for the field names; the `Judgment` field is a small optional add | S |
| R12-22 | MASH report, all 9 idea entries | **No numeric score, rank, Elo or confidence value appears anywhere in any idea entry.** Corroborated on the product side by the tracked idea-card captures (see `R13-9`) | `done` (**this row was wrong in an earlier draft and is corrected**) | We do the opposite, deliberately: `report_markdown.py:327` writes the Elo into every heading — `### {i}. {title}  _Elo: {rating}_`. That is the same choice FINDINGS `D1` closed as `=` ("Google deliberately hides Elo and shows a card list"), so the divergence is decided, not new. The one thing `D1` does **not** cover is scope: it is written about the React Ideas tab, and the markdown export is a second surface carrying the same divergence — worth naming in that row so a future reader does not rediscover it | A scope note on `D1` naming the export | S |
| R12-23 | MASH report L378 (`Research directions`) and L424 (`Review summary`) | Two further published sections. `Research directions` restates the five main directions as bulleted expansions plus an `Unexpected Research Directions` block; `Review summary` restates the run's evaluation criteria as **16 yes/no reviewer questions** grouped under 5 criteria — the rubric, not a verdict | `work` | `Research directions` has a partial analogue — the Research Overview's `research_directions` (title, importance, suggested experiments) — but no thematic clustering and no unexpected-directions block. `Review summary` is **absent**; the only repo hit for that string is an internal prompt label in `ranking_prompt.py`. Note `Review summary` is the reader-facing form of `R12-18`: it only exists because the criteria were synthesized per goal | Report renderer, downstream of `R12-18` | M |

*`R12-17` … `R12-23` were added in the closing round, after a full read of the
MASH report's 4,187 lines and a verify pass over eight specific claims. They are
the reason the `work` count moved.*

---

## R10 — `research/papers/`

`R10-1` … `R10-9` were verified directly. The rest of the region continues below.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R10-1 | `towards-an-ai-co-scientist.md` A.5.2, L1388-1424; second copy in the Nature SI Note 4.3 | A **15-item Specific Aims evaluation rubric** in two domains — "Significance and innovation (5 questions)" and "Rigor and feasibility (10 questions)" — each scored on a 5-point Likert scale (Strongly Disagree / Disagree / Neutral / Agree / Strongly Agree) | `work` | `evaluations/expert_review.py:29-36` — `RATING_AXES` is `(alignment, plausibility, novelty, testability, safety, impact)` plus `preference_rank`, i.e. the paper's five default criteria plus impact. A different instrument. Grepping the rubric's own wording across the repo returns hits only inside `references/`. PARITY `EVAL-EXPERT-SCHEMA-001` is `verified` against the 6-axis schema and never mentions this rubric | A PARITY row, an `evaluations/datasets/` rubric artifact, and an `expert_review` export mode | M |
| R10-2 | same, L1390-1402 | The rubric is a **pilot framework** by oncologists at a US institute, inspired by NIH Specific Aims criteria, deliberately LLM-specific (it emphasises logical consistency and public-knowledge use, and explicitly tests for hallucination and factual inaccuracy), and explicitly *not* a validated instrument — it "would require considerable further research… including assessment of validity and reliability" | `work` (constraint on R10-1) | The paper's own text | The same row as R10-1 must carry this caveat | S |
| R10-3 | same, A.4.2 L1342-1344 | The expert-review selection gate was "co-scientist review score ≥ 4 **and** DepMap score ≥ 0.99", and Figure A.23 describes "five AI co-scientist review score groups" from 1 to 5 — so **the published co-scientist review score is on a 1–5 scale** | `work` | Ours is 1–10: `engine/src/co_scientist/schemas/review.py:27` and `prompts/templates/review.md:11` ("score 1-10 for each"), with `constants.NOT_VIABLE_SCORE = 2` and `NEEDS_REVISION_SCORE = 4` keyed to that band. FINDINGS `E15` records our rubric as 1–10 and calls the audit's "1..5" stale, but never notes the paper's own score is 1–5 | A PARITY row recording our scale as a labelled reconstruction, or a change | S to record, M to change |
| R10-4 | same, A.5.1 L1366-1386 (Table A.2) | The Specific Aims proposal set is **78 proposals** ("Grand Total 78") over 16 named TCGA cancer types | `external` | Google's own generated dataset, not a behaviour. PARITY `EVAL-EXPERT-RESULTS-001` already carries the expert-study half as `external` | `none` | — |
| R10-5 | same, A.4.1 / A.4.3 / A.4.4 L1284-1362 | Datasets and wet-lab method: 33 TCGA cancer types (10 rare; CNTL and MISC excluded), 2,300 drugs from the Open Targets Platform, DepMap Q2 2024 at default dependency probability, IC50 by MTS assay (CellTiter 96 AQueous One, Promega), 5,000 cells/well in 96-well plates, 48 h treatment, 1 h MTS at 37 °C, absorbance 490 nm, triplicate, Quest Graph IC50 Calculator, cell lines MOLM-13 / HL60 / KG-1 | `external` | PARITY `EVAL-WETLAB-001`; FINDINGS `L15`, listed under "Open, but not code" | `none` | — |
| R10-6 | same, A.6 L1956-1964 | AlphaFold is integrated as a **validation tool** that scores the structural plausibility of proposed sequences and returns feedback used to refine the hypothesis in later iterations; the sequence was first verified against UniProt via web search; ESM-2 and RoseTTAFold gave independent validation (pLDDT, GDT, log-likelihood ratio, pTM, ipTM named) | `reject` | FINDINGS `G13`, marked `=` — closed as a deliberate local choice, with `engine/src/co_scientist/config/tools.yaml` carrying the documented extension point. The paper's own "this example is for demonstration purposes only" supports the closure | `none` | — |
| R10-7 | same, A.5.4 L1924-1928; corroborated in the Nature SI | A review block terminates in a bare `Answer: N`, and a separately scored `Novelty review` terminates in its own `Answer: N` — at least two independently scored review types in one output | `unclear` | The text never states the scale for `Answer: N`. It is plausibly the 1–5 of R10-3, but the paper does not say so here | Review schema, only once the scale is settled | S |
| R10-8 | same, A.5.4 L1707-1954 | One complete detailed output runs: Summary, Hypothesis, Recent findings and related research, Areas worth exploring, Detailed novel likely correct idea, Molecular mechanism of action, Impacted pathways, Effect on proliferation, IC50 assay concentrations, Safety and toxicity, Testable hypothesis, Experimental plan, Conclusion, Review, Relevant article abstracts, Assumptions, Reasoning about assumptions, Improvements to the idea, Reasoning about correctness and testing, Novelty review, Already explored aspects, Novel aspects, Reasoning about novelty and recommendation, `Answer: N`, a numbered reference list, Critiques | `unclear` | The trailing `Critiques` block is explicitly "a summary of the negative critiques from the reviews" — a **per-idea** rollup distinct from the run-level meta-review critique. Our idea detail shows reviews, not a synthesized negative-critique summary | Idea detail / review projection | M |
| R10-9 | same, A.1 Glossary L705-711 | Three defined terms: "Novel repurposing candidate", "Novel target", "Novel mechanistic explanation" | `unclear` | A controlled vocabulary the repo does not carry. Whether it is load-bearing or descriptive needs a decision | `none`, or a vocabulary note | S |

### R10 continuation — the rubric's actual content, and the two-versions problem

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R10-10 | `extracted-artifacts/outputs/specific-aims/lapatinib-colon-cancer.md` and `selinexor-colon-cancer.md`, `#### Expert rating` blocks; rubric defined at `towards-an-ai-co-scientist.md` A.5.2 and Nature SI §4.3 | The 15 rubric axes exist **verbatim and applied**, not just described: 1 unmet clinical needs, 2 bridges therapeutic gap, 3 scientifically rigorous rationale, 4 integrates prior studies, 5 avoids over-extrapolation, 6 clear hypotheses and methods, 7 clearly stated aims, 8 path to clinical application, 9 well-defined endpoints, 10 meaningful pre-clinical experiments, 11 translational component, 12 avoids inaccuracies, 13 evidence-based assumptions, 14 originality and terminology, 15 clear writing and organization. Two worked exemplars carry a filled-in five-point Likert rating for every axis — lapatinib 11 Strongly Agree / 3 Agree / 1 Neutral / 0 / 0; selinexor 7 / 8 / 0 / 0 / 0. Givosiran carries no rating block, and its own header says why | `work` | This is the **dataset half of R10-1**, which named the rubric but had no instance of it. `evaluations/expert_review.py:29-36` scores a different 6-axis instrument, so nothing in the tree can consume these. Two filled exemplars are enough to pin an export format and give a reference distribution; they are far too few to calibrate against | The same `evaluations/datasets/` artifact R10-1 proposes — these are its fixtures | S (given R10-1) |
| R10-11 | `specific-aims/selinexor-colon-cancer.md:5-7`; `tool-use/alphafold-oct4-protein-design.md:11-16`; `supplements/…-supplementary-information.md:111-115` vs `papers/towards-an-ai-co-scientist.md:334-336` | **The arXiv paper and the Nature SI are two different publications that disagree on facts.** Three confirmed instances: (a) the Selinexor expert study is 6 raters / 8 yrs mean experience in the arXiv, 9 raters / 6.7 yrs in the SI; (b) the OCT4 validation is "ESM-2 and RoseTTAFold" in the arXiv and "ESM-2, ESMFold, and RoseTTAFold" in the SI, which also reassigns the "similar pLDDT" result from ESM-2 to ESMFold; (c) the SI reports **two independent rater groups agreeing at Spearman's rho = 0.745, p < 0.001**, a statistic the arXiv does not carry at all | `work` (record only) | The reconciliation exists **only inside the corpus**, written into two extraction-note headers by whoever built the folder. Nothing in `docs/` records that "the paper" is two sources that disagree, and rows across PARITY and FINDINGS cite it as one. Deleting the folder deletes the only written account of the divergence | A short "sources and their divergences" note carrying these three, cited from wherever the ledger says "the paper" | S |
| R10-12 | Nature SI §4.3 / `supplementary-information.md:113` | The rubric's five-point scale is an **agreement** scale — Strongly Agree / Agree / Neutral / Disagree / Strongly Disagree — and each of the 15 axes carries several sub-questions. Raters are told to judge clinical relevance and translation potential, explicitly **not** translational capacity or clinical-trial design | `work` (constraint on R10-10) | Confirms the 15-axis instrument is not a quality score and does not share a scale with the 1–5 / 1–10 review score of R10-3 and R10-7 — a distinction that must survive into any implementation, or the two get merged | The same row as R10-10 must carry this caveat | S |


---

## R8 — the eight published prompts, re-checked

The eight published prompts are the one part of this corpus recorded as fully
extracted: `engine/src/co_scientist/prompts/templates/README.md` maps each to
the template derived from it. That mapping records **derivation**, not
line-by-line preservation — so this study diffed them.

**Method, and its limits.** For each published prompt, every sentence of ≥6
words was taken, placeholders dropped, and the fraction of its content words
appearing anywhere in the mapped template measured. Low coverage is a
*candidate*, not a proof — a sentence can be present in different words. Every
row called `work` below was confirmed by a direct grep for the concept itself,
not by the score.

| Published prompt → template | Sentences | Poorly covered |
|---|---|---|
| generation-01 → `generation_debate_and_literature` + `draft_with_tools` | 9 | 2 |
| generation-02 → `generation_after_debate` | 18 | **0** |
| reflection-03 → `reflection_observations` | 21 | 1 |
| ranking-04 → `ranking.md` | 10 | 3 |
| ranking-05 → `ranking.md` | 19 | 14 |
| evolution-06 → `evolution.md` | 8 | 5 |
| evolution-07 → `evolution.md` | 11 | 9 |
| meta-review-08 → `meta_review.md` | 9 | **0** |

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R8-1 | `prompts/ranking-04-pairwise-comparison.md:26`; also flagged as an invariant in `prompting-architecture-…md` §7 L358 | The published pairwise judge is told: "Disregard these scores in your comparative analysis, as they may not be directly comparable across reviews." | `work` | **Absent from `engine/src/co_scientist/prompts/templates/ranking.md`** — grep for "comparable across" and "disregard" returns zero hits — while that template *does* inject review content at line 50 (`{{review_context}}`) and lines 59/62 (`{{hypothesis_a_mature_reviews}}` / `{{hypothesis_b_mature_reviews}}`). FINDINGS `F7` independently states "the ranking prompt reads its score beside the agents'". We feed the judge exactly what the published prompt warns about, without the warning | One line in `ranking.md` | S |
| R8-2 | The mapping itself, `prompts/templates/README.md` | The eight published prompts are recorded as mapped to templates | `work` | R8-1 is proof that derivation was recorded while preservation was never checked. One substantive instruction was lost silently | A one-off semantic diff of all eight prompts against their templates, of which R8-1 is the first result | M |
| R8-3 | `evolution-06-feasibility-improvement.md`, `evolution-07-out-of-the-box-thinking.md` | Two published evolution prompts whose content is largely absent from `evolution.md` (5/8 and 9/11 poorly covered) | `done` | **Already disclosed.** `prompts/templates/README.md` states evolution.md is "Partly A.6/A.7 — the paper's feasibility-improvement and out-of-the-box prompts survive as operators in a clone-authored operator-driven template, not as standalone prompts" | `none` | — |
| R8-4 | `ranking-05-comparison-via-scientific-debate.md` | 14 of 19 sentences poorly covered, including "typically 3-5 turns, up to 10 turns" at zero coverage | `unclear` | Mostly explained: the turn envelope is enforced in **code** (`agents/ranking/ranking.py:234`, PARITY `RANK-DEBATE-DEPTH-001` `verified`), and a mechanic enforced by code need not be restated in the prompt. What is not settled either way is one instruction only a prompt can carry — "Pose clarifying questions to address any ambiguities" (0.0). **The panel-of-experts half is now settled: see R8-6** | A semantic read of `ranking.md` against A.5 | S |
| R8-5 | generation-01/02, reflection-03, meta-review-08 | Four published prompts | `done` | Their templates carry the source faithfully: 0/18, 0/9, 1/21 (the one miss is the file's own title line), and 2/9 (both flavour text) | `none` | — |
| R8-6 | `prompts/ranking-05-comparison-via-scientific-debate.md:14-18` | The published debate judge is framed as a plurality: "You are an expert in comparative analysis, **simulating a panel of domain experts** engaged in a structured discussion to evaluate two competing hypotheses", and "**The experts** possess no pre-existing biases toward either hypothesis and are solely focused on identifying the optimal choice, given that only one can be implemented" | `work` | **New primary evidence against a `=` row.** FINDINGS `E18` is closed as a deliberate local choice on the stated reasoning that "the paper's tournament prompts name a single evaluator". This prompt does not — it names a simulated panel and refers to the experts in the plural. Our `prompts/templates/ranking.md` carries neither: grep for `panel`, `domain expert`, `pre-existing` and `bias` returns zero hits. **The distinction E18 draws still holds in part** — the published prompt simulates an unnamed panel, and our clone-invented Innovator / Pragmatist / Contrarian personas remain unattributed. What is contradicted is the narrower claim that the source names a single evaluator | A correction to FINDINGS `E18`, and one framing line in `ranking.md` | S |

R8-1 is the study's single most consequential find, because it comes from the
region everyone had already marked finished.

---

## R11 — `research/supplements/`

`R11-1` … `R11-8` were verified directly; the swept remainder continues below.

The protein-assemblies folder is the corpus's only **complete published run** —
one prompt, 19 hypotheses, 3 reports, 9,010 lines. It is a reality check on what
a real run's output looks like.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R11-1 | `ai-guided-discovery-…/hypotheses/` (19 files) | All 19 hypotheses from one real run carry effectively **one title, restated 19 times** — every one contains "Structural Novelty Index"/"SNI" and "NRC-NLR(s)", almost always "AlphaFold 3", varying only in parameter count (6–10) and a cosmetic qualifier | `work` (record only) | This repo has twice treated near-identical idea titles as a **defect** — the recorded "why is every idea about empagliflozin" symptom behind FINDINGS `K2`, and the near-duplicate-guard gotcha in `AGENTS.md`. Google's own published run shows the same near-zero title diversity on a narrow goal | A note on `evaluations/metrics.py::hypothesis_diversity` and/or FINDINGS | S |
| R11-2 | same, exhaustive grep of all 23 files | No Elo rating, rank, or any system metadata appears anywhere; no lineage marker (parent id, generation, "evolved from") appears anywhere | `done` | Strong primary corroboration of FINDINGS `D1` (Elo leaderboard is a local divergence, `=`) and `D20` (lineage is text-only). Cite it there | `none` — cite as evidence | S |
| R11-3 | same, appendix blocks | Review labels are Correctness / Novelty / Feasibility / Impact potential / Motivation / Coherence / Deep verification; the `Reviews summary` is a numbered `1. Executive Verdict … 8. Conclusion`; dispositions appear as bolded `Verdict: No-Go` and `Verdict: Proceed with Testing`, with explicit nulls "No critical flaws found." / "No incoherence found." | `unclear` | Ours: axes relevance / plausibility / novelty / testability / safety / scientific_soundness / clarity / potential_impact (`schemas/review.py`), dispositions sound / needs_revision / rejected. Overlapping, not identical — and this is one run | Review schema vocabulary, if wanted | S |
| R11-4 | `reports/research-overview.md` | Its own "Top ranking hypotheses" list references **20** distinct hypothesis IDs; 19 match files on disk by title and one (`103040864270759`) has no file anywhere | `unclear` | The published run is incomplete on disk. Anyone citing it as a pool-size ground truth must say 19-of-20 | A note wherever the run is cited | S |
| R11-5 | `reports/top-ranking-hypotheses-existing-export.md` vs its twin | The two differ in five reproducible ways: an empty References heading becomes a broken empty table, inline LaTeX is stripped and reordered, "AI" corrupts to "Al", subscripted names garble (`pore`→`nore`, `pred`→`med`), and every heading sits one Markdown level deeper | `reject` | It is a lossy OCR/re-typeset conversion, not a second serialization format. It is **not** evidence of an "existing export" feature and must never be mined as a schema source | `none` — one explicit warning line | S |
| R11-6 | `supplements/ai-guided-discovery-…/` vs `extracted-artifacts/outputs/…/protein-assemblies/` | Every file is byte-identical between the two locations (verified by `diff -rq`; the only difference is an added `SOURCE-NOTE.md` in each of the two copies) | `done` | **22 files and 8,973 lines** are duplicated *within* the corpus — 19 hypotheses (7,689 lines) and 3 reports (1,284 lines). The corpus is smaller than its file count suggests | Deletion-planning note | S |
| R11-7 | `ai-assisted-drug-re-purposing-…-file-1.md` | The file's own title is "**Med-Gemini Output** for Role of Epigenetic Changes in Liver Fibrosis" | `reject` | It is a **comparator system's** output used as a baseline, not the AI co-scientist's. Nothing in it is evidence of Co-Scientist behaviour | `none` — one explicit warning line | S |
| R11-8 | Nature SI Note 3 / Supplementary Table 1 | A fully quantified per-agent ablation: Reflection search-tool ablation (novelty 6.14→2.38, correctness 7.4→8.46, GPQA AUC 0.643→0.651), Evolution (GPQA precision 70.9%→75.4%, quality 4.7→5.6), Meta-review (AUC 0.521→0.597 constructed, 0.629→0.634 GPQA), plus Ranking-prompt and Proximity findings | `work` | PARITY `EVAL-ABLATION-001` is `partial`, and its residual says meta-review and debate-strategy have no toggle seam — **exactly the arms Google published numbers for**. Only the 6.14→2.38 datum is already known (FINDINGS `E8`) | `evaluations/ablation_driver.py` + the `EVAL-ABLATION-001` residual | M |

---

## R1 and R4 — the two agent/system consolidations

**931 candidate rows** were swept out of the corpus in total. For the nine
consolidation files an attribution judgement was recorded per row: does the file
cite the paper, the preprint, a product capture, or Google Help for this claim,
or does it merely assert it? Measured across those files: **110 paper-backed,
204 unattributed, 52 known-invented**.

R1 (`source-system-reference.md`) accounts for most of the paper-backed rows and
is the one consolidation that is not substantially invented. It even disowns the
twelve-agent roster at line 54, noting the paper specifies seven and that "the
clone documents expand this to twelve", pointing at file 04.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R1-1 | SSR §1 L23-27 | The five default output criteria: alignment, plausibility, novelty, testability, safety | `done` | PARITY `OUTPUT-CRITERIA-001` (`verified`) — all five are required scored axes in `schemas/review.py` | `none` | — |
| R1-2 | SSR §2 L35-38 | Four system components: natural-language interface, asynchronous task framework, specialized agents, context memory | `done` | PARITY `ORCH-WORKER-IFACE-001`, `CKPT-STATE-001` | `none` | — |
| R1-3 | SSR §3 L46-48 | Goal is parsed into a research plan configuration; the Supervisor creates a task queue, periodically computes summary statistics informing resource allocation and termination, and writes state to context memory | `done` | PARITY `SUP-DYNAMIC-001`, `SUP-STATS-001`, `SUP-TERMINATE-001` (all `verified`) | `none` | — |
| R1-4 | SSR §4 L62-65 | Generation's four techniques: literature exploration, simulated debate, iterative assumptions, research expansion | `done` | PARITY `GEN-TECHNIQUES-001` (`verified`) — all four fire in a run | `none` | — |
| R1-5 | SSR §4 L72-77 | Reflection's six review types: initial, full, deep verification, observation, simulation, recurrent | `done` | PARITY `REFLECT-TYPES-001` (`verified`) | `none` | — |
| R1-6 | SSR §4 L84-87 | Elo starts at 1200; multi-turn debate for top-ranked, single-turn for lower; pairing favours proximity-similar and newer/top-ranked | `done` | PARITY `ELO-INIT-1200`, `RANK-DEBATE-DEPTH-001`, `RANK-PAIRING-001` (all `verified`) | `none` | — |
| R1-7 | SSR §4 L96-101 | Evolution's six strategies, including "inspiration from existing hypotheses" | `done` | `agents/evolution/evolution_operators.py:26-32` has all six; FINDINGS `E5` is `✓` | `none` | — |
| R1-8 | SSR §4 L108-110 | Meta-review critique is appended to every other agent's next prompt; research overview periodically synthesizes top-ranked hypotheses, formattable as an NIH Specific Aims page; research contacts suggest domain experts | `done` | PARITY `META-CRITIQUE-APPEND-001`, `OVERVIEW-NIH-001` (both `verified`) | `none` | — |
| R1-9 | SSR §4 Proximity L90-91 | Proximity computes a graph over hypotheses accounting for the goal, enabling clustering, de-duplication, and match organisation; it generates no hypotheses | `done` | PARITY `PROX-GRAPH-001`, `PROX-GRAPH-APP-001`, `PROX-INCREMENTAL-001` | `none` | — |
| R1-10 | SSR §5 L122-125 | Four expert-in-the-loop interactions: refine the goal, provide manual reviews, contribute own hypotheses into the tournament, direct follow-up on specific directions | `done` (partly open, already recorded) | PARITY `HITL-STEERING-001`, `HITL-MANUAL-HYP-001`, `HITL-MANUAL-REVIEW-001` are `partial` with residuals naming exactly what is missing (a contributed hypothesis does not join a live tournament) | `none` — already owned by P1.10 | — |
| R1-11 | SSR §6 L131-134 | Web search is primary; domain-specific databases constrain bounded searches; a private repository of scientist publications can be indexed; specialized models like AlphaFold can feed back | `done` | PARITY `TOOLS-CONFIG-001`, `HITL-CORPUS-001` (`verified`); AlphaFold is FINDINGS `G13` (`=`) | `none` | — |
| R1-12 | SSR §7 L141 | Elo-quality concordance buckets responses by Elo in **50-point increments** and computes accuracy per bucket | `work` | `evaluations/elo_concordance_eval.py` has no bucketing at all — zero grep hits for "bucket", "increment", "50". It scores Kendall's tau-b rank concordance, a different method. PARITY `EVAL-ELO-CALIB-001`'s residual names the licensed-corpus problem, not the method difference | `elo_concordance_eval.py` + the `EVAL-ELO-CALIB-001` residual | M |
| R1-13 | SSR §7 L144 | Test-time-compute scaling partitions a run's hypotheses into **ten equal temporal buckets** and shows best Elo and top-10 average Elo trending upward across them | `work` | `evaluations/scaling_eval.py` keys `scaling_curve()` on **budget/tier across runs**, with no temporal bucketing inside a run. `EVAL-SCALING-001`'s own residual concedes our offline curve "measures the harness rather than the model — the deterministic backend answers identically at every tier". The paper's method does not vary tier at all: it measures improvement over time *within one run* | `scaling_eval.py` + the `EVAL-SCALING-001` residual | M |
| R1-14 | SSR §7 L147, L150 | Expert evaluation over 11 of 15 goals by seven experts (preference rank 2.36, novelty 3.64, impact 3.09); safety evaluation over 1,200 adversarial goals across 40 topics, dataset withheld | `external` | PARITY `EVAL-EXPERT-RESULTS-001`, `SAFE-GOOGLE-SET-001`, both `external` | `none` | — |
| R1-15 | SSR §8 L156-165 | Three end-to-end wet-lab validations (AML repurposing, liver fibrosis, cf-PICI) | `external` | PARITY `EVAL-WETLAB-001`; FINDINGS `L15`, listed under "Open, but not code" | `none` | — |
| R1-16 | SSR §9 L172-176 | Six stated limitations: open-access-only literature, no negative results, multimodal/tool-use gaps, inherited LLM limitations, preliminary metrics, validation scope | `reject` | Bounding statements about what the reference system does *not* do. They constrain what fidelity can mean; none names a behaviour we claim and lack | `none` | — |
| R1-17 | SSR §4 Meta-review L108 | "The Generation agent uses the meta-review critique **selectively**, to avoid overfitting to critiques" — recorded by the sweep as paper-backed | `work` (a correction) | **The paper does not say this.** Grepping both papers and the Nature SI for "selectively"/"overfit" returns only unrelated pharmacology text; the nearest real sentence (`towards-an-ai-co-scientist.md:201`) is about the *Reflection* agent and about oversight, not selective use by Generation. The R8 sweep independently marked the same claim `unattributed` | A correction note; and a per-row paper check before any R1 row is promoted into PARITY | S |
| R1-18 | SSR §11 L188-190 | Three glossary terms: "novel repurposing candidate", "novel target", "novel mechanistic explanation" | `unclear` | A controlled vocabulary the repo does not carry. Whether it is load-bearing or merely descriptive needs a decision | `none`, or a vocabulary note | S |
| R4-1 | `agent-coalition-specifications.md` §1-§2 | A twelve-agent roster with personas, per-agent I/O JSON schemas, model-class assignments ("Gemini 3.5 Pro/Opus-class"), and named third-party integrations | `reject` | FINDINGS corpus-integrity corrections: "12 agents → the paper specifies **7** (Supervisor + 6)". R1 itself disowns it at line 54 | `none` | — |
| R4-2 | same §3 | A fixed NIH output schema: disease-description / unmet-need / proposed-solutions / specific-aims, each aim split into six named sub-fields | `reject` | Invented — R1 only ever calls NIH Specific Aims one illustrative example format. Our schema is pinned against the published exemplars instead, by `engine/tests/test_published_artifact_shapes.py` | `none` | — |
| R4-3 | same §6 | A fidelity checklist mixing paper-backed invariants with its own pass/fail machinery — notably a "≥80% tier-2 citation" threshold and a content-screening assertion phrased as an absolute guarantee | `reject` | Both unsourced. The absolute-guarantee framing also conflicts with this project's documented escalate-only screening design (FINDINGS `J4`, `J14`: a model may raise a verdict, never lower one). Do not convert either into a task | `none` | — |

**Caveat on this region.** R1-17 shows that R1's own paper-backed self-labelling
is not reliable. The 110/204/52 counts are the files' framing, not an audited
count. Any R1 row promoted into PARITY must be checked against the paper text.

---

## R2, R3, R5, R6, R7, R8, R9 — the remaining consolidations

**The decisive measurement.** Across roughly 1,650 lines of these files there is
essentially no external citation: R2 **0** paper-backed of 47 rows; R3 **1** of
49; R5 **2** of 73; R6 **0** of 71; R7 **2** rows in 162 lines. The few
"paper-backed" rows are self-labels in the prose (`*** PAPER INVARIANT ***`,
"the paper's six") carrying no arXiv, Nature, or Help pointer at all. Every
numeric threshold, rate limit, and constant in these files is a bare assertion by
the clone's own authors.

The correct verdict for the bulk of this material is therefore `reject`, per the
audit's own rule that scoring against clone-invented content makes the system
*less* faithful.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R2-1 | `product-surface-and-ux.md` (47 rows, 0 paper-backed) | An Elo-leaderboard Ideas tab; a Standard-vs-Advanced "Configure Run" form; Material-3 blue `#0b57d0` with Spline/DM Sans; NotebookLM/PDF/Word/LaTeX/BibTeX export | `reject` | FINDINGS corpus-integrity corrections lists all four as clone-invented; `D1`, `D2`, `D3` are `=`. **Exception:** the NotebookLM half is contested — `D16` is `?`, because current Google Help does list it | `none`, except D16 which stays open on its own terms | — |
| R3-1 | `system-architecture-and-orchestration.md` (49 rows, 1 paper-backed) | A Postgres schema, AG-UI/CopilotKit with ~17 SSE event types, a ResearchLoop control plane, and a proposed stack (Temporal, Celery/Redis, pgvector, named NLI models) | `reject` | FINDINGS corpus-integrity corrections; and `docs/PARITY.md`'s closing section states outright that the corpus's proposed stack is **not** a parity requirement | `none` | — |
| R3-2 | same, L192 | The single self-labelled paper invariant in the file: `elo_rating INT NOT NULL DEFAULT 1200, -- *** PAPER INVARIANT ***` | `done` | PARITY `ELO-INIT-1200` (`verified`), and pinned against the published pseudocode by `engine/tests/test_published_pseudocode_invariants.py` | `none` | — |
| R5-1 | `tournament-evolution-…md` (73 rows, 2 paper-backed) | A K-factor schedule, a margin-of-victory formula `effectiveK = 32·min(5, 1+25·rawMargin)`, and a 60/30/10 pairing-weight split — the file self-discloses the first as "paper-unspecified → clone-defined" and the third as "a clone choice" | `reject` | Elo K is a named evidence boundary ("paper-unspecified — preserve the 1200 core; label and configure everything above it"); FINDINGS `H6`; PARITY `RANK-K-FACTOR-001` already records 24 as a labelled reconstruction | `none` | — |
| R5-2 | same | The 3-persona debate (Innovator / Pragmatist / Contrarian) | `reject` | FINDINGS corpus-integrity corrections: "the paper specifies debate **turn counts**, never personas". Already closed as `E18` (`=`) | `none` | — |
| R6-1 | `retrieval-grounding-…md` §1–§2 | Fourteen named retrieval sources with rate limits and quotas | see below | Checked one by one against `engine/src/co_scientist/config/tools.yaml` | — | — |
| R6-2 | same §4, §7 | GRADE evidence grading and graph-based novelty math (Pop/N(H) with SLPA communities) | `reject` | FINDINGS corpus-integrity corrections: "clone evaluation design, not Google behavior" | `none` | — |
| R6-3 | same §5 L131 | "Tiered citation grounding", which the file itself labels "(the clone's storage contract)" | `reject` | Self-disclosed as local design | `none` | — |
| R7-1 | `context-engineering-and-memory.md` (162 lines) | The KSDS blackboard, Ideation/Experimentation memory, E-mem reconstruction, `AUTOCOMPACT_BUFFER_TOKENS=13000`, a context-budget percentage split, and a 15-table SQLite schema | `reject` | FINDINGS corpus-integrity corrections: "KSDS blackboard / cross-run 'Ideation Memory' → the paper's context memory is **per-run**"; cross-run memory is a standing evidence boundary — "do not add or claim it without new evidence" | `none` | — |
| R9-1 | `build-methodology-…md` | BRIDGE, M2M, and the 9-category fidelity harness | `reject` | FINDINGS corpus-integrity corrections names all three as clone evaluation design | `none` | — |
| R9-2 | same §7 | Open-source verdicts: Jataware open-coscientist FORK PRIMARY; LLNL, Sakana v2, FutureHouse Robin, OpenScientist/K-Dense, aimclub CoScientist all MINE; The-Swarm-Corporation INSPECT; mims-harvard AutoScientists REJECT | `work` | These are live *decisions*, not requirements, and they are the kind of thing the `references/peripheral/` precedent drained into ADRs. None is recorded anywhere outside this file | An ADR, so the decision survives deletion | S |
| R9-3 | `tech-stack-findings.md` | A cited primary-source report on Google's undisclosed stack, whose own uncertainty register states Google never names source languages, frontend framework, backend framework, storage engines, queue product, or retrieval index | `work` | Categorically different from the rest of R9 — it is a *citation-disciplined* document that corroborates the repo's own evidence-boundary register rather than asserting requirements. It is worth preserving as evidence | Fold its uncertainty register into the FINDINGS "Evidence boundaries" table | S |
| R9-4 | `tech-stack-findings.md`, confirmed-facts rows | Google's own sources confirm **ChEMBL and UniProt** as named database integrations, but do **not** confirm PubMed or arXiv as first-class integrations | `unclear` | In tension with this repo, where PubMed is the primary, most heavily used retrieval path (`search_pubmed`, `pubmed_search_with_fulltext`, and the whole `literature_review` query-generation path). Whether that makes PubMed a documented *local* choice or an implicit parity claim is settled by no ledger row. Would be settled by: deciding whether PARITY `TOOLS-CONFIG-001` should record PubMed primacy as CLONE rather than PRODUCT | A source-class note on `TOOLS-CONFIG-001` | S |

### R6 §1–§2 retrieval sources, checked one by one

`engine/src/co_scientist/config/tools.yaml` registers: `search_pubmed`,
`pubmed_search_with_fulltext`, `search_openalex`, `search_chembl`,
`search_uniprot`, `search_europepmc`, `search_preprints`,
`search_clinical_trials`, `search_string_interactions`,
`search_reactome_pathways`, `search_open_targets`, `search_ensembl_gene`,
`search_gnomad_constraint`, `search_web`, `read_url`.

| Source named in R6 | In `tools.yaml`? | Status |
|---|---|---|
| PubMed / MEDLINE | yes | `done` |
| Europe PMC | yes | `done` |
| OpenAlex | yes | `done` |
| ChEMBL | yes | `done` |
| UniProt | yes | `done` |
| Reactome | yes | `done` |
| ClinicalTrials.gov | yes | `done` |
| Preprints (bioRxiv / medRxiv) | yes | `done` |
| AlphaFold DB | referenced | `reject` — FINDINGS `G13` (`=`), documented extension point only |
| Semantic Scholar | **no** | `reject` |
| Crossref | **no** | `reject` |
| RCSB PDB | **no** | `reject` |
| KEGG | **no** | `reject` |
| Gene Ontology / NCBI Gene | **no** | `reject` |

**The five absences are not missing work — they are a completed decision.**
FINDINGS `G4` is `✓` *precisely because* unrunnable sources were removed from
config: "the unrunnable sources are gone from config — arXiv, bioRxiv,
OpenTargets, ClinicalTrials, Semantic Scholar, Crossref, Scholar no longer
appear; `config/tools.yaml` declares only backed tools." Reading these five as
gaps would reverse a deliberate fix. (Note that bioRxiv, Open Targets and
ClinicalTrials have since been re-added with real backends, so `G4`'s evidence
line is now stale in that direction — a small ledger-accuracy item.)

The registry also carries STRING, Ensembl and gnomAD, which R6 does not name —
we exceed the corpus's list in places.

| ID | Source | What it states | Status | Decided by | Proposed sink | Effort |
|---|---|---|---|---|---|---|
| R6-4 | R6 §6 | Retraction Watch / Crossref integration for detecting retracted sources | `done` (already owned twice) | FINDINGS `G6` is `✓` — retracted candidates are excluded before both admission paths. The remaining half is recorded in two places already: PARITY `CITE-META-001` is `partial` ("no live resolver is wired: the default still reads a supplied boolean"), and FINDINGS `G16` is open ("`assess_resolvability`/`Resolver` in `claims_gate.py` are still unwired into citation classification"). The parts exist — `claims_gate.py:91,101,126` has the `RETRACTED` state and the injectable seam, and `app/app/citation_resolver.py` already performs live doi.org and NCBI lookups | `none` — owned by `G16` / `CITE-META-001` | — |
| R6-6 | R6 §1–§2 vs §6 | Crossref appears in this corpus in **two distinct roles**: as a literature *search* source (§1–§2) and as the *retraction* lookup (§6) | `work` (a distinction to record) | The two roles get opposite verdicts and must not be collapsed. Crossref-as-search is deliberately absent from `tools.yaml` per `G4`; Crossref-as-retraction-resolver is the one thing that would close `CITE-META-001`'s residual. A later reader rejecting the resolver on the strength of the search-tool rejection would be reversing a fix | One clarifying line on `G16` / `CITE-META-001` | S |
| R6-5 | `G4`'s evidence line vs `tools.yaml` | `G4` states bioRxiv, Open Targets and ClinicalTrials "no longer appear" in config; all three are now registered with backends | `work` | `engine/src/co_scientist/config/tools.yaml` — `search_preprints`, `search_open_targets`, `search_clinical_trials` | A one-line correction to the `G4` evidence row | S |

---

## Verification depth — what was checked how

This study swept **931 candidate rows** out of the corpus. Every line of every
**prose document** assigned to a region was read. That is not the same as
consuming the whole folder, and the "Coverage" section below states exactly what
was measured, glanced at, or never opened.

Verification was not uniform, and the rows say which kind they got:

- **Directly verified against the tree** (the orchestrator ran the greps and read
  the code): all of R13, all deletion-readiness rows, R12-1 … R12-16,
  R10-1 … R10-9, R8-1 … R8-5, R11-1 … R11-8, R1-1 … R1-18, R4-1 … R4-3,
  R6's fourteen retrieval sources, and R2/R3/R5/R7/R9's headline claims.
- **Verified by measurement** — the eight published prompts were diffed against
  their templates sentence by sentence; the consolidations' attribution was
  counted row by row during the sweep.
- **Verified row by row in a separate pass** — R2, R3, R5, R6, R7, R8 and R9 were
  additionally adjudicated one row at a time against the ledger and the code,
  covering 298 source items in 180 verdicts: **53 `done`, 123 `reject`,
  2 `unclear`, 2 `work`**. That pass independently reproduced the retrieval-source
  table above with the same eight-present / six-absent split, and independently
  reached the same conclusion about the `G4` trap. Its two `work` items are
  folded in as `R9-2` and `R6-6`; its two `unclear` items are `R9-4` and the
  "Run Specification(s)" naming question — the latter is **not** carried as a row
  here, because FINDINGS already resolves it in "Where the audits disagreed"
  (07-20 controls, having checked live Help on its audit date).

- **R10 was independently verified in full.** A separate pass adjudicated all 145
  candidate rows from the two papers and the corpus READMEs into 69 verdicts:
  **39 `done`, 17 `external`, 13 `reject`, 0 `work`, 0 `unclear`**. It found
  **no new work at all** — its one `work` candidate was a duplicate of `R10-1`
  (the A.5.2 rubric). It also settled the A.3 "probing questions" structure as
  `done` against `templates/deep_verification.md`, which implements the
  QUESTION / ANSWER / REASONING triple the appendix prints.

That is a meaningful result rather than an empty one: **R10 is the region the
brief called the highest-priority unmined territory, and it is in fact almost
entirely covered by the existing ledger.** The twelve `R10-*` rows above are the
complete set of findings from both papers — the last three came only after the
coverage audit below forced a re-read of files the first pass had skipped.

The passes agreed everywhere they overlapped. Where they differed on detail, the
direct grep won: the R2–R9 pass paraphrased the registered tool names
(`pubmed_search`, `europepmc_search`), and the table above uses the names
actually present in `tools.yaml` (`search_pubmed`, `search_europepmc`).

One approach was tried and discarded: scoring every candidate row by word
overlap against the ledger and the code. With a 4 MB code haystack the median
score was 0.88 and the metric could not separate anything — the same asymmetry
trap `AGENTS.md` already records for Jaccard citation scoring. It was abandoned
rather than reported.

### Coverage — was every line actually read

The honest answer is **not on the first pass, and yes on the last**.

A mechanical audit enumerated all **182 files** (`find -type f`, excluding
`.DS_Store`) and matched each against what had actually been opened. The first
sweep left **15 markdown files unread** (676 lines — including all seven
pseudocode listings and all three Specific Aims exemplars), **2 read only in
part** (~4,626 lines), and **82 non-markdown files never opened at all**. Those
gaps were closed in a second round, and the audit was then re-run.

**Final state: 182 of 182 files accounted for, 0 uncovered.** The audit was
asked to name any file falling outside every coverage category and returned
none.

Three things that only the closing round found, which is the argument for
having done it:

- `R8-6` — the published debate prompt's panel framing, which contradicts a
  FINDINGS row closed as deliberate.
- `R10-10` / `R10-12` — the 15 rubric axes as *applied instruments* with filled
  Likert ratings, where the first pass had only the rubric's description.
- `R10-11` — that the arXiv paper and the Nature SI disagree on published facts,
  and that the corpus holds the only written reconciliation.

Two bookkeeping errors the audit caught in this document's own working notes,
both now corrected above: the protein-assemblies duplicate set is **19**
hypothesis files, not 21 (22 files and 8,973 lines counting the 3 reports), and
the MASH Knowledge Base has **7** subject headings, not 8.

### What was NOT consumed, stated plainly

"Accounted for" means every file was assigned a coverage verdict. It does **not**
mean every line and every pixel was consumed, and three categories were not:

| Not consumed | Volume | Why, and what the risk is |
|---|---|---|
| **Video frames** | **13,202 frames** — `mash-fibrosis-prompt-setup.mp4` 3,602 and `mash-fibrosis-research-plan-and-run.mp4` 9,600, both 120 fps | Neither file was ever played. Only `ffprobe` metadata was taken. **This is the one gap that touches a live citation**: `docs/UI-FIDELITY.md` sources the four-tab mapping to the frame at ≈66 s, and nobody in this study looked at it. `R13-3` is defensible only because a *tracked JPG* shows the same tab bar — the frame itself remains unexamined, and any other claim resting on this footage is unverified |
| **Minified web assets** | **6.55 MB** across 12 files in `google-labs-page/…_files/` — `base.js` ×2 at 1.5 MB each, `site.*.css` 712 KB, `www-player.css` ×2 at 519 KB, `site-*.js` 500 KB, `gtm.js` 408 KB, `lottie-light.js` 210 KB, three YouTube embed HTMLs at ~172 KB each, `cookienotificationbar.min.js` 78 KB | Triaged by identification, not by reading. Each got a one-line verdict as third-party tooling. The saved page's own 151-line HTML *was* read, but via `textutil` text extraction — its markup was not. Low risk: these are Google's shipped bundles, not authored corpus content. Non-zero risk: an inlined config blob or a data attribute inside them was never looked for |
| **Bibliography lines** | **3,354 lines** — the MASH report's `References` block | Characterised with shell tools rather than transcribed: 3,259 bullets + 1 mis-nested + 93 blanks + 1 header reconciles the range exactly, with link format, host distribution and duplicate analysis computed. 3,259 bibliography entries carry no extractable content beyond their shape. This one is a deliberate and, I think, correct trade |

**Images are a weaker claim than "read".** 62 image files were viewed and
described — but by a subagent, rendered into a model's context, not inspected by
me. Small type in a 2,160 x 1,620 screenshot can be misread, and one file in this
very set (`R13-12`) turned out to show something other than its filename claims,
which is the kind of error that survives a careless look. Treat every image-sourced
row as "a model reported seeing this", and re-open the file before acting on one.

**The chain of trust.** Most of this rests on subagent reports. Four claims were
spot-checked against the tree directly and all four held (the protein-assemblies
file count, git tracking across `media/`, the ranking prompt's wording, the
ESM-2/ESMFold divergence), and the audit itself caught two errors in this
document's own bookkeeping. But the coverage audit could not verify that the
media and MASH readings had actually completed — it took those on trust, and so,
transitively, does this document.


---

# Appendix — the published artifacts, recorded verbatim

**Why this appendix exists.** The checklist above says *where* we diverge from
Google's published material. It does not carry that material, and a checklist
that cites a folder cannot survive the folder's deletion. This appendix is the
record: every published prompt and pseudocode listing, copied byte-for-byte, so
the mirror can be rebuilt from this document alone.

**How it was produced.** Mechanically — `cat` into a fenced block, never
retyped. A model re-transcribing 500 lines of prompts is precisely how drift
enters the artifact meant to prevent drift. Each block carries its source path,
line count, and a sha256 prefix so any future edit is detectable: re-run the
hash against the source (or against git history once the folder is gone) and a
mismatch means someone paraphrased.

**How to use it.** These are the mirror targets. Where our implementation
differs, the difference should be traceable to a stated need — see the `MP-*`,
`MC-*`, `MO-*` and `MA-*` rows above, each of which names the element, our
file:line, and whether the difference is justified.

### A. The eight published prompts

Google's agent prompts as printed in the paper's appendix. These are the mirror targets for `engine/src/co_scientist/prompts/templates/`. Placeholders in `{braces}` are the paper's own. 260 lines in total.

#### `evolution-06-feasibility-improvement.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/evolution-06-feasibility-improvement.md` — 14 lines, sha256 `4d50f28971a6`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.4 "Prompts for the Evolution agent" -> Figure A.6 (line 861; rendered inline as one paragraph in source).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.4 "Prompts for the Evolution agent".
AGENT: Evolution agent. PURPOSE: refine a hypothesis for practical implementability / technological feasibility.
VERBATIM extract from the canonical source (which presents the prompt as a single run-on paragraph). {curly_brace} placeholders are the paper's.
-->

# Evolution agent — hypothesis feasibility improvement

```
Prompt for hypothesis feasibility improvement You are an expert in scientific research and technological feasibility analysis. Your task is to refine the provided conceptual idea, enhancing its practical implementability by leveraging contemporary technological capabilities. Ensure the revised concept retains its novelty, logical coherence, and specific articulation. Goal: {goal} Guidelines: 1. Begin with an introductory overview of the relevant scientific domain. 2. Provide a concise synopsis of recent pertinent research findings and related investigations, highlighting successful methodologies and established precedents. 3. Articulate a reasoned argument for how current technological advancements can facilitate the realization of the proposed concept. 4. CORE CONTRIBUTION: Develop a detailed, innovative, and technologically viable alternative to achieve the objective, emphasizing simplicity and practicality. Evaluation Criteria: {preferences} Original Conceptualization: {hypothesis} Response:
```
````

#### `evolution-07-out-of-the-box-thinking.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/evolution-07-out-of-the-box-thinking.md` — 30 lines, sha256 `065c72929962`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.4 "Prompts for the Evolution agent" -> Figure A.7 (lines ~865-883).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.4 "Prompts for the Evolution agent".
AGENT: Evolution agent. PURPOSE: generate a divergent, "out-of-the-box" hypothesis by analogy from existing ideas.
VERBATIM extract. {curly_brace} placeholders are the paper's.
-->

# Evolution agent — hypothesis generation through out-of-the-box thinking

```
Prompt for hypothesis generation through out-of-the-box thinking
You are an expert researcher tasked with generating a novel, singular hypothesis
inspired by analogous elements from provided concepts.
Goal: {goal}
Instructions:
1. Provide a concise introduction to the relevant scientific domain.
2. Summarize recent findings and pertinent research, highlighting successful approaches.
3. Identify promising avenues for exploration that may yield innovative hypotheses.
4. CORE HYPOTHESIS: Develop a detailed, original, and specific single hypothesis
   for achieving the stated goal, leveraging analogous principles from the provided
   ideas. This should not be a mere aggregation of existing methods or entities. Think out-of-the-box.
Criteria for a robust hypothesis:
{preferences}
Inspiration may be drawn from the following concepts (utilize analogy and inspiration,
not direct replication):
{hypotheses}
Response:
```
````

#### `generation-01-hypothesis-after-literature-review.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/generation-01-hypothesis-after-literature-review.md` — 32 lines, sha256 `cf554f87e143`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.1 "Prompts for the Generation agent" -> Figure A.1 (lines ~715-737).
PARALLEL SOURCE (same prompt, Nature-published version): references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.1 "Prompts for the Generation agent" (lines ~1105-1127).
AGENT: Generation agent. PURPOSE: hypothesis generation after literature review and relevant article exploration.
This file is a VERBATIM extract of the prompt template. Placeholders in {curly_braces} are the paper's, not added by us.
-->

# Generation agent — hypothesis generation after literature review

```
Prompt for hypothesis generation after literature review
You are an expert tasked with formulating a novel and robust hypothesis to address
the following objective.
Describe the proposed hypothesis in detail, including specific entities, mechanisms,
and anticipated outcomes.
This description is intended for an audience of domain experts.
You have conducted a thorough review of relevant literature and developed a logical framework
for addressing the objective. The articles consulted, along with your analytical reasoning,
are provided below.
Goal: {goal}
Criteria for a strong hypothesis:
{preferences}
Existing hypothesis (if applicable):
{source_hypothesis}
{instructions}
Literature review and analytical rationale (chronologically ordered, beginning
with the most recent analysis):
{articles_with_reasoning}
Proposed hypothesis (detailed description for domain experts):
```
````

#### `generation-02-hypothesis-after-scientific-debate.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/generation-02-hypothesis-after-scientific-debate.md` — 50 lines, sha256 `bd14cdd7ef6f`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.1 "Prompts for the Generation agent" -> Figure A.2 (lines ~739-779).
PARALLEL SOURCE (same prompt, Nature-published version): references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.1 (lines ~1129-1174).
AGENT: Generation agent. PURPOSE: hypothesis generation after a simulated multi-expert scientific debate (self-play).
VERBATIM extract. {curly_brace} placeholders are the paper's.
-->

# Generation agent — hypothesis generation after scientific debate

```
Prompt for hypothesis generation after scientific debate
You are an expert participating in a collaborative discourse concerning the generation
of a {idea_attributes} hypothesis. You will engage in a simulated discussion with other experts.
The overarching objective of this discourse is to collaboratively develop a novel
and robust {idea_attributes} hypothesis.
Goal: {goal}
Criteria for a high-quality hypothesis:
{preferences}
Instructions:
{instructions}
Review Overview:
{reviews_overview}
Procedure:
Initial contribution (if initiating the discussion):
    Propose three distinct {idea_attributes} hypotheses.
Subsequent contributions (continuing the discussion):
    * Pose clarifying questions if ambiguities or uncertainties arise.
    * Critically evaluate the hypotheses proposed thus far, addressing the following aspects:
        - Adherence to {idea_attributes} criteria.
        - Utility and practicality.
        - Level of detail and specificity.
    * Identify any weaknesses or potential limitations.
    * Propose concrete improvements and refinements to address identified weaknesses.
    * Conclude your response with a refined iteration of the hypothesis.
General guidelines:
    * Exhibit boldness and creativity in your contributions.
    * Maintain a helpful and collaborative approach.
    * Prioritize the generation of a high-quality {idea_attributes} hypothesis.
Termination condition:
    When sufficient discussion has transpired (typically 3-5 conversational turns,
    with a maximum of 10 turns) and all relevant questions and points have been
    thoroughly addressed and clarified, conclude the process by writing "HYPOTHESIS"
    (in all capital letters) followed by a concise and self-contained exposition of the finalized idea.
#BEGIN TRANSCRIPT#
{transcript}
#END TRANSCRIPT#
Your Turn:
```
````

#### `meta-review-08-meta-review-generation.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/meta-review-08-meta-review-generation.md` — 32 lines, sha256 `f9aac3ccfd41`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.5 "Prompt for the Meta-review agent" -> Figure A.8 (lines ~889-909).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.5 "Prompt for the Meta-review agent".
AGENT: Meta-review agent. PURPOSE: synthesize a meta-analysis across all reviews/tournament debates; its output is appended to other agents' prompts (feedback without back-propagation).
VERBATIM extract. {curly_brace} placeholders are the paper's.
-->

# Meta-review agent — meta-review generation from existing reviews

```
Prompt for meta-review generation
You are an expert in scientific research and meta-analysis.
Synthesize a comprehensive meta-review of provided reviews
pertaining to the following research goal:
Goal: {goal}
Preferences:
{preferences}
Additional instructions:
{instructions}
Provided reviews for meta-analysis:
{reviews}
Instructions:
    * Generate a structured meta-analysis report of the provided reviews.
    * Focus on identifying recurring critique points and common issues raised by reviewers.
    * The generated meta-analysis should provide actionable insights for researchers
      developing future proposals.
    * Refrain from evaluating individual proposals or reviews;
      focus on producing a synthesized meta-analysis.
Response:
```
````

#### `ranking-04-pairwise-comparison.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/ranking-04-pairwise-comparison.md` — 36 lines, sha256 `1426373a1768`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.3 "Prompts for the Ranking agent" -> Figure A.4 (lines ~789-811).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.3 "Prompts for the Ranking agent".
AGENT: Ranking agent. PURPOSE: single-turn pairwise hypothesis comparison in the Elo tournament (used for lower-ranked pairs).
VERBATIM extract. {curly_brace} placeholders are the paper's.
NOTE [sic]: the prompt body says 'concluding with the phrase "better idea: <1 or 2>"' but the final line instructs ending with
'"better hypothesis: <1 or 2>"'. Both phrasings appear in the source; reproduced as-is.
-->

# Ranking agent — pairwise hypothesis comparison (tournament)

```
Prompt for hypothesis comparison during tournament
You are an expert evaluator tasked with comparing two hypotheses.
Evaluate the two provided hypotheses (hypothesis 1 and hypothesis 2) and determine which one
is superior based on the specified {idea_attributes}.
Provide a concise rationale for your selection, concluding with the phrase "better idea: <1 or 2>".
Goal: {goal}
Evaluation criteria:
{preferences}
Considerations:
{notes}
Each hypothesis includes an independent review. These reviews may contain numerical scores.
Disregard these scores in your comparative analysis, as they may not be directly comparable across reviews.
Hypothesis 1:
{hypothesis 1}
Hypothesis 2:
{hypothesis 2}
Review of hypothesis 1:
{review 1}
Review of hypothesis 2:
{review 2}
Reasoning and conclusion (end with "better hypothesis: <1 or 2>"):
```
````

#### `ranking-05-comparison-via-scientific-debate.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/ranking-05-comparison-via-scientific-debate.md` — 52 lines, sha256 `fcd94f1f5edf`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.3 "Prompts for the Ranking agent" -> Figure A.5 (lines ~815-855).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.3 "Prompts for the Ranking agent".
AGENT: Ranking agent. PURPOSE: multi-turn pairwise comparison via simulated scientific debate (used for top-ranked pairs).
VERBATIM extract. {curly_brace} placeholders are the paper's.
-->

# Ranking agent — comparison via simulated scientific debate (tournament)

```
Prompt for hypothesis comparison via simulated scientific debate during tournament
You are an expert in comparative analysis, simulating a panel of domain experts
engaged in a structured discussion to evaluate two competing hypotheses.
The objective is to rigorously determine which hypothesis is superior based on
a predefined set of attributes and criteria.
The experts possess no pre-existing biases toward either hypothesis and are solely
focused on identifying the optimal choice, given that only one can be implemented.
Goal: {goal}
Criteria for hypothesis superiority:
{preferences}
Hypothesis 1:
{hypothesis 1}
Hypothesis 2:
{hypothesis 2}
Initial review of hypothesis 1:
{review1}
Initial review of hypothesis 2:
{review 2}
Debate procedure:
The discussion will unfold in a series of turns, typically ranging from 3 to 5, with a maximum of 10.
Turn 1: begin with a concise summary of both hypotheses and their respective initial reviews.
Subsequent turns:
    * Pose clarifying questions to address any ambiguities or uncertainties.
    * Critically evaluate each hypothesis in relation to the stated Goal and Criteria.
    This evaluation should consider aspects such as:
        - Potential for correctness/validity.
        - Utility and practical applicability.
        - Sufficiency of detail and specificity.
        - Novelty and originality.
        - Desirability for implementation.
    * Identify and articulate any weaknesses, limitations, or potential flaws in either hypothesis.
Additional notes:
{notes}
Termination and judgment:
Once the discussion has reached a point of sufficient depth (typically 3-5 turns, up to 10 turns)
and all relevant questions and concerns have been thoroughly addressed, provide a conclusive judgment.
This judgment should succinctly state the rationale for the selection.
Then, indicate the superior hypothesis by writing the phrase "better idea: ",
followed by "1" (for hypothesis 1) or "2" (for hypothesis 2).
```
````

#### `reflection-03-generate-observations.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/prompts/reflection-03-generate-observations.md` — 14 lines, sha256 `18f770ee2620`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.2 "Prompt for the Reflection agent" -> Figure A.3 (line 783; rendered inline as one paragraph in source).
PARALLEL SOURCE (same prompt, re-rendered as a numbered list): references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.2 (lines ~1176-1215).
AGENT: Reflection agent. PURPOSE: the "observation review" -- find prior-experiment observations a hypothesis could newly explain.
VERBATIM extract from the canonical source (which presents the prompt as a single run-on paragraph). {curly_brace} placeholders are the paper's.
-->

# Reflection agent — generate observations explainable by the hypothesis

```
Prompt for generating observations which can be explained by the hypothesis You are an expert in scientific hypothesis evaluation. Your task is to analyze the relationship between a provided hypothesis and observations from a scientific article. Specifically, determine if the hypothesis provides a novel causal explanation for the observations, or if they contradict it. Instructions: 1. Observation extraction: list relevant observations from the article. 2. Causal analysis (individual): for each observation: a. State if its cause is already established. b. Assess if the hypothesis could be a causal factor (hypothesis => observation). c. Start with: "would we see this observation if the hypothesis was true:". d. Explain if it's a novel explanation. If not, or if a better explanation exists, state: "not a missing piece." 3. Causal analysis (summary): determine if the hypothesis offers a novel explanation for a subset of observations. Include reasoning. Start with: "would we see some of the observations if the hypothesis was true:". 4. Disproof analysis: determine if any observations contradict the hypothesis. Start with: "does some observations disprove the hypothesis:". 5. Conclusion: state: "hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>". Scoring: \* Already explained: hypothesis consistent, but causes are known. No novel explanation. \* Other explanations more likely: hypothesis \*could\* explain, but better explanations exist. \* Missing piece: hypothesis offers a novel, plausible explanation. \* Neutral: hypothesis neither explains nor is contradicted. \* Disproved: observations contradict the hypothesis. Important: if observations are expected regardless of the hypothesis, and don't disprove it, it's neutral. Article: {article} Hypothesis: {hypothesis} Response {provide reasoning. end with: "hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>".)
```
````

### B. The seven published pseudocode listings

The published algorithm for each agent. These are the mirror targets for `engine/src/co_scientist/agents/`. Note that ordering, guards and idempotency conditions carry as much weight as the named constants — the constants are already pinned by `engine/tests/test_published_pseudocode_invariants.py`, the control flow is pinned by nothing. 240 lines in total.

#### `01-supervisor.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/01-supervisor.md` — 71 lines, sha256 `2f7a6fe641b3`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Supervisor agent — pseudocode

```
// Supervisor agent
FUNCTION StartCoScientist(ScientistResearchGoal)
BEGIN
 Parse the ScientistResearchGoal into a structured ResearchPlan
 SAVE ResearchPlan TO SharedMemory
 CREATE new Task (Agent: Generation, Action: "CreateInitialHypotheses")
 ADD Task TO GlobalTaskQueue
 // Main Loop
 WHILE NumberOfIdeas < MaxIdeas AND NumberOfMatchesPerIdea < MaxMatchesPerIdea DO
 IF GlobalTaskQueue is NOT empty THEN
 FETCH next Task FROM GlobalTaskQueue
// Assign task to the correct agent
 LET AgentToRun = GET agent for Task
 LET Results = AgentToRun.Execute(Task)
 // Process the results and create follow-up tasks
 CALL FUNCTION ManageFollowUpTasks(Results)
 ELSE
 // If there's a pause, decide what to do next
 CALL FUNCTION DecideNextSteps()
 END IF
 END WHILE
END
FUNCTION ManageFollowUpTasks(ResultsOfCompletedTask)
BEGIN
 // This function shows how agents trigger each other via the Supervisor
 IF ResultsOfCompletedTask.Type IS "NewHypothesisCreated" THEN
 // A new hypothesis was made. It needs to be reviewed
 CREATE new Task (Agent: Reflection, Action: "ReviewHypothesis", TargetID:
ResultsOfCompletedTask.HypothesisID)
 ADD Task TO GlobalTaskQueue.
 END IF
 IF ResultsOfCompletedTask.Type IS "ReviewCompleted" THEN
 // The hypothesis is now ready for the tournament

 CREATE new Task (Agent: Ranking, Action: "AddToTournament", TargetID:
ResultsOfCompletedTask.HypothesisID)
 ADD Task TO GlobalTaskQueue
 END IF
END
FUNCTION DecideNextSteps()
BEGIN
 // What to do when no new tasks are being generated by the workflow
 // Keep the tournament running to refine scores
 CREATE new Task (Agent: Ranking, Action: "RunTournamentBatch")
 ADD Task TO GlobalTaskQueue
 // If scores are stable, try to improve top ideas
 IF hypothesis quality has stopped improving THEN
 CREATE new Task (Agent: Evolution, Action: "EvolveTopHypotheses")
 ADD Task TO GlobalTaskQueue
 END IF
 // Periodically, synthesize system-wide feedback
 IF enough time has passed THEN
 CREATE new Task (Agent: Metareview, Action: "GenerateSystemFeedback")
 ADD Task TO GlobalTaskQueue
 END IF
 // Periodically, synthesize final report
 IF enough time has passed THEN
 CREATE new Task (Agent: Metareview, Action: "GenerateFinalResearchOverview")
 LET FinalReport = MetaReviewAgent.GenerateFinalResearchOverview()
 RETURN FinalReport to the scientist
 END IF
END
```
````

#### `02-generation.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/02-generation.md` — 29 lines, sha256 `f9d19a9a6505`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Generation agent — pseudocode

```
// Generation agent
FUNCTION CreateInitialHypotheses()
BEGIN
 // Strategy 1: Use existing knowledge
 PERFORM a web search for literature related to the ResearchGoal

 CALL LanguageModel with prompt: "Based on this research, propose a novel
hypothesis for [ResearchGoal]." 
 // Strategy 2: Simulate debate
 CALL LanguageModel with prompt: "Simulate a scientific debate between experts to
create a new hypothesis for [ResearchGoal]."
 // More strategies...
 // Process new ideas
 FOR EACH NewHypothesis generated DO
 SAVE NewHypothesis to HypothesesList in SharedMemory
 CREATE new Task (Agent: Reflection, Action: "ReviewHypothesis", TargetID:
NewHypothesis.ID)
 ADD Task TO GlobalTaskQueue
 END FOR
END
```
````

#### `03-reflection.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/03-reflection.md` — 30 lines, sha256 `ad6a4c3b022c`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Reflection agent — pseudocode

```
// Reflection agent
FUNCTION ReviewHypothesis(HypothesisID)
BEGIN
 FETCH Hypothesis from SharedMemory using HypothesisID
 // Perform full review
 PERFORM web search for evidence related to the Hypothesis
 CALL LanguageModel with prompt: "Critically review this hypothesis for novelty
and correctness using the provided literature."
 CREATE FullReview and SAVE to ReviewsList
 // Perform deep verification
 CALL LanguageModel with prompt: "Break down this hypothesis into its core
assumptions."
 FOR EACH Assumption DO
 CHECK if the assumption is scientifically plausible
 END FOR
 CREATE VerificationReview and SAVE to ReviewsList
 // Create next step
 CREATE new Task (Agent: Ranking, Action: "AddToTournament", TargetID:
HypothesisID)
 ADD Task to GlobalTaskQueue
END
```
````

#### `04-ranking.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/04-ranking.md` — 36 lines, sha256 `e5c0327ddb0c`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Ranking agent — pseudocode

```
// Ranking agent
FUNCTION AddToTournament(HypothesisID)
BEGIN
 // Retrieve the specified hypothesis from our central data store
 LET HypothesisToAdd = FETCH Hypothesis FROM SharedMemory WHERE ID is
HypothesisID
 // Check if this hypothesis is already in the tournament. If so, do nothing
 IF HypothesisToAdd.EloRating IS NOT empty THEN
 PRINT "Warning: Hypothesis [HypothesisID] is already in the tournament."
 EXIT function
 END IF
 // Assign the standard starting Elo score
 SET HypothesisToAdd.EloRating TO 1200
 // Save the updated hypothesis back to the central data store
 UPDATE Hypothesis in SharedMemory
END
FUNCTION RunTournamentBatch()
BEGIN
 SELECT two hypotheses to compare (HypothesisA, HypothesisB)
 // Prioritize new hypotheses or those with similar Elo ratings
 CALL LanguageModel with prompt: "Simulate a debate between two scientists, one
defending HypothesisA and one defending HypothesisB. Conclude by declaring which
one is superior."
 DETERMINE the winner (e.g., HypothesisA) and loser (HypothesisB) from the debate
 CALCULATE new Elo ratings for both hypotheses based on the outcome
 UPDATE HypothesisA.EloRating and HypothesisB.EloRating in SharedMemory
END
```
````

#### `05-evolution.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/05-evolution.md` — 32 lines, sha256 `f737c9a057b7`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Evolution agent — pseudocode

```
// Evolution agent
FUNCTION EvolveTopHypotheses()
BEGIN
 FETCH the top 5 hypotheses from the HypothesesList
 // Strategy 1: Combine ideas
 CALL LanguageModel with prompt: "Combine the best parts of [Hypothesis1] and
[Hypothesis2] into a new, stronger hypothesis."
 // Strategy 2: Simplify for clarity

 CALL LanguageModel with prompt: "Refine [Hypothesis3] to make it simpler and
more testable."
 // Strategy 3: Think differently
 CALL LanguageModel with prompt: "Inspired by these ideas, propose an
'out-of-the-box' alternative."
 // More strategies...
 FOR EACH EvolvedHypothesis generated DO
 // Treat it like a brand new idea
 SAVE EvolvedHypothesis to HypothesesList
 CREATE new Task (Agent: Reflection, Action: "ReviewHypothesis", TargetID:
EvolvedHypothesis.ID)
 ADD Task to GlobalTaskQueue
 END FOR
END
```
````

#### `06-proximity.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/06-proximity.md` — 17 lines, sha256 `cea466f23a38`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Proximity agent — pseudocode

```
// Proximity agent
FUNCTION UpdateProximityGraph()
BEGIN
 FOR EACH pair of hypotheses in the HypothesesList DO
 CALCULATE a similarity score between them (e.g., using text embeddings)
 UPDATE the connection between them in the ProximityGraph
 END FOR
END
```
````

#### `07-meta-review.md`

Source: `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/07-meta-review.md` — 25 lines, sha256 `7e502a1ae3fa`.

````
<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Meta-review agent — pseudocode

```
// Meta-review agent
FUNCTION GenerateSystemFeedback()
BEGIN
 GATHER all reviews and tournament debate transcripts from SharedMemory
 CALL LanguageModel with prompt: "Analyze all these critiques. What are the most
common weaknesses (e.g., 'lacks a clear experimental plan') and strengths?
Summarize this as feedback for the whole system."
 UPDATE SystemWideFeedback in SharedMemory with this summary
END
FUNCTION GenerateFinalResearchOverview()
BEGIN
 FETCH the top 10 hypotheses from SharedMemory

 CALL LanguageModel with prompt: "Synthesize these top-ranked hypotheses into a single, coherent research overview for the scientist. Outline the main research directions and their justifications."

 RETURN the generated overview END
```
````

### C. The published real outputs

Eighteen real outputs from real runs, copied whole rather than reduced to a
skeleton — because the mirror target is the *shape*, and a skeleton loses the
field wording, the ordering, and the terminator lines that are exactly what
must be copied. The scientific content is goal-specific and is not a mirror
target; the structure around it is. The `MO-*` rows above index which parts we
reproduce. Excluded here: the 4,187-line MASH report (its structure is recorded
in `R12-6` … `R12-23`, and 3,259 of its lines are a bibliography) and the 22
protein-assemblies files (byte-identical duplicates of the `supplements/` copy,
per `R11-6`).

#### hypotheses/als-generation-output.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/hypotheses/als-generation-output.md` — 34 lines, sha256 `025d46737463`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example output of the Generation agent" / Figure A.10 (lines 929-955).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.2 (lines ~1365-1393).
AGENT: Generation. CASE STUDY: ALS illustrative example. ARTIFACT: a generated hypothesis + research proposal (abbreviated in source).
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract (abbreviated in the source with "...").
-->

# ALS illustrative example — Generation agent output (hypothesis + proposal)

Research goal Develop a novel hypothesis for the key factor or process which contributes to ALS progression ... We can use iPSC cells for the in-vitro experiments. ...

#### Introduction

Amyotrophic Lateral Sclerosis (ALS) is a fatal neurodegenerative disease characterized by the selective loss of motor neurons, leading to progressive muscle weakness, paralysis, and ultimately death. While the exact cause of ALS remains unknown, a complex interplay of genetic predisposition, environmental factors, and age-related cellular changes is believed to contribute to its pathogenesis. ...

#### Recent findings and related research

Recent research has implicated several key players and processes in ALS. TDP-43, an RNA-binding protein, is found mislocalized and aggregated in the cytoplasm of affected neurons in the majority of ALS cases. This protein's ability to undergo liquid-liquid phase separation (LLPS) has come under intense scrutiny, with evidence suggesting that dysregulation of this process leads to the formation of pathological aggregates. Further, impairments in nucleocytoplasmic transport, the process by which molecules move between the nucleus and cytoplasm, have been observed in ALS and linked to TDP-43 pathology. Endoplasmic reticulum (ER) stress, a cellular response to protein misfolding, has also been implicated as a potential contributing factor.

#### Hypothesis

Cellular stress (including but not limited to ER stress) induces post-translational modifications (PTMs) on specific FG-Nups (focusing initially on Nup98 and Nup62) at the nuclear pore complex (NPC). These Nup PTMs modify the interaction between these Nups and TDP-43, leading to altered TDP-43 dynamics and increased retention at the NPC. This increased retention at the NPC, in turn, triggers the disruption of nucleocytoplasmic transport.

#### Rationale and specificity

Instead of making the hypothesis about LLPS, we are making it much more specific but with the same starting point. Cellular stress, a broad concept encompassing various cellular insults, can trigger a cascade of molecular events. A key consequence of stress response is altered protein structure and function, which can be mediated by PTMs. Nuclear pore proteins, particularly FG-Nups like Nup98 and Nup62, form a "hydrogel" or selective barrier at the NPC, regulating the movement of molecules between the nucleus and cytoplasm. We hypothesize that specific PTMs on these FG-Nups (e.g., phosphorylation, O-GlcNAcylation initially) directly alter their interaction with TDP-43. TDP-43, known to interact with the NPC and be involved in nucleocytoplasmic transport, may get inappropriately trapped or retained at the NPC when interacting with PTM-modified Nups. This trapping alters TDP-43 dynamics (even if not disrupting LLPS directly initially), meaning it cannot perform its normal functions and disrupting nucleocytoplasmic transport, which we know is happening in ALS. Since even a small change in transport could lead to downstream problems, this is a plausible initial event with testable consequences. The specific FG-Nups (Nup98/62) and chosen PTMs (phosphorylation/O-GlcNAcylation) provide a concrete starting point for experimentation. This mechanism directly links cellular stress to TDP-43 dysfunction and the key ALS pathology of defective nucleocytoplasmic transport by invoking a novel interaction mechanism at the NPC – all testable in vitro.

#### Experimental design and validation

Cell Types: Human iPSC-derived motor neurons from healthy controls and ALS patients. Stress Induction: Induce cellular stress using established pharmacological agents (e.g., tunicamycin for ER stress, arsenite for oxidative stress, oligomycin A for mitochondrial stress) and physical stressors (heat shock). Test different stressors individually and in combination. This broadened approach allows for a more robust investigation of the stress response.

Nup PTM Analysis: Assess PTMs of Nup98 and Nup62 specifically using mass spectrometry and immunoblotting with PTM-specific antibodies (specifically looking for phosphorylation and O-GlcNAcylation). Focus the analysis on these two.
````

#### hypotheses/liver-fibrosis-epigenetic-targets.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/hypotheses/liver-fibrosis-epigenetic-targets.md` — 127 lines, sha256 `e546a6bf7869`.

````
<!--
SOURCE (verbatim): references/core/google-co-scientist/research/supplements/ai-assisted-drug-re-purposing-for-human-liver-fibrosis-supplementary-data-file-1.md (entire file, lines 1-114).
CASE STUDY: Novel target discovery for liver fibrosis (epigenetic targets).
ARTIFACT: two complete Generation-agent example hypotheses ("Example experiment 1" and "Example experiment 2"), each scored
  (score=novelty+details+usefulness+pairwise rank=11) and ending with the system's own novelty/similarity judgment.
NOTE: The source file labels these as "Med-Gemini Output". This is the early naming for the same Co-Scientist system; the
  liver-fibrosis study (Guan et al., Adv Sci 2025) is the validated target-discovery case study in which the system proposed
  epigenetic modifiers -- one effective drug, Vorinostat (an HDAC inhibitor, named below), is FDA-approved for another indication.
This file reproduces the source verbatim. The whole source file is a single Co-Scientist output, so it is copied in full.
-->

# Liver fibrosis — epigenetic-target generated hypotheses (Med-Gemini / Co-Scientist output)

Med-Gemini Output for Role of Epigenetic Changes in Liver Fibrosis

Example experiment 1 (score=novelty+details+usefulness+pairwise rank=11):

## Prompt: A Novel Hypothesis Regarding Myofibroblast Generation in Liver Fibrosis

We propose a novel hypothesis that specific epigenetic alterations contribute to myofibroblast (MyoF) formation in liver fibrosis. Unlike previous approaches that primarily focused on canonical TGFβ1 and PDGF pathways, we hypothesize that changes in the cell's epigenetic landscape play a critical role in regulating MyoF differentiation and subsequent ECM production.

Specifically, our hypothesis centers on the following key elements:

* Histone Modifications: We theorize that during fibrogenesis, alterations in histone modifications, particularly deacetylation, in the promoter regions of genes responsible for MyoF differentiation occur. For example, reduced acetylation of Histone 3 lysine 9 (H3K9ac) could promote the recruitment of repressive transcriptional machinery, silencing pro-MyoF factors. Alternatively, increased acetylation on certain histones might facilitate the binding of transcription factors that drive MyoF identity.
* DNA Methylation: Our hypothesis also posits that dynamic changes in DNA methylation patterns around genes involved in the MyoF pathway could be crucial. For instance, we predict that demethylation of CpG islands near regulatory elements of pro-MyoF genes might lead to enhanced transcription. Conversely, hypermethylation of the same regions might prevent the binding of critical activators, thereby inhibiting MyoF transition.

These two mechanisms, working in concert, could provide a complex regulatory system governing MyoF generation and subsequent ECM deposition impacting liver fibrosis.

## Groundbreaking Experiment to Test the Hypothesis

To test our hypothesis, we propose an innovative experiment utilizing the human micro-HO system:

Experiment Setup:

1. micro-HO Generation:
   * Human micro-HOs will be generated from iPSCs according to the established protocol. These micro-HOs faithfully recapitulate the architecture and cellular composition of the human liver, including hepatic stellate cells (HSCs).
2. Fibrosis Inducement:
   * micro-HOs will be exposed to a relevant fibrotic stimulus (e.g., TGFβ1 or PDGF) to induce the fibrotic response and MyoF generation.
   * A parallel group will be kept untreated as controls.
3. Epigenetic Profiling:
   * ChIP-Seq: At different time points during the fibrosis induction process, we will perform chromatin immunoprecipitation with sequencing (ChIP-Seq) to map the genome-wide landscape of relevant histone modifications such as H3K9ac, and relevant histone methylases/demethylases.
   * Methylation analysis: Using bisulfite sequencing or similar approaches, we will assess the DNA methylation status of critical MyoF-associated genes.
4. Candidate Identification:
   * The epigenomic analysis will guide the identification of regions with significant epigenetic changes during fibrosis development.
   * Bioinformatic analysis will be conducted to correlate the epigenetic alterations with candidate genes involved in MyoF differentiation.
5. Functional Validation:
   * The epigenetic modifications and associated candidate genes will be validated using targeted approaches. This includes:
   * CRISPR/Cas9 Epigenetic Editing: To directly confirm the role of specific epigenetic changes, we will manipulate the epigenome using CRISPR/Cas9-based tools directly or by employing dCas9 systems fused to epigenetic writer/eraser domains.
   * Pharmacological Modulation: To assess the therapeutic potential, pharmacological targeting of identified epigenetic modifiers will be performed. Drugs like inhibitors of DNA methyltransferases (e.g., Azacitidine) and histone deacetylase (HDAC) inhibitors (e.g., Vorinostat) could be tested for their impact on MyoF generation and ECM production in the micro-HO model.

Expected Outcomes:

* Identification of key transcriptional regulators with specific epigenetic alterations driving MyoF formation and liver fibrosis.
* Validation of epigenetic markers as new diagnostic tools for liver fibrosis.
* Discovery of potential therapeutic targets through specific epigenetic modifiers.

Additional Techniques:

* Transcriptomic Analysis: Alongside epigenomic data, RNA sequencing will be performed throughout the experiment to track the dynamics of gene expression during the fibrotic process.
* Live Cell MyoF Imaging: The micro-HO platform, in combination with collagen-specific fluorescent probes and second harmonic generation (SHG) microscopy, will allow for real-time live cell monitoring of MyoF emergence and ECM generation, providing invaluable insights into the kinetics of fibrosis progression.

## Judgments and Discussion

Novelty and Impact:

This hypothesis and experiment hold significant novelty as they depart from a sole focus on signaling pathways and explore the role of epigenetic mechanisms in MyoF development. The human micro-HO model, alongside powerful techniques like ChIP-Seq and live cell imaging, provide unprecedented access to a detailed understanding of fibrogenesis in a human context. This research could have a profound impact on liver fibrosis research and therapeutic advancement.

Uniqueness of this Approach:

Investigating epigenetic modifications in MyoF generation during liver fibrosis hasn't been extensively explored previously. While some studies investigated epigenetic changes related to HSC activation, the comprehensive and dynamic analysis we propose using micro-HOs is a significant step forward. This approach holds high potential for a deeper understanding of a complex and crucial cellular phenomenon in liver fibrosis.

Example experiment #2 (score=novelty+details+usefulness+pairwise rank=11):

## Novel Hypothesis Regarding Myofibroblast Differentiation in Liver Fibrosis:

We hypothesize that specific epigenetic alterations, in addition to known growth factor signaling, are essential for driving the transdifferentiation of hepatic stellate cells (HSCs) into myofibroblasts – the primary collagen-producing cells responsible for fibrosis. Specifically, we propose that activation of HSCs during liver injury triggers changes in DNA methylation patterns and histone modifications at critical gene loci. These epigenetic modifications promote the expression of genes involved in:

* Collagen production and ECM remodeling: Genes like `COL1A1`, `COL3A1`, and matrix metalloproteinases (MMPs).
* Myofibroblast phenotype acquisition: Transcription factors like `SNAI1`, `TWIST1`, and smooth muscle actin (αSMA).
* Fibrotic signaling pathways: Genes encoding components of TGFβ, PDGF, and Hedgehog pathways.

Furthermore, based on our preliminary scRNA-seq data from ARPKD hepatic organoids, we posit that these epigenetic modifications might be driven, in part, by the STAT3 signaling pathway which is downstream of PDGFRβ activation.

## Experiment Targeting the Epigenetic Landscape :

Objective: To determine if epigenetic modifiers can block myofibroblast transdifferentiation and reduce collagen production in the microHO live-cell fibrosis model.

Experimental Setup:

1. MicroHO Preparation:
   * Hepatic organoids will be generated from human iPSCs and differentiated into microHOs using established protocols.
   * To mimic chronic liver injury, microHOs will be exposed to low, continuous doses of TGFβ1 and/or PDGF for a defined period (e.g., 7 days).
2. Epigenetic Modifier Treatment:
   * Based on prior research and known mechanisms, we will select various classes of epigenetic modifiers for testing, including:
   * DNA Methyltransferase Inhibitors (DNMTis): Examples include 5-Azacytidine and Decitabine, which deplete DNA methylation and reactivate silenced genes.
   * Histone Deacetylase Inhibitors (HDACis): Examples like Trichostatin A (TSA) and Vorinostat increase histone acetylation leading to a more open chromatin state and favoring gene expression.
   * Bromodomain Inhibitors: Such as JQ1, targeting epigenetic readers that recognize acetylated histones, thereby disrupting transcription.
3. Assessment of Myofibroblast Transdifferentiation:
   * Live-cell imaging: microHOs will be monitored daily for the emergence of collagen-producing cells utilizing our established live-cell imaging system.
   * Second Harmonic Generation (SHG) microscopy: Visualization of thick collagen fiber formation as a hallmark of fibrosis will be conducted.
   * Immunofluorescence staining: Quantification of myofibroblast markers like αSMA and Col1A1 expression in fixed microHOs.
   * scRNA-seq analysis: Global transcriptomic changes upon epigenetic modifier treatment will be evaluated to assess:
   * Alterations in the myofibroblast gene expression signature.
   * Expression changes in TGFβ, PDGF, and STAT3 pathway components
   * Identification of specific genes activated or repressed by epigenetic modifications.
4. Evaluation of Collagen Production and ECM deposition:
   * Quantitative analysis of collagen content: Utilizing biochemical assays like Sircol assay or hydroxyproline quantification.
   * Measurement of MMP activity: Assays will assess the ECM remodeling dynamics influenced by epigenetic modifications.

Expected Outcome and Impact:

This experiment has the potential to:

* Uncover novel epigenetic changes driving myofibroblast transdifferentiation and collagen production in liver fibrosis.
* Determine the efficacy of epigenetic modifiers in reducing or reversing hepatic fibrosis in the microHO model.
* Identify promising drug targets within the epigenetic landscape of fibrosis.
* Provide a valuable platform for drug discovery and validation for liver fibrosis treatments.

Novelty and Significance:

* Innovative Hypothesis: Linking specific epigenetic changes to myofibroblast transdifferentiation represents a novel departure from the prevailing focus solely on growth factor signaling.
* Advanced Experimental Platform: The utilization of human microHOs offers a physiologically relevant and species-specific model system to study fibrosis.
* Detailed Experimental Design: The multi-faceted approach employing live-cell imaging, molecular biology, and transcriptomics provides a comprehensive analysis of myofibroblast behavior and collagen deposition.

Similarity assessment:

While studies have explored epigenetic factors in broad cellular models of fibrosis, this experiment's strength lies in its specific focus on myofibroblast generation and collagen production within the context of the innovative microHO liver fibrosis model. This detailed approach encompassing multiple analytical techniques provides a more nuanced understanding of the epigenetic landscape. While other groups may explore aspects of epigenetics in fibrosis, the proposed combination of hypothesis, methodology, and model system likely distinguishes it from existing research.
````

#### meta-review-critiques/als-meta-review-critique.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/meta-review-critiques/als-meta-review-critique.md` — 83 lines, sha256 `38fb5fa819e4`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example output of a critique by the Meta-review agent" / Figures A.18-A.19 (lines 1126-1203).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.10 (lines ~1571-1644).
AGENT: Meta-review. CASE STUDY: ALS illustrative example. ARTIFACT: the synthesized meta-review critique across all ALS reviews/debates (this feedback is appended to other agents' prompts in subsequent iterations).
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract (Figures A.18 + A.19 concatenated; the "(continued)" boundary is marked).
-->

# ALS illustrative example — Meta-review agent critique

#### I. Core Hypothesis and Mechanism:

- Primary Driver vs. Consequence: A very common critique across many ideas was the difficulty in proving that the proposed mechanism is a primary initiating event in ALS rather than a downstream consequence of other processes. Future ideas need to:
  - Provide strong evidence for the temporal sequence of events using longitudinal experiments.
  - Employ models where early-stage events can be studied and manipulated.
  - Explicitly address whether the proposed mechanism is causative or correlative.
  - Specifically knockdown the primary driver to prove it's necessary and sufficient to cause the pathology.
- Specificity: Many hypotheses were criticized for a lack of specificity in various aspects:
  - Molecular Targets: Imprecise identification of specific proteins, RNA species, lipids, PTMs, etc. involved. Ideas should name specific candidates.
  - Cellular Compartments: Vague localization (e.g., "mitochondria" or "AIS"). Ideas should pinpoint specific subcellular locations whenever possible.
  - Disease Mechanisms: Broad terms like "oxidative stress" or "autophagy impairment." Ideas need to define the precise molecular events involved.
  - Types of Stress: If stress is involved, the specific type of stress needs to be defined (e.g., ER stress, nutrient deprivation, mitochondrial stress, ionic stress).
  - Temporality: The timing of the intervention is critical. Early vs. late events, duration of processes, etc., should be clearly specified.
- Motor Neuron Specificity: Given the focus on ALS, a strong explanation for why the proposed mechanism would specifically or preferentially affect motor neurons (and often specific subtypes of motor neurons) is crucial. Many ideas were critiqued for not adequately addressing this.
- Over-Simplification vs. Complexity: This is a balancing act. Some ideas were criticized for being too narrowly focused, potentially oversimplifying the complex, multifactorial nature of ALS. Others were criticized for being overly complex, making them difficult to test and validate experimentally. When in doubt, err on the side of testability in a reasonable timeframe and budget.
- ALS Subtype Relevance: Ideas should address whether the proposed mechanism is relevant to all ALS subtypes or specific to certain genetic or sporadic forms. Ideally, address how the proposed work will differentiate or be applicable to different subtypes.

#### II. Experimental Design and Feasibility:

- Model System Limitations: Reviewers frequently pointed out the limitations of in vitro models, particularly iPSC-derived motor neurons. While valuable, these models may not fully capture the in vivo environment, cell-cell interactions, or the aging process. Future ideas need to:
  - Acknowledge the limitations of the chosen model system.
  - Propose validation in multiple model systems if possible, including eventually animal, ex-vivo and, if applicable, in-vivo models.
  - Carefully consider and justify the choice of control cell types.
  - Propose isogenic controls where relevant.
- Technical Challenges: Many ideas proposed experiments that are technically very challenging. Reviewers often raised concerns about feasibility and the potential for ambiguous results. Future ideas should:
  - Demonstrate awareness of the technical hurdles.
  - Propose realistic solutions and alternative approaches.
  - Prioritize experiments that are most likely to yield clear, interpretable data.
- Specificity of Tools: When using inhibitors, antibodies, or other tools, their specificity needs to be carefully considered and validated to avoid off-target effects that can confound results. Appropriate controls and validation experiments must be included.
- Quantitative Rigor: Many critiques centered on the need for more rigorous quantification of experimental results. Future ideas need to:
  - Clearly define measurable outcomes.
  - Describe the specific assays and techniques that will be used for quantification.
  - Include appropriate statistical analysis plans.
  - Have a proposed plan for controls, replicates, and sample sizes.

<!-- Figure A.19 — "Example output of a critique by the Meta-review agent (continued)" -->

- Time-Course Experiments: Given the dynamic nature of cellular processes, incorporating time-course experiments is often crucial to understanding the sequence of events and demonstrating causality.
- Distinguishing Cause from Effect: This requires careful experimental design, including:
  - Longitudinal studies to observe the temporal order of events.
  - Intervention experiments to manipulate the proposed cause and observe the effects downstream.
  - Temporal resolution to demonstrate that the potential cause occurs before a downstream event.

#### III. Novelty and Impact:

- Incremental vs. Groundbreaking: Many ideas were criticized for being incrementally novel, building upon existing knowledge rather than proposing truly groundbreaking mechanisms.
- "Key Switch" Claims: Several ideas were criticized for prematurely claiming that the proposed mechanism is the "key switch" for ALS. This type of strong claim requires very strong supporting evidence. It is often better to frame the hypothesis in terms of a significant contributing factor and test its requirement for the pathology.
- Therapeutic Potential: While not always explicitly stated, the potential for translating the findings into therapeutic strategies is an important consideration. Ideas that offer a clear path toward therapeutic development may be viewed more favorably, provided a strong rationale is presented for the specific therapeutic approach.

#### IV. Assumptions and Validation:

- Strong Assumptions: Many hypotheses rely on strong assumptions that lack direct experimental support. Future ideas need to:
  - Clearly state all assumptions.
  - Provide a strong rationale for each assumption, citing relevant literature.
  - Propose experiments to directly test the most critical assumptions.

#### • Validation of Assumptions:

- Reviewers consistently emphasized the need for rigorous experimental validation of all assumptions.
- Assumptions should be addressed in the order of the proposed mechanism.
- If the initial steps are not validated, it may be unnecessary to proceed to later steps.

#### V. General Advice Based on Common Critiques:

- Mechanistic Detail: Provide as much specific mechanistic detail as possible. Don't just state that pathway X is affected; describe how it is affected at the molecular level.
- Literature Review: Demonstrate a thorough understanding of the existing literature, including contradictory findings. Address how the proposed idea fits into the current understanding of ALS and how it differs from previous work.
- Focus on Causality: Always design experiments that can distinguish between cause and effect.
- Feasibility: Prioritize experiments that are feasible with available resources and expertise. Consider using a phased experimental approach. Prioritize the experiments used to validate assumptions in the order they appear in the proposed mechanism.
- Strong Rationale: Provide a clear and compelling rationale for every aspect of the hypothesis and experimental design.
- Specificity of Controls: Explain why the choices of controls used in the experimental design are the best choice to test the effects of interest. Demonstrate that the effect is not due to a more general effect or mechanism.
- Address Limitations: Acknowledge the limitations of the proposed approach and discuss potential alternative explanations.
- Quantitative data: Emphasize quantitative data, consider including mathematical modeling of data where appropriate.
````

#### plan-configs/als-research-goal-and-plan-config.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/plan-configs/als-research-goal-and-plan-config.md` — 25 lines, sha256 `c3a5366741b5`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 "Examples ..." -> "From research goal to research plan configuration" / Figure A.9 (lines 917-927).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.1 (lines ~1351-1363).
CASE STUDY: ALS (Amyotrophic Lateral Sclerosis) -- the recurring ILLUSTRATIVE example used throughout both papers.

>>> CAVEAT (from the source papers): This ALS example "has been reviewed by domain experts, [but] it remains
    illustrative and may contain errors. Importantly, this example does not aim to suggest potential therapeutic
    avenues for ALS and should be interpreted with utmost caution." It is NOT a validated scientific result.

This file shows the user's natural-language research goal and how the system parsed it into a research plan configuration.
VERBATIM extract.
-->

# ALS illustrative example — research goal and parsed research plan configuration

## Scientist research goal

Develop a novel hypothesis for the key factor or process which causes ALS related to phosphorylation of a Nuclear Pore Complex (NPC) nucleoporin. Explain mechanism of action in detail. Include also a feasible experiment to test the hypothesis.

## Parsed research plan configuration

- Preferences: Focus on providing a novel hypothesis, with detailed explanation of the mechanism of action.
- Attributes: Novelty, Feasibility
- Constraints: should be correct, should be novel.
````

#### plan-configs/mash-liver-fibrosis-reversal-research-plan.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/plan-configs/mash-liver-fibrosis-reversal-research-plan.md` — 85 lines, sha256 `d6b17ff762ea`.

````
<!--
SOURCE: references/core/google-co-scientist/media/live-footage/mash-fibrosis-research-plan-and-run.mp4
  First half of the 80-second Gemini Enterprise live-footage capture.
  Visible screen: Google Co-Scientist "Research plan" for the chat
  "Epigenetic Reversal of MASH Fibrosis".

TRANSCRIPTION NOTE: Text is transcribed from the on-screen plan configuration;
line wrapping has been normalized for markdown readability.
-->

# MASH-associated liver fibrosis - research plan configuration

## Research plan

Here's my plan to tackle the topic:

## Epigenetic and stromal reversal strategies for MASH-associated liver fibrosis

## Goal

Generate a single, novel, and testable hypothesis for reversing established
liver fibrosis in MASH by targeting a specific molecular mechanism within
epigenetic, stellate cell, or stromal-immune pathways.

## Requirements

- The hypothesis must describe a novel mechanism for reversing established liver
  fibrosis, not a summary of known pathways or a literature review.
- The proposed intervention must be testable in human-relevant in vitro systems
  like hepatic organoids, precision-cut liver slices, or be strongly supported by
  human single-cell/spatial transcriptomics data.
- Approaches that rely solely on findings from murine models are discouraged.
- The proposed strategy must not involve permanent genome editing (e.g.,
  CRISPR-Cas9 knockout).
- The proposed strategy must not rely on broad, non-specific immunosuppression.
- If a compound is proposed, preference is given to those with existing human
  safety data and an acceptable hepatotoxicity profile.
- The idea must clearly fit into one of the core focus areas: 1)
  chromatin/epigenetic regulation, 2) hepatic stellate cell
  deactivation/clearance, or 3) stromal-immune crosstalk.

## Attributes

- **Mechanism Novelty:** Rate the novelty of the proposed biological mechanism
  on a 1-5 scale (1: Well-established pathway, 3: New application of a known
  mechanism, 5: Highly novel and paradigm-shifting).
- **Human Relevance:** Rate the reliance on human-relevant data and models on a
  1-5 scale (1: Based purely on murine or non-liver models, 5: Strong basis in
  human liver data and directly testable in human hepatic organoids/slices).
- **Clinical Translatability:** Rate the immediate potential for clinical
  translation on a 1-5 scale (1: Requires novel drug discovery from scratch, 3:
  Involves a pre-clinical compound, 5: Proposes repurposing an FDA-approved drug
  with a good safety profile).
- **Target Area:** Categorize the primary focus of the hypothesis (Epigenetics,
  Stellate Cell Biology, or Stromal-Immune Crosstalk).
- **Validation Plan Strength:** Rate the quality and feasibility of the proposed
  experimental validation plan on a 1-5 scale (1: Vague or unrealistic, 3:
  Plausible but lacks detail, 5: Clear, detailed, with well-defined quantitative
  go/no-go criteria).

## Criteria

- Idea correctness: Required
- Idea novelty: Required
- Maximize impact: Yes

## Focus

- Prefer evidence: Prioritizes well-established methods and data for
  high-confidence, incremental advances.
- Balance: A mix of established techniques and novel approaches for a
  comprehensive strategy. **Selected.**
- Prefer novelty: Favors unconventional ideas and exploratory methods for
  creative, higher-risk solutions.
- Breakthrough: Focuses on high-risk, high-reward strategies with the potential
  for paradigm shifts.

## Tier

- Express: Suitable for quick research questions and small-scale experiments.
- Standard: Suitable for medium-sized research questions and experiments.
  **Selected.**
- Extended: Suitable for large-scale research questions and experiments.
- Ultra: Most compute-intensive, using the largest models for cutting-edge
  insights. May take longer.
````

#### ranking-tournament/als-tournament-debate.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/ranking-tournament/als-tournament-debate.md` — 22 lines, sha256 `29679d639c25`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example of a scientific debate match in the Ranking agent tournament" / Figure A.17 (lines 1110-1124).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.9 (lines ~1551-1569).
AGENT: Ranking (tournament). CASE STUDY: ALS illustrative example. ARTIFACT: a multi-turn simulated scientific-debate match comparing two hypotheses (Idea 1 vs Idea 2), ending in an Elo-relevant verdict.
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract.
-->

# ALS illustrative example — Ranking agent tournament debate match

Expert 1: I'm intrigued by both ideas, but I have a few clarifying questions. For Idea 1, while the focus on TDP-43 retention at the NPC is novel, I'm not entirely convinced that it's fundamentally different from the extensively studied TDP-43 mislocalization. Could the retention just be a consequence of mislocalization, or are there experiments that can distinguish these two phenomena? Another question I have: Is there evidence already that specific PTMs modulate the interaction of Nups and TDP-43? Not necessarily in the context of ALS, but are there any precedents?

Expert 2: For Idea 2, I appreciate the bold approach, but the ISR as a trigger is a significant departure from the conventional view. Can the proponents of this idea elaborate on the evidence supporting this? Also, what specific lipid species are they proposing to be most critical at the ER-mitochondria interface and the AIS? Is there any preliminary reason why those lipids would be disrupted in ALS?

Expert 3: I agree with Expert B regarding the ISR. Shifting it from a response to a trigger is a big claim that needs strong justification. However, I think there are some initial clues that might be worth investigating. For example, there are reports that chronic low-level stress responses can actually be detrimental in some contexts. Perhaps a low, persistent activation of the ISR could predispose cells to damage. This idea needs to be fleshed out though.

Expert 3: I also find Idea 1 more compelling at this point. It's a more focused hypothesis with a clear path for experimental validation. While Idea 2 is undoubtedly more "outside the box," I'm concerned about the lack of evidence for the ISR as a trigger and the technical challenges. It feels like a high-risk, high-reward scenario, and given that we can only choose one, I'd prefer the more grounded approach of Idea 1. I do agree with the idea that the technical challenges are significant, but I like that the experiments proposed are standard and there are many commercial antibodies available to start testing this idea.

Expert 2: Alright, I'm on board with Idea 1. Let's focus our efforts on testing this specific mechanism and address the motor neuron specificity question rigorously in the experimental design. Perhaps by comparing different cell types and focusing on motor neuron-specific RNAs, as suggested earlier. We should also consider investigating different types of stress and their combined effects.

Better idea: 1
````

#### research-goals/cf-pici-research-goal.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/research-goals/cf-pici-research-goal.md` — 28 lines, sha256 `e37f63506de1`.

````
<!--
SOURCE (verbatim): references/core/google-co-scientist/research/supplements/ai-mirrors-experimental-science-to-uncover-a-mechanism-of-gene-transfer-crucial-to-bacterial-evolution-supplementary-information.md
  "Supplemental Data S1. Original input to the AI co-scientist, related to Table 1" (lines 11-27; the bundled 12-item reference list is at lines 29-43 in the source, not reproduced here).
CASE STUDY: Antimicrobial resistance / bacterial gene transfer (cf-PICIs).
ARTIFACT: the exact natural-language RESEARCH GOAL (the end-user input/prompt) given to the Co-Scientist. This is the input that
  the system answered when it independently recapitulated the (then-unpublished) experimental finding that cf-PICIs hijack diverse
  phage tails to expand host range -- in ~2 days, matching the researchers' real discovery.
NOTE: inline ReadCube citation hyperlinks present in the source have been omitted here for readability; the prose is verbatim.
VERBATIM extract of the prompt prose.
-->

# cf-PICI / AMR case study — research goal given to the Co-Scientist (input)

**Title**: Understanding inter-species cf-PICI transfer

**Goal**: Unravel a specific and novel molecular mechanism explaining how the same cf-PICI can be found in different bacterial species.

**Background:** The spread of antibiotic-resistant bacteria is a global health crisis. As superbugs evolve faster than new antibiotics are developed, effective treatments are becoming scarce. The key forces driving the rise of resistant and virulent strains remain poorly understood, hindering efforts to combat antibiotic resistance and reduce threats to human health and the environment.

Two fascinating players in the bacterial world, phages and phage-inducible chromosomal islands (PICIs), hold pivotal roles in bacterial evolution. Phages are viruses that infect bacteria, while PICIs are small (~10–15 kb), highly mobile genetic elements found in over 200 pathogenic bacterial species. PICIs hijack temperate phages (helper phages) to package their small genome into virus-like particles with small capsids, enabling their spread within bacterial populations.

Phages and PICIs can carry critical genes related to virulence and antibiotic resistance, making their acquisition a game-changer for a bacterium's pathogenicity or resistance profile. Understanding how these elements move between bacterial species is crucial.

Our recent work uncovered novel mechanisms of PICIs and helper phages in gene transfer. However, there is an unknown mechanism that could explain how a specific family of PICIs, called capsid-forming PICIs (cf-PICIs), spreads in nature. cf-PICIs are the most abundant members of the phage satellite and PICI families. Unlike typical phage satellites and other PICIs, cf-PICIs produce their own small capsids and independently package their DNA, requiring only phage tails to complete particle assembly. Although the cf-PICI genes responsible for capsid formation and DNA packaging resemble phage genes, they function exclusively with cf-PICI proteins.

Unlike phages and traditional PICIs with narrow host ranges, identical cf-PICIs are found across multiple bacterial species, suggesting a novel intra- and inter-species transfer mechanism. For example, two related cf-PICIs, EcCIGN02175 (hereby named PICIEc1) and KpCIDSM30104 (hereby named PICIKp1), were identified in *Escherichia coli* GN02175, *Klebsiella pneumoniae* DSM30104, and other species, many of which are WHO priority pathogens. PICIEc1 was detected in five genera and seven species, including *E. coli*, *K. pneumoniae*, *Shigella flexneri*, *Citrobacter freundii*, *Citrobacter amalonaticus*, *Enterobacter asburiae*, and *Enterobacter hormaechei*. Similarly, PICIKp1 was found in both *K. pneumoniae* and *E. coli*.

So the main question is, why can cf-PICIs, but not other types of PICIs or satellites, be easily found in different bacterial species? What is the mechanism that explains this?
````

#### research-overviews/als-research-overview-and-contact.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/research-overviews/als-research-overview-and-contact.md` — 84 lines, sha256 `6d2997eaeec0`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3:
    - "Example of a research overview by the Meta-review agent"             / Figures A.20-A.21 (lines 1205-1271)
    - "Example of research contact identification by the Meta-review agent"  / Figure A.22 (lines 1273-1280)
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Sections 10.11 (research overview) and 10.12 (research contact).
AGENT: Meta-review. CASE STUDY: ALS illustrative example.
ARTIFACTS: (a) the research overview -- the main final output presented to the scientist, mapping research directions; (b) a suggested research contact (expert names redacted in source).
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract (abbreviated in source; "..." / "• ..." / "– ..." / "∗ ..." ellipses are the source's).
-->

# ALS illustrative example — Meta-review agent research overview + research contact

## Research overview (Figures A.20–A.21)

#### [Main Research Directions]

We will be focusing on these interrelated areas:

- Mitochondrial Dysfunction and Oxidative Stress: This direction investigates defects in mitochondrial DNA repair, mitochondrial dynamics, calcium handling, and oxidative stress response, focusing on their role in initiating inflammatory signaling and neurodegeneration.
- RNA Processing and Stress Granules: This direction explores abnormalities in RNA processing, transport, and modification, as well as impaired stress granule dynamics, and their impact on protein homeostasis and neuronal survival. It includes examining RNA-binding proteins, RNA structure and modifications, translation defects, and the interplay between RNA and proteostatic stress responses.
- Protein Homeostasis and the Nucleocytoplasmic Transport: This direction is aimed at investigating defects in protein folding, trafficking, aggregation, and degradation, as well as nucleocytoplasmic transport (NCT) dysfunction, with a particular focus on the nuclear pore complex (NPC). This includes how those pathways and processes influence, and are influenced by, TDP-43 and FUS protein function and localization.

• ...

#### Mitochondrial Dysfunction and Oxidative Stress

- Rationale: Mitochondrial dysfunction and oxidative stress are consistently implicated in ALS pathogenesis. Mitochondria are critical for cellular energy production, and their dysfunction can lead to a cascade of events including increased oxidative stress, impaired calcium handling, inflammation, and ultimately cell death. Given the high energy requirements of motor neurons, especially upper motor neurons, these deficits are expected to have a significant impact. We hypothesize that specific mitochondrial vulnerabilities, not just generalized dysfunction play a very early role in initiating disease and provide a specific cellular event which can be targeted for research and for potential future therapy.
- Recent Findings: Research has shown that mutations in mitochondrial DNA (mtDNA) maintenance genes are associated with ALS. Further there are links between impaired mitochondrial calcium handling and oxidative stress, with a particular focus on base excision repair (BER) pathway defects and a potential link to activation of the cGAS-STING pathway. These findings suggest that a deeper understanding of mtDNA integrity, repair mechanisms, and ROS dynamics is critical for uncovering the initial drivers of ALS.

#### • Areas of Research:

#### – Mitochondrial DNA Repair Defects:

- ∗ Why Research? Explore the possibility that a deficiency in base excision repair (BER) enzymes for mitochondrial DNA is a primary driver of ALS.
- ∗ What to Research? Investigate the activity and expression of specific BER enzymes (e.g., OGG1) in iPSC-derived motor neurons from ALS patients and controls. Assess whether deficiencies correlate with increased accumulation of oxidized mtDNA lesions (e.g., 8-oxo-dG) and whether these can be released into the cytoplasm after VDAC or MOMP activation. Determine if this release activates the cGAS-STING pathway.
- ∗ Example Idea: Measure OGG1 enzyme activity, oxidized mtDNA levels (8-oxo-dG) and cGAS-STING activation in iPSC-derived motor neurons. Genetically manipulate (knock-out/overexpress) key components of the mitochondrial BER pathway or target specific pathways using small molecules. Use VDAC inhibitors to prevent release or modulate MOMP function to understand cause and effect of ox-mtDNA release and cGAS-STING activation on cell death and inflammatory outcomes.

#### – Mitochondrial Calcium Handling and Oxidative Stress:

- ∗ Why Research? Motor neurons have high calcium demands and are sensitive to oxidative damage. Imbalances in mitochondrial calcium handling and ROS production may trigger a cascade leading to neurodegeneration.
- ∗ What to Research? Examine the role of mitochondrial calcium uniporter (MCU) and other calcium transporters in ALS. Assess if dysregulated calcium influx into mitochondria leads to increased ROS production and whether this is different in different types of motor neurons. Study the potential role of calcium handling defects as a primary trigger or modifier of the disease.
- ∗ Example Idea: Use calcium indicators and ROS sensors in iPSC-derived motor neurons to monitor real-time calcium and ROS levels in mitochondria. Manipulate mitochondrial calcium uptake via pharmacological or genetic approaches (e.g., MCU inhibitors or knock-outs). Assess cell survival and the impact on inflammatory response markers and activation of the cGAS-STING pathway to assess direct causality.

– ...

<!-- Figure A.21 — research overview (continued) -->

#### RNA Processing and Stress Granules:

• ...

#### Protein Homeostasis and the Nucleocytoplasmic Transport:

- Rationale: The proper folding, trafficking, degradation, and localization of proteins are critical for cellular function. Defects in these processes can lead to the accumulation of toxic protein aggregates, disrupt cellular signaling, and initiate pathways leading to cell death in ALS. The nucleus is a key compartment, and transport into and out of this organelle is essential for cellular function.
- Recent Findings: Research has identified misfolded TDP-43 and FUS as key pathological features of ALS. Furthermore, the dysregulation of nucleocytoplasmic transport (NCT) and the nuclear pore complex (NPC) is a recurring feature, with recent findings that emphasize defects in early stages of assembly and dynamic function of the NPC as an early initiating step.
- Areas of Research:
  - Ubiquitin-Proteasome System (UPS) Dysfunction:
    - ∗ Why Research? The UPS is a major cellular protein degradation machinery. Defects in the UPS can lead to an accumulation of misfolded proteins, which could lead to cellular stress and death. Exploring the potential of a functional deficiency in these system as an early trigger in disease.
    - ∗ What to Research: Investigate how UPS functionality is altered in ALS models, with particular attention to the role of E3 ligases in TDP-43 and FUS degradation. Determine whether specific modifications on ALS related proteins impair their degradation and whether specific pathways of protein quality control are affected in early stages of the disease. Assess if this is a primary cause or secondary outcome of other disease related pathways.
    - ∗ Example Idea: Use cell-based assays to measure UPS activity and substrate degradation rates in iPSC-derived motor neurons. Conduct proteomic analysis to identify specific ubiquitinated proteins that accumulate in ALS cells. Genetically manipulate UPS components or use small molecules to modulate their function and assess cellular responses (e.g. measuring protein aggregation and cell survival)

#### – Autophagy Dysfunction:

- ∗ Why Research? Autophagy is crucial for clearing cellular debris and aggregates. Dysfunctional autophagy can lead to the accumulation of toxic proteins and can lead to organelle defects.
- ∗ What to Research? Explore how autophagy pathways are altered in ALS, focusing on the specific mechanisms of cargo recognition, autophagosome formation, and lysosome fusion. Assess if specific types of autophagy including mitophagy (mitochondrial specific) or lipophagy (lipid specific) are more vulnerable in specific cell types.
- ∗ Example Idea: Track the formation and degradation of autophagosomes in real-time in hiPSC-derived motor neurons after different stress conditions. Manipulate key effectors of the autophagy pathway and observe cellular response, measuring protein aggregation, cell viability and inflammatory markers.
- Nucleocytoplasmic Transport (NCT) Defects:

∗ ...

– Targeted Protein misfolding:

∗ ...

• ...

## Research contact identification (Figure A.22)

Research Direction: Oxidative DNA Damage & Mitochondrial Base Excision Repair (BER) in ALS

- [Researcher names]: They directly study the role of mitochondrial OGG1 (a key BER enzyme) in controlling cytosolic mtDNA release and neuroinflammation. Their expertise is highly valuable for understanding the link between BER, mtDNA, and inflammation. Also, they have experience with experiments using mtOGG1 overexpressing mice which is relevant to the in-vitro experiments proposed.
- ...
````

#### research-overviews/cf-pici-research-overview-directions-2-to-6.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/research-overviews/cf-pici-research-overview-directions-2-to-6.md` — 251 lines, sha256 `21b6985aecb2`.

````
<!--
SOURCE (verbatim): references/core/google-co-scientist/research/supplements/ai-mirrors-experimental-science-to-uncover-a-mechanism-of-gene-transfer-crucial-to-bacterial-evolution-supplementary-information.md
  "Supplemental Data S2. Output of the AI co-scientist, related to Figure 1" (full output is lines 45-410 of the source).
CASE STUDY: Antimicrobial resistance / bacterial gene transfer (cf-PICIs).
ARTIFACT: the Co-Scientist's research-overview OUTPUT for the cf-PICI goal -- this is the CONTINUATION of the sibling file
  02-research-overview-output.md, which reproduces the Introduction, the list of all six Main Research Directions, and the
  COMPLETE text of Direction #1 (Capsid-Tail Interactions, the winning/load-bearing direction). The present file reproduces the
  remaining FIVE detailed directions VERBATIM:
    #2 Integration Mechanisms                          (source lines 135-189)
    #3 Entry Mechanisms                                (source lines 191-243)
    #4 Helper Phage and Environmental Factors          (source lines 245-298)
    #5 Alternative Transfer and Stabilization Mechanisms (source lines 300-354)
    #6 Unexpected Areas of Research and Why to Research Them (source lines 356-410)
TRUNCATION: The source S2 output ends mid-list at line ~410 -- the fifth Unexpected Area ("The Evolutionary Origins of cf-PICIs")
  trails off with a dangling "- Investigate". This is a truncation in the SOURCE ITSELF (the published supplement is cut off there),
  reproduced here as-is and NOT completed.
FIDELITY NOTE: the PROSE is verbatim (word-for-word; mid-sentence line-wraps joined; inline citation links omitted). Source typos
  are preserved (e.g. "exampes", "hypothese", "restrictionmodification", "phagereceptor"). Markdown HEADING LEVELS and list nesting
  were normalized for readability to match the sibling file 02 (source mixed '##'/'####' with "●"/"■"/"○" glyph headings; rendered
  here as nested '###'/'####'/bullets). No words were added, removed, or changed.
-->

# cf-PICI / AMR case study — Co-Scientist research overview, Directions #2–#6 (output, continued)

> Continuation of `02-research-overview-output.md`. Direction #1 (Capsid-Tail Interactions) and the Introduction / six-direction
> list are in that file. This file holds the remaining detailed directions (#2–#6) from the same S2 output.

### 2. Integration Mechanisms

#### ● Why Research This Area?

- **Essential for Stable Inheritance:** For cf-PICIs to persist in a new host, they must integrate into the host's genome (or potentially exist as stable episomes, which will be discussed below). Understanding the integration mechanism is therefore crucial.
- **Potential for Broad Specificity:** The integrase enzyme responsible for integration might have relaxed sequence specificity, allowing it to recognize and integrate into a wider range of sites in diverse bacterial genomes than typical integrases.
- **Contribution to Host Range:** The ability to integrate into diverse genomic locations could directly contribute to the broad host range of cf-PICIs. This is supported by the fact that several of the ideas you listed point to relaxed or adaptable integrase specificity.
- **Novel Recombination Mechanisms:** cf-PICIs might employ novel recombination mechanisms or exploit host DNA repair pathways for integration, as suggested by some of the hypotheses you listed. Studying these mechanisms could reveal new aspects of bacterial DNA dynamics.
- **Recent Findings:** Recent studies have shown that some mobile genetic elements can utilize host factors, such as DNA repair proteins, to facilitate integration. This suggests that cf-PICIs might employ similar strategies. Furthermore, advances in genomics and bioinformatics now make it possible to analyze integration sites across diverse bacterial species with unprecedented precision.

#### ● What to Research in This Area?

- **Topic 1: Characterization of the cf-PICI Integrase:** Identify and characterize the integrase enzyme encoded by cf-PICIs.
  - **Why research this topic?** The integrase is the key enzyme responsible for mediating integration. Understanding its properties, such as its sequence specificity and catalytic mechanism, is essential for understanding how cf-PICIs integrate into diverse genomes. Some of the hypotheses you listed, such as the modular integrase, highlight the importance of this enzyme.
  - **Example Idea:** Use bioinformatic analysis to identify putative integrase genes within cf-PICI genomes. Clone, express, and purify the integrase protein. Then, use in vitro assays with synthetic DNA substrates to determine its sequence specificity and catalytic activity.
  - **■ Specific Questions:**
    - What is the sequence specificity of the cf-PICI integrase?
    - How does this specificity compare to that of other phage or PICI integrases?
    - Does the cf-PICI integrase require any host factors for activity?
    - What is the catalytic mechanism of the integrase?
- **Topic 2: Mapping Integration Sites:** Determine the preferred integration sites of cf-PICIs in the genomes of diverse bacterial species.
  - **Why research this topic?** Mapping integration sites will reveal whether cf-PICIs integrate randomly or at specific locations. If there are preferred sites, it will shed light on the recognition mechanism employed by the integrase. For example, if cf-PICIs frequently integrate near mobile genetic elements, it could suggest a strategy for increasing their own mobility, as suggested by some hypotheses.
  - **Example Idea:** Transfer cf-PICIs into a panel of diverse bacterial species. Then, use whole-genome sequencing and bioinformatic analysis to identify the precise locations of cf-PICI integration. Look for common sequence motifs or genomic features near the integration sites.
  - **■ Specific Questions:**
    - Do cf-PICIs integrate randomly or at specific sites in bacterial genomes?
    - Are there common features (e.g., sequence motifs, GC content, proximity to other mobile elements) near the integration sites?
    - Do different cf-PICIs have different integration site preferences?
    - How do the integration sites compare across different bacterial species?
- **Topic 3: Role of Host Factors:** Investigate the potential involvement of host DNA repair or recombination machinery in cf-PICI integration, as suggested by the "exploitation of host DNA repair pathways" in some of the proposed hypotheses.
  - **Why research this topic?** Host factors could play a crucial role in facilitating integration, particularly if the cf-PICI integrase has relaxed sequence specificity. This could be a mechanism for overcoming the limitations of a "promiscuous" integrase. The idea that cf-PICIs might exploit host non-homologous end joining (NHEJ) is particularly intriguing in this context.
  - **Example Idea:** Use genetic knockouts or CRISPR interference to deplete specific host DNA repair or recombination proteins in recipient bacteria. Then, measure the efficiency of cf-PICI integration in these mutant strains compared to wild-type strains.
  - **■ Specific Questions:**
    - Are any host DNA repair or recombination proteins required for efficient cf-PICI integration?
    - Does the involvement of host factors vary across different bacterial species?
    - Can we identify specific interactions between the cf-PICI integrase and host factors?
    - Does the host SOS response influence cf-PICI integration?
- **Topic 4: Episomal Maintenance:** Explore the possibility that cf-PICIs can exist as stable episomes (i.e., extrachromosomal DNA) in some bacterial species.
  - **Why research this topic?** Episomal maintenance could provide an alternative mechanism for persistence in new hosts, particularly if integration is inefficient or detrimental. This could be a temporary or even long-term strategy for cf-PICI survival, similar to what is observed with some plasmids and is also suggested in some of your exampes.
  - **Example Idea:** Use pulsed-field gel electrophoresis or other techniques that can separate episomal DNA from chromosomal DNA to determine if cf-PICIs are present as episomes in a panel of bacterial hosts. Investigate potential cf-PICI-encoded factors required for episomal maintenance.
  - **■ Specific Questions:**
    - Can cf-PICIs exist as stable episomes in any bacterial species?
    - If so, what are the mechanisms for episomal replication and segregation?
    - Do cf-PICIs encode any proteins that contribute to episomal maintenance?
    - What are the relative frequencies of integration versus episomal maintenance in different hosts?

### 3. Entry Mechanisms

#### ● Why Research This Area?

- **Beyond Traditional Phage Receptors:** While cf-PICIs utilize phage tails, their broad host range suggests they might employ entry mechanisms that are less dependent on specific phage receptor interactions than typical phages. Exploring alternative entry routes is a logical step.
- **Potential Role of Conserved Structures:** cf-PICIs might interact with conserved bacterial surface structures, such as LPS or outer membrane proteins, rather than relying solely on variable phage receptors. Several of the ideas you listed point to conserved surface structures as potential targets.
- **Novel Entry Pathways:** cf-PICIs could utilize novel entry pathways, such as those involving membrane vesicles or direct membrane fusion, as suggested by some of the hypotheses. Studying these could reveal new aspects of bacterial cell biology.
- **Recent Findings:** Recent research has shown that some phages can utilize multiple receptors or even bypass the need for specific receptors altogether. This suggests that cf-PICIs might have evolved similar strategies for broad host range entry. Moreover, the increasing recognition of the role of bacterial extracellular vesicles (EVs) in intercellular communication and horizontal gene transfer provides a strong rationale for investigating their potential involvement in cf-PICI transfer.

#### ● What to Research in This Area?

- **Topic 1: Identification of Bacterial Receptors:** Determine if cf-PICIs utilize specific bacterial receptors and, if so, identify them.
  - **Why research this topic?** Identifying the receptors used by cf-PICIs is crucial for understanding their entry mechanism. If they utilize conserved receptors, it would support the hypothesis that they can infect diverse species. If the receptors are variable, it would suggest a more complex mechanism, possibly involving multiple receptors or adaptor proteins.
  - **Example Idea:** Use a combination of genetic screens (e.g., CRISPR interference) in diverse bacterial species and biochemical approaches (e.g., affinity purification with cf-PICI capsids as bait) to identify potential receptors.
  - **■ Specific Questions:**
    - Do cf-PICIs utilize specific bacterial receptors for entry?
    - If so, what are the identities of these receptors?
    - Are the receptors conserved across different bacterial species?
    - How do the receptors interact with cf-PICI capsids or associated phage tails?
- **Topic 2: Role of Membrane Vesicles:** Investigate the potential involvement of bacterial outer membrane vesicles (OMVs) in cf-PICI entry, as suggested by the "Trojan Horse" and other related hypotheses.
  - **Why research this topic?** OMVs are known to play roles in intercellular communication and horizontal gene transfer. If cf-PICIs are packaged within or associated with OMVs, it could provide a mechanism for protected transfer and entry into diverse bacterial species, bypassing the need for specific receptors. Many of your listed hypothese support this direction.
  - **■ Example Idea:** Isolate OMVs from bacteria carrying cf-PICIs and determine if they contain cf-PICI DNA or capsids using techniques like electron microscopy and qPCR. Test whether these OMVs can transfer cf-PICIs to recipient bacteria.
  - **■ Specific Questions:**
    - Are cf-PICIs packaged within or associated with bacterial OMVs?
    - If so, what are the mechanisms for packaging or association?
    - Can OMV-associated cf-PICIs infect new bacterial hosts?
    - Does OMV-mediated transfer contribute to the broad host range of cf-PICIs?
- **Topic 3: Direct Membrane Interactions:** Explore the possibility that cf-PICI capsids can directly interact with and penetrate bacterial membranes, independent of specific receptors.
  - **Why research this topic?** Direct membrane interactions could provide a mechanism for entry into diverse species, bypassing the limitations of receptor-mediated entry. Some phages are known to utilize membrane fusion or pore formation for entry, and cf-PICIs might have evolved similar strategies. In addition, some of your examples suggest this direction of research.
  - **Example Idea:** Use liposome model systems to study the interactions between purified cf-PICI capsids and artificial membranes of varying lipid compositions. Use techniques like cryo-EM and fluorescence microscopy to visualize these interactions and look for evidence of membrane fusion or pore formation.
  - **■ Specific Questions:**
    - Can cf-PICI capsids directly interact with bacterial membranes?
    - If so, what are the mechanisms for these interactions (e.g., electrostatic interactions, hydrophobic insertion)?
    - Do these interactions lead to membrane fusion or pore formation?
    - Are there specific lipid components that are important for these interactions?
- **Topic 4: Role of Helper Phage Tails:** Clarify the precise role of helper phage tails in cf-PICI entry. Are they simply delivery vehicles, or do they actively participate in receptor recognition or membrane penetration?
  - **Why research this topic?** Understanding the role of helper phage tails is crucial for deciphering the entry mechanism. For instance, if the tails primarily serve to bring the cf-PICI capsid into proximity with the bacterial membrane, it would suggest that the capsid itself plays a more active role in entry. Also, as many of your hypotheses suggest, tails could have some promiscuous interactions that aid entry.
  - **Example Idea:** Construct chimeric phage tails with different receptorbinding domains and test their ability to mediate cf-PICI entry into various bacterial species. Use microscopy to visualize the interactions between cf-PICI particles (with different tails) and bacterial cells.
  - **■ Specific Questions:**
    - ■ What is the precise role of helper phage tails in cf-PICI entry?
    - Do the tails primarily mediate attachment, or do they also play a role in membrane penetration?
    - Does the receptor-binding specificity of the helper phage tail influence the host range of cf-PICI transfer?
    - Can cf-PICIs utilize tails from defective phages for entry?

### 4. Helper Phage and Environmental Factors

#### ● Why Research This Area?

- **Crucial Partnership:** cf-PICIs depend on helper phages for tails and other essential functions. The nature of this relationship could significantly influence cf-PICI transfer and host range. For example, if cf-PICIs preferentially utilize helper phages with broad host ranges, this could contribute to their own broad distribution.
- **Generalized Transduction Potential:** Some of the hypotheses you listed suggest that generalized transduction by helper phages might play a role in cf-PICI transfer. Investigating this possibility is important for understanding the mechanisms involved.
- **Ecological Context:** cf-PICI transfer likely occurs within complex microbial communities. Understanding the influence of environmental factors, such as nutrient availability, stress conditions, and the presence of other mobile genetic elements, is crucial for a complete picture.
- **Recent Findings:** Recent studies have highlighted the importance of prophages (dormant phages integrated into bacterial genomes) in bacterial evolution and horizontal gene transfer. This suggests that prophages might also play a role in cf-PICI dynamics. Furthermore, the increasing recognition of the role of environmental stress in inducing the SOS response and promoting horizontal gene transfer provides a strong rationale for investigating the influence of stress on cf-PICI transfer.

#### ● What to Research in This Area?

- **Topic 1: Helper Phage Specificity:** Determine the range of helper phages that can support cf-PICI transfer and whether there is a preference for phages with broad host ranges.
  - **Why research this topic?** Understanding helper phage specificity will shed light on the co-evolutionary relationship between cf-PICIs and their helpers. If cf-PICIs can utilize a wide range of helper phages, it would suggest a flexible strategy for survival and dissemination. Many of your suggested hypotheses also point to this direction.
  - **Example Idea:** Co-infect bacteria carrying cf-PICIs with a panel of different phages, including those with narrow and broad host ranges. Measure the efficiency of cf-PICI transfer mediated by each phage.
  - **■ Specific Questions:**
    - What is the range of helper phages that can support cf-PICI transfer?
    - Is there a correlation between the host range of the helper phage and the efficiency of cf-PICI transfer?
    - Do cf-PICIs preferentially utilize certain types of helper phages?
    - Can defective phages act as helper phages for cf-PICI transfer?
- **Topic 2: Role of Generalized Transduction:** Investigate the contribution of generalized transduction by helper phages to cf-PICI transfer, as suggested by several hypotheses listed in the prompt.
  - **Why research this topic?** Generalized transduction, where phages accidentally package host DNA instead of their own, could provide a mechanism for cf-PICI transfer that is less dependent on specific interactions between the cf-PICI capsid and phage tails.
  - **Example Idea:** Use DNase sensitivity assays to distinguish between cf-PICI transfer mediated by specific interactions (protected within phage particles) and generalized transduction (potentially sensitive to DNase). Compare cf-PICI transfer rates using helper phages with high and low generalized transduction frequencies.
  - **■ Specific Questions:**
    - Does generalized transduction contribute to cf-PICI transfer?
    - If so, what is the relative importance of generalized transduction compared to other transfer mechanisms?
    - Do certain helper phages mediate cf-PICI transfer primarily through generalized transduction?
    - Can we identify cf-PICI DNA packaged within generalized transducing particles?
- **Topic 3: Influence of Prophages:** Examine the potential role of resident prophages in cf-PICI transfer and maintenance.
  - **Why research this topic?** Prophages could act as helper phages for cf-PICI transfer, or they could provide integration sites for incoming cf-PICIs. The "Prophage-Mediated Transposition and Capture" hypothesis specifically highlights this possibility.
  - **Example Idea:** Compare cf-PICI transfer rates in bacterial strains with and without resident prophages. Investigate whether cf-PICIs preferentially integrate near or within prophage sequences.
  - **■ Specific Questions:**
    - Do resident prophages influence cf-PICI transfer or integration?
    - If so, what are the mechanisms involved?
    - Can prophages act as helper phages for cf-PICI transfer?
    - Do cf-PICIs preferentially integrate into or near prophage sequences?
- **Topic 4: Environmental Stress and SOS Response:** Investigate the influence of environmental stress and the bacterial SOS response on cf-PICI transfer.
  - **Why research this topic?** Environmental stress, such as exposure to antibiotics, can induce the SOS response, which in turn can activate prophages and increase the frequency of horizontal gene transfer. Several of your listed ideas also hint at the importance of stress. This could be a key factor in promoting cf-PICI dissemination in natural environments.
  - **Example Idea:** Measure cf-PICI transfer rates under various stress conditions, such as antibiotic exposure, UV irradiation, and nutrient limitation. Investigate the expression of cf-PICI genes and helper phage genes under these conditions.
  - **■ Specific Questions:**
    - Does environmental stress enhance cf-PICI transfer?
    - If so, what are the mechanisms involved?
    - Does the SOS response play a role in stress-induced cf-PICI transfer?
    - Are there specific stress conditions that are particularly effective at promoting cf-PICI transfer?

### 5. Alternative Transfer and Stabilization Mechanisms

#### ● Why Research This Area?

- **Beyond Phage-Mediated Transfer:** While helper phages are clearly important, cf-PICIs might also utilize alternative transfer mechanisms, such as conjugation or extracellular vesicles, to expand their reach. These mechanisms could be particularly important for transferring to distantly related bacteria where compatible helper phages might be scarce.
- **Conjugation as a Possibility:** Some mobile genetic elements can transfer via conjugation, a process involving direct cell-to-cell contact. It's conceivable that cf-PICIs could exploit conjugative plasmids or other conjugative elements for transfer, as suggested by some of the provided hypotheses.
- **Extracellular Vesicles (EVs) as Vehicles:** As discussed previously, EVs are emerging as important players in horizontal gene transfer. cf-PICIs could be packaged within or associated with EVs, providing a protected and potentially broad-host-range transfer mechanism. Many of the hypotheses you listed indicate that this will be an important area to research.
- **Unique Stabilization Strategies:** cf-PICIs might employ unique strategies for stabilizing their DNA in new hosts, such as encoding anti-restriction or anti-CRISPR systems, or utilizing novel DNA modifications, as hinted at by some of the listed hypotheses.
- **Recent Findings:** Recent studies have shown that conjugation can play a significant role in the spread of antibiotic resistance genes, even between distantly related bacteria. Furthermore, the discovery of diverse mechanisms for DNA transfer via EVs, including the transfer of antibiotic resistance genes, provides a strong rationale for investigating their potential involvement in cf-PICI dissemination.

#### ● What to Research in This Area?

- **Topic 1: Role of Conjugation:** Investigate the potential involvement of conjugative elements in cf-PICI transfer.
  - **Why research this topic?** Conjugation could provide a mechanism for cf-PICI transfer that is independent of helper phages, potentially allowing them to reach a broader range of hosts. Some hypotheses listed in your prompt, such as the "hitchhiking" on conjugative plasmids, specifically suggest this possibility.
  - **Example Idea:** Perform conjugation experiments using donor strains carrying both cf-PICIs and conjugative plasmids and recipient strains lacking both. Use selective media to isolate transconjugants that have acquired both the plasmid and the cf-PICI. Analyze the cf-PICI integration sites in the transconjugants.
  - **■ Specific Questions:**
    - Can cf-PICIs be transferred via conjugation?
    - If so, do they require the presence of a conjugative plasmid or other conjugative element?
    - Is there evidence of cf-PICI integration into conjugative elements?
    - How does the efficiency of conjugative transfer compare to phage-mediated transfer?
- **Topic 2: EV-Mediated Transfer:** Further explore the potential role of extracellular vesicles (EVs) in cf-PICI transfer, building on the ideas presented in the "Entry Mechanisms" section and several of the hypotheses you listed, such as the "Trojan Horse" and EV-mediated hypotheses.
  - **Why research this topic?** EVs could provide a protected and potentially broad-host-range mechanism for cf-PICI transfer, as discussed previously. This is a rapidly developing area of research with significant implications for horizontal gene transfer.
  - **Example Idea:** Purify EVs from bacterial cultures carrying cf-PICIs and characterize their contents using proteomics, genomics, and electron microscopy. Test the ability of these EVs to transfer cf-PICIs to recipient bacteria in vitro and in vivo.
  - **■ Specific Questions:**
    - Are cf-PICIs packaged within or associated with EVs?
    - What are the mechanisms for cf-PICI packaging or association with EVs?
    - Can EV-associated cf-PICIs infect new bacterial hosts and integrate into their genomes?
    - What is the efficiency of EV-mediated cf-PICI transfer compared to other mechanisms?
- **Topic 3: DNA Stabilization Mechanisms:** Investigate potential mechanisms for stabilizing cf-PICI DNA in new hosts, such as anti-restriction systems, anti-CRISPR systems, and novel DNA modifications.
  - **Why research this topic?** New hosts may have defense systems that target foreign DNA, such as restriction-modification systems and CRISPR-Cas systems. cf-PICIs might encode mechanisms to evade these defenses, ensuring their survival and integration. Several of the hypotheses you listed suggest that such mechanisms might be involved.
  - **Example Idea:** Use bioinformatic analysis to search for genes encoding potential anti-restriction or anti-CRISPR proteins within cf-PICI genomes. Test the ability of these proteins to protect cf-PICI DNA from restriction enzymes or CRISPR-Cas systems in vitro and in vivo. Investigate potential cf-PICI-encoded DNA modifications using mass spectrometry.
  - **■ Specific Questions:**
    - ■ Do cf-PICIs encode any proteins that can inhibit host restrictionmodification systems or CRISPR-Cas systems?
    - If so, what are the mechanisms of these inhibitors?
    - Do cf-PICIs utilize any novel DNA modifications to protect their DNA from host defenses?
    - How do these stabilization mechanisms contribute to the success of cf-PICI transfer and integration?
- **Topic 4: Alternative Replication Strategies:** Investigate whether cf-PICIs possess unique replication strategies that enhance their persistence or transfer, such as rolling circle replication or the formation of specialized intracellular compartments.
  - **Why research this topic?** Alternative replication strategies could increase cf-PICI copy number, enhancing the likelihood of transfer and integration. They could also provide protection from host nucleases or facilitate packaging into EVs. The "Janus Capsid and Heterogeneous Packaging Synergy" hypothesis, for example, suggests the possibility of pre-integration maintenance through rolling circle replication.
  - **Example Idea:** Use qPCR to quantify cf-PICI copy number in different bacterial hosts and under different growth conditions. Use advanced imaging techniques, such as super-resolution microscopy, to visualize cf-PICI DNA within cells and look for evidence of specialized replication compartments.
  - **■ Specific Questions:**
    - Do cf-PICIs utilize any alternative replication strategies, such as rolling circle replication?
    - If so, how do these strategies contribute to their persistence or transfer?
    - Do cf-PICIs form any specialized intracellular compartments for replication or packaging?
    - Does cf-PICI copy number correlate with transfer efficiency?

### 6. Unexpected Areas of Research and Why to Research Them

Beyond the core research directions outlined above, several unexpected areas might provide valuable insights into the broad host range of cf-PICIs:

#### 1. cf-PICI Interactions with Other Mobile Genetic Elements:

- **○ Why research this area?** cf-PICIs likely encounter and interact with other mobile genetic elements, such as transposons, insertion sequences, and other types of PICIs, within bacterial genomes. These interactions could influence cf-PICI integration, stability, and transfer. For example, some mobile elements might facilitate cf-PICI integration by creating genomic instability or providing recombination sites. Some hypotheses, such as "Generalized Transduction and Transposition Rescue" hint at these interactions.
- **○ What to research:**
  - ■ Investigate the genomic context of cf-PICI integration sites, looking for associations with other mobile genetic elements.
  - Experimentally manipulate the presence of other mobile elements in recipient bacteria and measure the impact on cf-PICI transfer and integration.
  - Use comparative genomics to study the co-evolution of cf-PICIs and other mobile elements.

#### 2. The Role of Quorum Sensing in cf-PICI Transfer:

- **○ Why research this area?** Quorum sensing, a bacterial communication system based on cell density, regulates various bacterial behaviors, including the expression of virulence factors and competence for DNA uptake. It's possible that quorum sensing could also influence cf-PICI transfer, either by modulating the expression of cf-PICI genes or by affecting the susceptibility of recipient bacteria.
- **○ What to research:**
  - Measure cf-PICI transfer rates at different cell densities and in the presence or absence of quorum sensing inhibitors.
  - Investigate the expression of cf-PICI genes under different quorum sensing conditions.
  - Use genetic screens to identify host quorum sensing genes that influence cf-PICI transfer.

#### 3. The Impact of Biofilms on cf-PICI Transfer:

- **○ Why research this area?** Biofilms, surface-attached communities of bacteria encased in a matrix, are common in natural environments and are often associated with increased antibiotic resistance. The biofilm environment could promote cf-PICI transfer by increasing cell-to-cell contact, facilitating horizontal gene transfer, and potentially inducing stress responses that activate cf-PICI mobilization. The "Seeding and Stochastic Heterogeneity" model touches upon this aspect.
- **○ What to research:**
  - Compare cf-PICI transfer rates in planktonic versus biofilm cultures.
  - Investigate the spatial distribution of cf-PICIs within biofilms using microscopy.
  - Study the influence of biofilm matrix components on cf-PICI transfer.

#### 4. The Potential for cf-PICI Transfer to Eukaryotic Cells:

- **○ Why research this area?** While cf-PICIs are primarily known to transfer between bacteria, the possibility of transfer to eukaryotic cells, including human cells, cannot be entirely ruled out. This could have significant implications for human health, particularly if cf-PICIs carry virulence or antibiotic resistance genes that could be expressed in eukaryotic cells. Some mechanisms proposed in the listed hypotheses, such as membrane vesicle interactions, could potentially mediate such transfer.
- **○ What to research:**
  - Co-culture bacteria carrying cf-PICIs with eukaryotic cell lines and screen for evidence of cf-PICI DNA transfer using PCR or other sensitive detection methods.
  - Investigate the potential for cf-PICI-encoded proteins to be expressed in eukaryotic cells.
  - ■ Use in silico analysis to identify potential eukaryotic-like promoters or other regulatory elements within cf-PICI genomes.

#### 5. The Evolutionary Origins of cf-PICIs:

- **○ Why research this area?** Understanding the evolutionary history of cf-PICIs could provide clues about the origins of their unique features, including their broad host range. For example, did they evolve from phages or other types of PICIs? Did they acquire their capsid-forming ability recently or in the distant past? Some of the ideas, for example the "minimalist capsid" hypothesis, implicitly touch upon these questions.
- **○ What to research:**
  - Use phylogenetic analysis to trace the evolutionary relationships between cf-PICIs, phages, and other PICIs.
  - Search for cf-PICI-like elements in diverse bacterial and archaeal genomes.
  - Investigate

<!-- The source S2 output is truncated here mid-list (line ~410 of the source): the fifth Unexpected Area trails off at a
     dangling "- Investigate". This truncation is present in the published supplement itself and is reproduced as-is, not completed. -->
````

#### research-overviews/cf-pici-research-overview.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/research-overviews/cf-pici-research-overview.md` — 91 lines, sha256 `748950658a5d`.

````
<!--
SOURCE (verbatim): references/core/google-co-scientist/research/supplements/ai-mirrors-experimental-science-to-uncover-a-mechanism-of-gene-transfer-crucial-to-bacterial-evolution-supplementary-information.md
  "Supplemental Data S2. Output of the AI co-scientist, related to Figure 1" (full output is lines 45-410 of the source).
CASE STUDY: Antimicrobial resistance / bacterial gene transfer (cf-PICIs).
ARTIFACT: the Co-Scientist's research-overview OUTPUT for the cf-PICI goal. Research Direction #1 (Capsid-Tail Interactions) is the
  KEY/winning direction -- it is the in-silico hypothesis that matched the team's real experimental discovery (cf-PICIs interact
  with diverse phage tails to expand host range).

SCOPE OF THIS EXTRACT: The full S2 output (source lines 45-410) enumerates SIX research directions, each with
  "Why Research This Area?", "What to Research", topics, and "Specific Questions". To keep this file faithful yet focused on the
  load-bearing result, this extract reproduces VERBATIM: the Introduction, the list of all six Main Research Directions, and the
  COMPLETE text of Direction #1 (Capsid-Tail Interactions). Directions #2-#6 (Integration, Entry, Helper Phage & Environmental
  Factors, Alternative Transfer & Stabilization, and Unexpected Areas) are present in full in the source at the cited line range
  but are not duplicated here. The source S2 ends mid-sentence ("Investigate") at line ~410 (truncated in the source itself).
FIDELITY NOTE: the PROSE is verbatim (word-for-word; mid-sentence line-wraps joined; inline citation links omitted). Markdown
  HEADING LEVELS and list nesting were normalized for readability (source mixed '##'/'####' with "●"/"■" glyph headings; rendered
  here as nested '###'/'####'/bullets). No words were added, removed, or changed.
-->

# cf-PICI / AMR case study — Co-Scientist research overview (output)

**Research Goal:** Unravel a specific and novel molecular mechanism explaining how the same cf-PICI can be found in different bacterial species.

### Introduction

Antibiotic resistance poses a grave threat to global health. Understanding the mechanisms driving the spread of resistance genes is paramount for developing effective countermeasures. Capsid-forming phage-inducible chromosomal islands (cf-PICIs) are key players in this arena. These mobile genetic elements, unlike typical phages and other PICIs, exhibit an extraordinary ability to transfer between diverse bacterial species, carrying with them virulence and antibiotic resistance genes.

This research aims to elucidate the molecular mechanisms underlying the broad host range of cf-PICIs, focusing on the observation that identical cf-PICIs, such as PICIEc1 and PICIKp1 are found in clinically relevant bacterial species, including WHO priority pathogens like *Escherichia coli* and *Klebsiella pneumoniae*. Unraveling this mystery is crucial for developing strategies to curb the spread of antibiotic resistance. We will do this by exploring many different research directions, including the ideas you listed in your prompt.

## Main Research Directions

Based on the background information and existing hypotheses, the following are the primary research directions that could explain the broad host range of cf-PICIs:

- 1. **Capsid-Tail Interactions:** Investigate the interactions between cf-PICI capsids and a broad range of helper phage tails (ideas related to broad tail interacting, tail adaptor proteins, tail-binding sites, capsid-mediated interactions, etc).
- 2. **Integration Mechanisms:** Examine the mechanisms by which cf-PICIs integrate into the genomes of diverse bacterial species (ideas related to integration, transposition, recombination, etc).
- 3. **Entry Mechanisms:** Explore alternative cf-PICI entry mechanisms beyond traditional phage receptor recognition (ideas related to membrane vesicles, surface structures, membrane perturbation, etc).
- 4. **Helper Phage and Environmental Factors:** Investigate the role of helper phages and broader ecological factors in cf-PICI transfer (ideas related to generalized transduction, prophages, community interactions, stress responses, etc).
- 5. **Alternative Transfer and Stabilization Mechanisms:** Explore other potential transfer mechanisms, such as conjugation, extracellular vesicles, and unique stabilization strategies, that might contribute to cf-PICI's broad host range (ideas related to conjugative plasmids, EVs, membrane mimicry, unique stabilization strategies, etc).
- 6. **Unexpected Areas of Research and Why to Research Them:** Beyond the core research directions outlined above, several unexpected areas might provide valuable insights into the broad host range of cf-PICIs

## Detailed Description of Each Main Research Direction

### 1. Capsid-Tail Interactions

#### ● Why Research This Area?

- **Central to cf-PICI Lifecycle:** cf-PICIs, while forming their own capsids, rely on helper phage tails for infection and DNA transfer. Understanding how they interact with a broad range of tails is fundamental to their lifecycle. Any of the ideas you listed in your prompt related to broad tail interaction, tail adaptors, and capsid-mediated interactions could be the key to understanding this.
- **Potential for Broad Host Range:** The ability to utilize diverse phage tails could directly contribute to the observed broad host range of cf-PICIs. If, for instance, cf-PICI capsids can interact with tails from phages that infect a wide array of bacteria, this would dramatically increase their transfer potential.
- **Novel Protein-Protein Interactions:** The interactions between cf-PICI capsids and phage tails likely involve novel protein-protein interactions not found in typical phage-host relationships. Studying these could reveal new principles of molecular recognition and assembly. For example the Tap protein mentioned in many ideas could provide a novel mechanism of interaction.
- **Therapeutic Target Potential:** If specific interactions are crucial for cf-PICI transfer, they could be targeted by novel therapeutics designed to disrupt these interactions and limit the spread of antibiotic resistance.
- **Recent Findings:** Recent studies have highlighted the unexpected flexibility of some phage tail proteins (e.g., tail fibers) in binding to different receptors. This suggests that similar flexibility might exist in the interactions between cf-PICI capsids and phage tails.
- **Supporting Evidence** Many of the hypotheses you listed in your prompt point precisely to this direction. These include, but are not limited to, the adaptable tail-docking hypothesis, proximal tail recognition, universal docking, modular tail adaptation, tail-tunneling complex, promiscuous tail hypothesis, and many more. They collectively underscore the importance of investigating capsid-tail interactions and provide a variety of testable predictions. In addition, our own preliminary data indicate that cf-PICI capsids can indeed interact with tails from multiple phage types, providing further impetus for this research direction.

#### ● What to Research in This Area?

- **Topic 1: Identification of Conserved Binding Sites:** Determine if there are conserved regions on cf-PICI capsids and/or phage tails that mediate their interaction.
  - **Why research this topic?** Identifying conserved binding sites would provide strong evidence for a specific interaction mechanism and could reveal the molecular basis for broad tail recognition. For instance, if a particular structural motif is consistently involved, it would suggest a fundamental mechanism for cf-PICI's adaptability.
  - **Example idea:** Use Cryo-EM to visualize the structure of cf-PICI capsids bound to different phage tails. Compare the structures to identify conserved contact points. Mutagenesis of these regions could then be used to test their importance for binding and transfer.
  - **■ Specific questions:**
    - Are there specific amino acid residues or structural motifs on cf-PICI capsid proteins that are essential for interacting with phage tails?
    - Do these residues/motifs show conservation across different cf-PICIs?
    - Can we identify corresponding conserved regions on diverse phage tails?
    - How do these interactions compare to typical phage-receptor interactions in terms of affinity and specificity?
- **Topic 2: Characterization of Adaptor Proteins:** Investigate the potential role of cf-PICI-encoded adaptor proteins in mediating interactions with diverse phage tails, as suggested by several ideas listed in the prompt.
  - **Why research this topic?** Adaptor proteins could provide a mechanism for enhanced flexibility and broad interaction. For instance, a single adaptor protein with multiple binding domains could link the cf-PICI capsid to a variety of phage tails. The Tap protein from many of your exampmle hypotheses is a candicate for such an adaptor protein.
  - **Example idea:** Use bioinformatic analysis to identify potential adaptor protein genes in cf-PICI genomes. Express and purify these proteins and test their ability to bind to both cf-PICI capsids and phage tails using techniques like pull-down assays and surface plasmon resonance.
  - **■ Specific questions:**
    - Do cf-PICIs encode proteins that can bind to both their capsids and phage tails?
    - If so, how do these proteins facilitate the interaction?
    - Do different cf-PICIs encode different adaptor proteins, potentially explaining variations in their host range?
    - Can we identify the specific binding domains on these adaptor proteins?
- **Topic 3: Structural Flexibility and Dynamics:** Examine the potential role of structural flexibility or disorder in cf-PICI capsid proteins in enabling interactions with diverse phage tails.
  - **Why research this topic?** Structural flexibility could allow cf-PICI capsids to adapt to the different shapes and sizes of various phage tails. This "induced fit" mechanism could be a key factor in their broad host range. Several ideas in your prompt also point to structural flexibility as potential explanation.
  - **Example idea:** Use NMR spectroscopy or molecular dynamics simulations to study the flexibility and dynamics of cf-PICI capsid proteins in the presence and absence of phage tails. Look for regions that undergo conformational changes upon binding.
  - **■ Specific questions:**
    - Are there regions of intrinsic disorder in cf-PICI capsid proteins?
    - Do these regions become more ordered upon binding to phage tails?
    - Does the flexibility of these regions correlate with the ability to bind to a wider range of tails?
    - How does this flexibility compare to that of typical phage capsid proteins?
- **Topic 4: Quantification of Binding Affinities:** Measure the binding affinities between cf-PICI capsids and tails from a diverse range of phages.
  - **Why research this topic?** Quantifying binding affinities will help determine the strength and specificity of these interactions. For example, weak, promiscuous interactions might suggest a different mechanism than strong, specific binding.
  - **Example Idea:** Use surface plasmon resonance (SPR) or isothermal titration calorimetry (ITC) to measure the binding affinities (Kd values) between purified cf-PICI capsids and tails from a panel of phages with different host ranges.
  - **■ Specific Questions:**
    - What is the range of binding affinities between cf-PICI capsids and different phage tails?
    - Is there a correlation between binding affinity and the ability of a phage to mediate cf-PICI transfer?
    - How do these affinities compare to those of typical phagereceptor interactions?
    - Do environmental factors (e.g., pH, ionic strength) affect these interactions?

<!-- Research Directions 2-6 continue in the source (S2, lines ~135-410). They are reproduced verbatim in the sibling file
     04-research-overview-directions-2-to-6.md. -->
````

#### reviews/als-reflection-reviews.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/reviews/als-reflection-reviews.md` — 106 lines, sha256 `2f486c549886`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3, Figures A.11-A.14:
    - "Example output of a complete novelty review by the Reflection agent" / Figure A.11 (lines 957-976)
    - "Example output of review critiques by the Reflection agent"        / Figure A.12 (lines 978-989)
    - "Example output of a full review by the Reflection agent"           / Figure A.13 (lines 991-1023)
    - "Example output of deep verification by the Reflection agent"        / Figure A.14 (lines 1025-1054)
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Sections 10.3 (novelty review), 10.4 (critiques), 10.5 (full review), 10.6 (deep verification).
AGENT: Reflection. CASE STUDY: ALS illustrative example. ARTIFACTS: novelty review, review critiques, full review, deep-verification review (all abbreviated in source).
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract. Each Figure boundary is marked below. "..." / "•  ..." ellipses are the source's abbreviations.
-->

# ALS illustrative example — Reflection agent reviews

## A.11 — Complete novelty review

#### Aspects already explored:

- TDP-43 mislocalization and aggregation in ALS: Extensively documented in multiple abstracts [1, 3, 4, 5, 6].
- Nucleocytoplasmic transport defects in ALS: Demonstrated in connection with TDP-43 pathology and C9orf72 mutations [4, 5, 6].
- NPC disruption in neurodegenerative diseases: Identified in ALS/FTD, Alzheimer's, Huntington's, and others, suggesting a common mechanism [4, 5, 7, 8].
- The link between cellular stress and TDP-43 pathology: Explored in the context of stress granule formation and TDP-43 aggregation [5]. Note - stress is explored in general, but the idea of it leading to PTMs of Nups is new.
- Role of FG-Nups in NPC function: FG-Nups are known to form a selective barrier regulating transport, but the impact of their PTMs on TDP-43 interaction in ALS is novel [7].
- The implication of PTMs for TDP-43: TDP-43 PTMs are widely researched, especially phosphorylation and ubiquitination. However, our hypothesis doesn't speak about TDP-43 PTMs, it is about Nup PTMs [1, 3, 4].

#### Novel Aspects:

- Cellular stress as an initiator of Nup PTMs: While stress is linked to TDP-43 pathology, the idea that it triggers specific PTMs on Nups (Nup98/Nup62) as an initiating event in ALS is novel, especially that these PTMs are phosphorylation and O-GlcNAcylation.
- Nup PTMs (phosphorylation and O-GlcNAcylation specifically) altering TDP-43 interaction at the NPC: The hypothesis proposes a novel mechanism where stress-induced PTMs on specific Nups (Nup98/Nup62) directly modify their interaction with TDP-43. This hasn't been explored before, particularly the focus on these specific PTMs and Nups.
- TDP-43 retention at the NPC as a key event: Instead of focusing on LLPS or aggregation directly, the hypothesis suggests that altered TDP-43 dynamics, specifically increased retention at the NPC due to modified Nup interactions, are a triggering factor. This specific mechanism at the NPC disrupting nucleocytoplasmic transport is novel.
- Focus on early events and potential for therapeutic intervention: By pinpointing early molecular events (Nup PTMs, altered TDP-43-Nup interaction), the hypothesis opens new avenues for therapeutic intervention targeting these specific processes, potentially before irreversible damage occurs.
- Broadening stress beyond ER stress: It is novel to consider multiple stressors in combination and it broadens the idea beyond ER stress (as suggested in the original provided idea).

## A.12 — Review critiques

- Lack of strong justification for motor neuron specificity: The initial hypothesis lacked a strong explanation for why the proposed mechanism would predominantly affect motor neurons, a critical aspect of ALS pathology.
- Limited exploration of downstream consequences: While the idea connects to nucleocytoplasmic transport defects, it doesn't fully elaborate on how these defects lead to other ALS-related pathologies like TDP-43 aggregation or RNA processing defects.
- Potential technical challenges: Identifying the specific PTMs responsible and demonstrating their direct impact on TDP-43 retention and transport might be technically difficult.
- Narrow focus on specific Nups and PTMs: Initially focusing only on Nup98/Nup62 and two types of PTMs (phosphorylation, O-GlcNAcylation) could be too restrictive, potentially overlooking other important factors.
- Less holistic approach: The focus on a specific mechanism at the NPC might neglect broader cellular processes involved in ALS pathogenesis.
- The temporal relationship with TDP-43 pathology is not clear: It's not clear whether the hypothesized mechanism occurs before or after other ALS hallmarks like cytoplasmic TDP-43 aggregation, which is crucial for establishing causality.

• ...

## A.13 — Full review

#### Related Articles:

- [5] TDP-43 pathology disrupts nuclear pore complexes and nucleocytoplasmic transport in ALS/FTD PMC: This article is highly relevant because it directly links TDP-43 pathology to nuclear pore complex (NPC) dysfunction and nucleocytoplasmic transport (NCT) defects in ALS/FTD, providing a strong foundation for the hypothesis.
- [4] Unraveling the impact of disrupted nucleocytoplasmic transport systems in C9orf72-associated ALS PMC: This article provides context on NCT defects in ALS, particularly in the context of C9orf72 mutations, highlighting the broader relevance of NCT dysfunction in different forms of ALS.
- [7] Nuclear pore and nucleocytoplasmic transport impairment in oxidative stress-induced neurodegeneration: relevance to molecular mechanisms in Pathogenesis of Parkinson's and other related neurodegenerative diseases - PMC: This article connects oxidative stress, a form of cellular stress, to NPC dysfunction and NCT impairment in neurodegenerative diseases, supporting the idea that cellular stress can impact NPCs.
- [3] Frontiers | Molecular Mechanisms of TDP-43 Misfolding and Pathology in Amyotrophic Lateral Sclerosis: This article reviews TDP-43 pathology in ALS, including its mislocalization and aggregation, which are central to the proposed hypothesis.
- [1] TDP-43 proteinopathies: a new wave of neurodegenerative diseases PMC: Provides an overview of TDP-43 proteinopathies, establishing the importance of TDP-43 dysfunction in ALS and other neurodegenerative diseases.
- [8] Aβ-driven nuclear pore complex dysfunction alters activation of necroptosis proteins in a mouse model of Alzheimer's Disease: Although focused on Alzheimer's, this article demonstrates that NPC dysfunction can occur in neurodegenerative diseases and highlights the potential impact on cellular processes like necroptosis. It supports the general idea that NPC defects can be a consequence of proteinopathy-associated stress.
- [9] Traumatic injury compromises nucleocytoplasmic transport and leads to TDP-43 pathology: This article provides another example of how cellular stress (traumatic injury) can lead to NCT defects and TDP-43 pathology, further supporting the link between stress, NCT, and TDP-43 dysfunction.

Assumptions of the Idea:

...

- Cellular stress induces PTMs on Nup98 and Nup62: The hypothesis assumes that various forms of cellular stress can trigger specific PTMs (phosphorylation and O-GlcNAcylation) on Nup98 and Nup62.
- PTMs on Nup98/Nup62 alter their interaction with TDP-43: It's assumed that these specific PTMs directly modify the binding affinity or interaction dynamics between Nup98/Nup62 and TDP-43 at the NPC.
- Altered Nup-TDP-43 interaction leads to increased TDP-43 retention at the NPC: This assumption posits that the modified interaction results in TDP-43 being trapped or retained at the NPC for longer durations.
- Increased TDP-43 retention at the NPC disrupts nucleocytoplasmic transport: The hypothesis assumes that this prolonged retention of TDP-43 at the NPC interferes with the normal transport of other molecules across the nuclear envelope.
- Nucleocytoplasmic transport defects contribute to ALS pathology: The idea assumes that the resulting NCT disruption is a significant contributor to the downstream pathological events in ALS, such as motor neuron degeneration.
- Motor neurons are more susceptible to this mechanism: It's assumed that motor neurons are particularly vulnerable to this stress-induced, Nup-mediated TDP-43 retention and subsequent NCT defects compared to other cell types.

#### Reasoning about assumptions:

- Cellular stress induces PTMs on Nup98 and Nup62: This is plausible. Cellular stress is known to activate various signaling pathways that can lead to PTMs on numerous proteins. Nups, being long-lived proteins, are susceptible to modifications. However, whether Nup98 and Nup62 are specifically targeted by stress-induced phosphorylation and O-GlcNAcylation needs experimental verification.
- PTMs on Nup98/Nup62 alter their interaction with TDP-43: This is possible but requires experimental validation. PTMs can significantly alter protein-protein interactions by changing surface charge, conformation, or binding sites. While there's no direct evidence for this specific interaction, it's a reasonable hypothesis given the role of FG-Nups in interacting with transport factors.
- Nucleocytoplasmic transport defects contribute to ALS pathology: This is supported by existing literature [4, 5]. NCT defects have been observed in ALS and are thought to contribute to disease pathogenesis. However, whether this specific mechanism is a primary driver or a downstream consequence needs further investigation.
- Motor neurons are more susceptible to this mechanism: This is a crucial assumption but lacks strong justification in the current proposal. Motor neurons have unique characteristics (high metabolic demand, long axons) that might make them more vulnerable to stress and NCT defects. However, this needs to be explicitly tested by comparing motor neurons to other cell types.

• ...

## A.14 — Deep verification review

#### Assumptions:

- Cellular stress induces PTMs like phosphorylation and O-GlcNAcylation.
- Nup98 and Nup62 interact with TDP-43 at the NPC.
  - Nup98 can interact with TDP-43
  - Nup62 can interact with TDP-43
- Altered interaction between Nups and TDP-43 leads to increased TDP-43 retention at the NPC.
- Disrupted nucleocytoplasmic transport triggers downstream ALS pathology.
- Motor neurons are inherently more vulnerable to this mechanism.
- The level of cellular stress inducing these PTMs is sufficient to cause a significant impact on TDP-43 localization.
- TDP-43 localizes to the nuclear pore complex (NPC).
- ...

#### 1. Cellular stress induces PTMs like phosphorylation and O-GlcNAcylation.

Cellular stress encompasses a range of conditions that disrupt cellular homeostasis, including nutrient deprivation, hypoxia, oxidative stress, and the accumulation of misfolded proteins. The endoplasmic reticulum (ER) is a central organelle involved in protein synthesis, folding, and modification. When the ER's capacity to handle protein folding is overwhelmed, a condition known as ER stress arises. This triggers a signaling pathway called the unfolded protein response (UPR) aimed at restoring ER homeostasis.

Post-translational modifications (PTMs) are covalent modifications to proteins that occur after translation. They play crucial roles in regulating protein function, localization, and interactions. Phosphorylation, the addition of a phosphate group, and O-GlcNAcylation, the addition of O-linked N-acetylglucosamine, are two common PTMs.

Numerous studies have demonstrated a strong link between cellular stress, including ER stress, and the alteration of PTMs. Here's a breakdown:

- ER Stress and Phosphorylation: The UPR, activated during ER stress, involves multiple signaling pathways, many of which rely on phosphorylation. For example, PERK (PKR-like ER kinase), a key UPR sensor, undergoes autophosphorylation upon sensing misfolded proteins. This activated PERK then phosphorylates eIF2α (eukaryotic initiation factor 2 alpha), leading to a global attenuation of translation. Another UPR sensor, IRE1 (inositol-requiring enzyme 1), possesses both kinase and endoribonuclease activity. Upon activation, IRE1 autophosphorylates and splices XBP1 mRNA, leading to the production of a transcription factor that upregulates chaperones and other proteins involved in protein folding and degradation. These are just two examples; numerous other proteins are phosphorylated during ER stress, affecting various cellular processes.
- ER Stress and O-GlcNAcylation: O-GlcNAcylation is a dynamic PTM influenced by nutrient availability and cellular stress. Evidence suggests a complex interplay between ER stress and O-GlcNAcylation. Some studies report increased O-GlcNAcylation during ER stress, potentially as a protective mechanism. For example, O-GlcNAcylation of certain chaperones can enhance their activity and promote protein folding. Conversely, other studies suggest that ER stress can lead to decreased O-GlcNAcylation. The exact relationship likely depends on the specific stress conditions, cell type, and the targeted proteins.
- Cellular Stress (beyond ER Stress) and PTMs: Other forms of cellular stress also impact PTMs. Oxidative stress, for example, can lead to protein oxidation, which can affect protein function and stability. Nutrient deprivation can alter the availability of substrates for PTMs, such as UDP-GlcNAc for O-GlcNAcylation. Hypoxia can also induce changes in phosphorylation and other PTMs, influencing cellular responses to low oxygen levels.

In summary, the available evidence strongly supports the assertion that cellular stress, including ER stress, can induce PTMs like phosphorylation and O-GlcNAcylation on proteins. This effect is mediated by complex signaling pathways and serves to regulate various cellular processes in response to stress.
````

#### reviews/mcomt-observation-review.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/reviews/mcomt-observation-review.md` — 26 lines, sha256 `74ac5d71a5fc`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example output of an observation review by the Reflection Agent" / Figure A.16 (lines 1091-1108).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.8 (lines ~1531-1549).
AGENT: Reflection (observation review). CASE STUDY: Antimicrobial resistance (cf-PICIs).
ARTIFACT: an observation review of an ALTERNATIVE cf-PICI hypothesis -- the "Modular Capsid-OMV Mediated Transfer" (MCOMT)
  hypothesis. (Per the source caption, the [Research Goal] is shown for illustration only and is not part of the review output.)
VERBATIM extract (abbreviated in source with "• ...").
-->

# cf-PICI / AMR case study — observation review (MCOMT hypothesis)

#### [Research Goal]

Unravel a specific and novel molecular mechanism explaining how the same cf-PICI can be found in different bacterial species.

Why can cf-PICIs, but not other types of PICIs or satellites, be easily found in different bacterial species? What is the mechanism that explains this?

#### [Output]

The "Modular Capsid-OMV Mediated Transfer" (MCOMT) hypothesis proposes that cf-PICIs achieve their broad host range through a combination of modular capsid interactions and OMV-mediated transfer, using both tail-dependent and tail-independent mechanisms. Several observations support this hypothesis:

- Widespread presence of PICIs in Gram-negative bacteria, particularly Enterobacteriaceae and Pastuerellaceae: These bacteria readily produce and internalize OMVs, aligning with the MCOMT hypothesis that OMVs are crucial for cf-PICI dissemination. The modular capsid, with its broad bacterial surface binding capabilities, further enhances transfer even without specific tail receptors on target cells.
- Unique PICI att sites not used by temperate prophages: The MCOMT hypothesis, by reducing reliance on helper phage integration due to OMV-mediated transfer and diverse entry routes, explains the evolution of cf-PICI-specific att sites independent of phage integration sites. This allows wider integration across bacterial genomes.

• ...
````

#### reviews/reparixin-deep-verification-probing.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/reviews/reparixin-deep-verification-probing.md` — 41 lines, sha256 `e133f842f15a`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example output of deep verification via probing questions by the Reflection agent" / Figure A.15 (lines 1056-1089).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.7 (lines ~1497-1529).
AGENT: Reflection (deep verification via probing questions). CASE STUDY: Drug repurposing for AML (Reparixin / CXCR1/2).
ARTIFACT: a probing-question deep-verification review. (Per the source caption, the [Research Goal] is shown "for illustration only, it is not included in the review output.")
VERBATIM extract.
-->

# AML drug repurposing — deep-verification via probing questions (Reparixin)

#### [Research Goal]

Repurposing Reparixin for AML treatment.

Suggest an existing drug that could be repurposed for Acute myelogenous leukemia (AML) treatment and provide experimentally testable concentrations for an IC50 assay. The drug should inhibit the proliferation of AML cell lines, particularly MOLM13.

The drug should have minimal cytotoxicity in healthy cell lines (have a good tradeoff for AML treatment). The drug should not have been experimentally tested for AML treatment before.

Reason about the drug's molecular mechanism, impacted pathways, and effect on AML cell proliferation inhibition. Describe the mechanism of action in detail. Reason about the safety and toxicity, stating if no safety data exists.

#### [Output]

Question: Sufficiency of CXCR1/2 Inhibition: What is the rationale for assuming that CXCR1/2 inhibition \*alone\* will be sufficient to overcome the established heterogeneity and multiple compensatory pathways known to drive AML progression and resistance, \*even before\* considering combination therapies?

This challenges the fundamental assumption that targeting a single pathway (even a dual-target one) will be effective in a complex disease like AML. AML is known for its ability to bypass single-target inhibition. Addressing this upfront is crucial to justify the entire approach, especially before investing heavily in combination studies.

Answer: The rationale for initially focusing on CXCR1/2 inhibition with Reparixin, before immediately jumping to combinations, stems from several interwoven, but not entirely definitive, points:

- Targeting a Key TME Node: CXCR1/2 are major regulators of neutrophil and myeloid-derived suppressor cell (MDSC) recruitment to the tumor microenvironment. These cells, in turn, contribute significantly to immune suppression, angiogenesis, and therapy resistance in AML. By blocking these receptors, Reparixin aims to disrupt a central hub of TME-mediated support for AML cells. The idea is not necessarily that CXCR1/2 inhibition is sufficient in all cases, but that it addresses a significant and often overlooked contributor to AML progression.
- Dual Receptor Blockade: Reparixin's dual inhibition of CXCR1 and CXCR2 is hypothesized to be more effective than targeting either receptor individually. While not explicitly stated in the provided text, there could be redundancy or synergy between these two receptors in promoting AML progression. Blocking both might offer a more substantial impact on the TME than single-receptor antagonists.
- Establishing a Baseline: The proposal, while acknowledging the complexity of AML, strategically starts with single-agent Reparixin to establish a clear baseline of its activity and effects. This is crucial for several reasons:
  - Understanding Single-Agent Effects: It's essential to dissect the specific contributions of Reparixin alone before introducing the complexity of combinations. This allows for a more rational design of combination strategies.
  - Identifying Resistance Mechanisms: Studying single-agent resistance is simpler and more direct than untangling resistance mechanisms in a multi-drug scenario. The extensive resistance studies proposed are specifically geared towards understanding Reparixin-specific resistance.
  - Patient Stratification: The comprehensive patient stratification plan is designed to identify patients who might respond to Reparixin as a single agent, or for whom it forms a critical foundation for combination therapy.
- TME Reprogramming, Not Just Cytotoxicity: The proposal positions Reparixin not just as a cytotoxic agent, but as a TME modulator. The hypothesis is that by altering the TME, Reparixin may sensitize AML cells to other therapies or even trigger immune-mediated clearance. This "reprogramming" effect might not be fully captured by traditional cytotoxicity assays alone.
- Sequential therapy: The proposal includes sequential administration of drugs, where Reparixin can prime the tumor cells for killing and/or resensitize them too.

Reasoning: The idea isn't incoherent, but it requires careful consideration of the sufficiency assumption. While the points above provide a rationale, they don't guarantee that CXCR1/2 inhibition alone will be sufficient in all, or even most, cases of AML. The heterogeneity of AML, with its multitude of driver mutations and compensatory pathways, strongly suggests that combination therapies will ultimately be necessary for many patients.

The strength of the proposal lies in its methodical approach. It doesn't claim that Reparixin is a magic bullet. It sets out to systematically investigate its potential, both alone and in combination, and to identify the specific patient subsets most likely to benefit. The extensive in vivo and patient stratification studies are key to addressing the "sufficiency" question empirically. The proposal is essentially a very detailed roadmap for determining when and how CXCR1/2 inhibition can be most effectively used in AML treatment, rather than an assertion of universal single-agent efficacy. Therefore the idea may require combination approaches but the study plan described in the proposal is structured in a way to determine that.
````

#### specific-aims/givosiran-aml.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/specific-aims/givosiran-aml.md` — 74 lines, sha256 `e37cd65c356d`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.5.3 "Examples of co-scientist generated Specific Aims with expert evaluation" / Figures A.26-A.27 (lines 1427-1496).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 4.1.1 "Example 1: Givosiran for AML" (lines 121-193).
CASE STUDY: Drug repurposing for AML. ARTIFACT: a Co-Scientist hypothesis reformatted by the Meta-review agent into the NIH grant "Specific Aims Page" format (one of 78 such proposals that expert oncologists rated). This shows the constrained-decoding / formatted-output capability.
VERBATIM extract (from canonical source; the Nature supplement also includes the per-aim "Expert rating" tables not reproduced here).
-->

# AML drug repurposing — Givosiran Specific Aims (NIH format)

### Givosiran for AML

#### Disease Description

Acute myeloid leukemia (AML) is an aggressive hematological malignancy with an incidence rate of approximately 4.3 per 100,000 persons per year in the United States, predominantly affecting older adults. AML arises from a complex interplay of genetic mutations, epigenetic alterations, and dysregulated signaling pathways, disrupting normal hematopoiesis by blocking myeloid differentiation and promoting uncontrolled blast proliferation. This leads to bone marrow failure, infections, bleeding, and other life-threatening complications. The current standard of care includes intensive chemotherapy, often combined with targeted therapies or hematopoietic stem cell transplantation. However, these treatments are often associated with significant toxicity, high relapse rates, and limited efficacy in certain patient populations, particularly in relapsed/refractory or high-risk AML.

#### Unmet Need

Despite advancements, significant unmet needs persist in AML treatment. Current therapies often cause severe side effects, particularly in older or frail patients, limiting their tolerability and effectiveness. Relapse rates remain high, and treatment options for relapsed/refractory AML are limited and often less effective. Many patients fail to achieve complete remission or experience only short-lived responses, underscoring the urgent need for novel, less toxic, and more effective therapies, especially for patients with relapsed/refractory or high-risk disease.

#### Proposed Solution

Givosiran sodium is an RNA interference (RNAi) therapeutic approved for acute hepatic porphyria (AHP). It targets aminolevulinate synthase 1 (ALAS1) mRNA, the rate-limiting enzyme in heme biosynthesis, reducing the production of heme precursors δ-aminolevulinic acid (ALA) and porphobilinogen. This prevents the accumulation of neurotoxic heme intermediates in AHP.

Repurposing givosiran for AML stems from the crucial role of heme biosynthesis in AML pathogenesis. Several studies suggest that disrupting heme biosynthesis offers a therapeutic advantage in AML. The proposed approach addresses the unmet need by targeting AML cells dependent on increased heme biosynthesis, particularly those with MYCN overexpression [1]. Modulating heme levels could influence oxidative stress [5, 6], apoptosis [1, 2], and drug sensitivity in AML [2]. Givosiran's ALAS1 inhibition aligns with this approach, offering a novel therapeutic strategy.

We hypothesize that givosiran, by inhibiting ALAS1 and reducing heme biosynthesis, will suppress AML cell growth and survival, particularly in those with upregulated heme biosynthesis. This is supported by preclinical evidence demonstrating that altering heme levels impacts AML cell proliferation, apoptosis, and drug sensitivity [2]. Abstract [1] suggests that elevated heme biosynthesis in MYCN-driven AML is a therapeutic vulnerability. Reducing ALA and porphobilinogen accumulation via givosiran can mitigate oxidative stress [6], a factor implicated in AML progression. Overall, our goal is to evaluate the efficacy and safety of givosiran as a novel therapeutic strategy for AML by exploiting the crucial role of heme biosynthesis in its pathogenesis and the drug's ability to modulate heme levels and downstream effects on AML cell proliferation, survival, and drug sensitivity.

### Specific Aims 1

#### Overarching goal:

Determine the anti-leukemic activity of givosiran in MYCN-driven AML models.

#### Hypothesis:

Givosiran treatment will decrease the viability and proliferation of MYCN-overexpressing AML cells in vitro and reduce tumor growth in MYCN-driven AML xenograft mouse models.

#### Reasoning:

MYCN-driven AML frequently exhibits upregulated heme biosynthesis [1], creating a potential dependency on this pathway. Givosiran, by inhibiting ALAS1, could disrupt this dependency, leading to decreased heme and growth inhibition. This is supported by preclinical data showing that inhibiting heme biosynthesis impacts AML cell growth and survival [1, 2].

### Specific Aims 2

#### Overarching goal:

Elucidate the impact of givosiran on oxidative stress and drug sensitivity in AML.

#### Hypothesis:

Givosiran treatment will modulate oxidative stress levels and enhance the cytotoxic effects of standard AML chemotherapeutics (e.g., cytarabine) in AML cell lines and primary patient samples.

#### Reasoning:

Heme plays a role in oxidative stress regulation, and its modulation by givosiran could influence AML cell chemosensitivity. Abstracts [5, 6] highlight oxidative stress in AML and the potential for ALA accumulation to contribute to it. By reducing ALA and heme, givosiran could alter reactive oxygen species (ROS) levels and potentially sensitize AML cells to chemotherapy-induced death.

### Specific Aims 3

#### Overarching goal:

Characterize the safety and tolerability of givosiran in preclinical AML models, focusing on its impact on liver function.

#### Hypothesis:

Givosiran treatment will be well-tolerated in AML mouse models, with minimal adverse effects on liver function and drug metabolism, at doses that effectively inhibit ALAS1 and reduce heme biosynthesis.

#### Reasoning:

Given givosiran's hepatic target (ALAS1), evaluating its safety profile in AML is crucial. Abstracts [7, 8] highlight the clinical significance of liver function in AML patients. This aim will assess potential hepatotoxicity and drug-drug interactions, ensuring safe translation to clinical trials. We will evaluate relevant liver function markers and givosiran's impact on standard AML chemotherapeutic metabolism.

#### Pilot Evaluation

A pilot study in a human AML xenograft mouse model will assess givosiran's in vivo efficacy and safety. Givosiran will be administered at various doses, monitoring tumor growth, survival, and liver function. The primary endpoint will be tumor growth inhibition. Secondary endpoints include survival, changes in heme levels, oxidative stress markers, and liver function tests. Existing safety data from givosiran's use in AHP will inform dose selection and monitoring. While givosiran is approved for AHP, its use in AML requires an Investigational New Drug (IND) application to the FDA before clinical trials. Existing safety data might facilitate a streamlined review process.
````

#### specific-aims/lapatinib-colon-cancer.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/specific-aims/lapatinib-colon-cancer.md` — 118 lines, sha256 `ba876c0d0bae`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.5.3 "Examples of co-scientist generated Specific Aims with expert evaluation" / Figures A.30-A.31 (lines 1597-1705).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 4.1.3 "Example 3: Lapatinib for colon cancer" (lines 259-~353). The per-axis Expert-rating list below is reproduced
  verbatim from the arXiv report, the canonical source here.
CASE STUDY: Drug repurposing — Specific Aims (colon adenocarcinoma / COAD). ARTIFACT: a Co-Scientist hypothesis reformatted by the
  Meta-review agent into the NIH "Specific Aims Page" format; the third of the three worked examples at A.26-A.31, and the second of the
  two (Selinexor, Lapatinib) carrying a full 15-axis "Expert rating" block against the A.5.2 rubric.
VERBATIM extract. The "Articles" list is abbreviated in the source (only [1], [2], [19] shown, with an ellipsis gap for [3]-[18]) — kept as-is.
The 15 numbered Expert-rating items map to the A.5.2 rubric (5 "Significance and innovation" + 10 "Rigor and feasibility").
-->

# Drug-repurposing Specific Aims — Lapatinib for colon cancer (NIH format, with expert rating)

## Lapatinib for colon cancer

#### Disease Description

Colon adenocarcinoma (COAD) is a significant public health concern, with an estimated incidence rate of over 150,000 new cases annually in the United States [19]. COAD arises from the epithelial lining of the colon, and its pathogenesis involves a complex interplay of genetic and environmental factors. Key molecular mechanisms include mutations in genes such as APC, KRAS, BRAF, and PIK3CA, as well as dysregulation of signaling pathways like Wnt, RAS/RAF/MEK/ERK, and PI3K/AKT/mTOR [8, 9, 12]. These alterations drive uncontrolled cell proliferation, evade apoptosis [14], promote angiogenesis [15], and ultimately lead to tumor growth, invasion, and metastasis [16]. The disease typically progresses through a series of stages, from localized tumors to regional lymph node involvement and distant metastasis. Current standard of care involves surgery, chemotherapy, and targeted therapies such as anti-EGFR antibodies. However, these treatments have limitations, including acquired resistance and significant toxicity.

#### Unmet Need

A major unmet need in COAD treatment is the development of effective therapies for patients who progress on or are refractory to standard treatments, particularly those with resistance to anti-EGFR therapy [2]. Despite available therapies, many patients experience disease recurrence and metastasis, leading to poor outcomes and diminished quality of life. There's a critical need for new therapeutic options that can overcome resistance mechanisms, improve response rates, and offer better tolerability profiles. Specifically, addressing resistance driven by KRAS mutations [10] and exploring alternative therapeutic targets remains crucial.

#### Proposed Solution

Lapatinib is an orally available small molecule tyrosine kinase inhibitor currently approved for use in combination with capecitabine for the treatment of HER2-positive metastatic breast cancer. It reversibly inhibits the intracellular tyrosine kinase domains of both EGFR (ErbB1) and HER2 (ErbB2), thereby blocking downstream signaling cascades, including RAS/RAF/MEK/ERK and PI3K/AKT/mTOR. This inhibition leads to decreased cell proliferation and increased apoptosis.

Repurposing lapatinib for COAD is rationalized by the shared ErbB signaling pathway between breast cancer and a subset of COAD. EGFR is commonly overexpressed in COAD [1], and while HER2 overexpression is less frequent than in breast cancer, it occurs in a clinically relevant subset [3, 17] and is associated with resistance to anti-EGFR therapy [2]. Lapatinib can directly inhibit both EGFR and HER2, potentially disrupting crucial oncogenic signaling [13, 14] including PLCγ [7].

We hypothesize that lapatinib can effectively inhibit ErbB signaling in COAD, leading to decreased cell proliferation, increased apoptosis, and suppression of metastasis. Preclinical studies demonstrate synergistic antitumor activity of lapatinib with HDAC inhibitors in COAD models [6], and lapatinib has also been shown to sensitize COAD cells to TRAIL-induced apoptosis via an off-target mechanism [5]. Studies have also investigated HER2 as a therapeutic target in CRC, especially after failure of anti-EGFR therapy [2, 18]. Although lapatinib as a single agent has shown limited efficacy in unselected CRC populations, this could be attributed to the heterogeneity of COAD and the presence of resistance mechanisms like KRAS mutations. We anticipate that patient stratification based on molecular profiles will identify subgroups that derive greater benefit.

Overall, our goal is: to demonstrate the efficacy of lapatinib in specific molecular subtypes of COAD, potentially in combination with other targeted therapies, to address the unmet need for new treatment options, particularly in patients resistant to standard therapies.

### Specific Aims 1

#### Overarching goal:

To determine the efficacy of lapatinib in inhibiting HER2/EGFR signaling and suppressing cell proliferation in a panel of well-characterized COAD cell lines.

#### Hypothesis:

Lapatinib will inhibit cell proliferation in HER2-amplified/overexpressing and/or EGFR-overexpressing COAD cell lines.

#### Reasoning:

Lapatinib directly inhibits both HER2 and EGFR, key drivers of cell proliferation in a subset of COAD. Inhibition of these receptors should lead to reduced downstream signaling through the RAS/RAF/MEK/ERK and PI3K/AKT/mTOR pathways, ultimately suppressing cell growth [6].

### Specific Aims 2

#### Overarching goal:

To elucidate the impact of lapatinib on apoptosis and key signaling pathways in COAD models.

#### Hypothesis:

Lapatinib will induce apoptosis and modulate key signaling pathways (RAS/RAF/MEK/ERK, PI3K/AKT/mTOR, and PLCγ) in COAD cell lines, especially those with HER2/EGFR alterations.

#### Reasoning:

Inhibition of HER2/EGFR by lapatinib disrupts pro-survival signaling, potentially promoting apoptosis [14]. Additionally, lapatinib can indirectly modulate downstream pathways [4, 7], even demonstrating synergistic effects with other agents [6]. This aim will explore the extent of this modulation in various COAD subtypes.

### Specific Aims 3

#### Overarching goal:

To identify predictive biomarkers for lapatinib response and explore potential combination strategies in COAD.

#### Hypothesis:

A combination of lapatinib with a MEK inhibitor will enhance antitumor activity in KRAS-mutant COAD cell lines compared to lapatinib alone.

#### Reasoning:

KRAS mutations are a known mechanism of resistance to EGFR/HER2 targeted therapies [10]. Combining lapatinib with a MEK inhibitor may overcome this resistance by blocking the downstream MAPK pathway activation, leading to enhanced antitumor efficacy.

#### Pilot Evaluation

A pilot study will be conducted to evaluate the safety and preliminary efficacy of lapatinib in patients with HER2-positive metastatic COAD who have progressed on standard therapy. This open-label, single-arm study will enroll 15-20 patients with confirmed HER2 overexpression/amplification and KRAS wild-type status. Key exclusion criteria will include prior treatment with lapatinib and significant comorbidities. The primary endpoint will be progression-free survival, and secondary endpoints will include overall response rate, duration of response, and safety. Lapatinib's known safety profile from its use in breast cancer will inform the monitoring plan. Expedited regulatory review may be possible due to lapatinib's existing approval.

### Articles

[1] Targeting the EGFR signalling pathway in metastatic colorectal cancer

Summary: Details the importance of EGFR signaling in CRC and how targeting it is a crucial therapeutic strategy.

Relevance: Provides context for lapatinib's action as it targets EGFR.

[2] HER2 as an Emerging Oncotarget for Colorectal Cancer Treatment After Failure of Anti-Epidermal Growth Factor Receptor Therapy

Summary: Discusses HER2 as a target in CRC, especially in the context of anti-EGFR therapy resistance.

Relevance: Directly relevant to lapatinib's mechanism and potential in COAD.

[19] United States Cancer Statistics

Summary: Provides official U.S. cancer incidence and mortality statistics.

Relevance: Source of epidemiological data for colon adenocarcinoma.

#### Expert rating

- 1. Strongly Agree (unmet clinical needs)
- 2. Agree (bridges therapeutic gap)
- 3. Strongly Agree (scientifically rigorous rationale)
- 4. Strongly Agree (integrates prior studies)
- 5. Strongly Agree (avoids over-extrapolation)
- 6. Strongly Agree (clear hypotheses and methods)
- 7. Strongly Agree (clearly stated aims)
- 8. Strongly Agree (path to clinical application)
- 9. Agree (well-defined endpoints)
- 10. Neutral (meaningful pre-clinical experiments)
- 11. Strongly Agree (translational component)
- 12. Strongly Agree (avoids inaccuracies)
- 13. Strongly Agree (evidence-based assumptions)
- 14. Strongly Agree (originality and terminology)
- 15. Agree (clear writing and organization)
````

#### specific-aims/selinexor-colon-cancer.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/specific-aims/selinexor-colon-cancer.md` — 97 lines, sha256 `fdddea2c0d52`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.5.3 "Examples of co-scientist generated Specific Aims with expert evaluation" / Figures A.28-A.29 (lines 1509-1597).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 4.1.2 "Example 2: Selinexor monotherapy for colon cancer" (lines 195-257). NOTE: the Nature SI prose differs slightly
  (e.g. it titles the example "Selinexor monotherapy…" and elsewhere reports 9 raters / avg 6.7 yrs experience vs. the arXiv's
  6 raters / 8 yrs); the per-axis Expert-rating list below is reproduced verbatim from the arXiv report, the canonical source here.
CASE STUDY: Drug repurposing — Specific Aims (colon adenocarcinoma / COAD). ARTIFACT: a Co-Scientist hypothesis reformatted by the
  Meta-review agent into the NIH "Specific Aims Page" format, one of the THREE worked examples the paper presents at A.26-A.31, and one
  of the two (Selinexor, Lapatinib) that carry a full 15-axis "Expert rating" block against the A.5.2 rubric. (Givosiran, A.26-A.27, has
  no rating block and is extracted separately under outputs/drug-repurposing-aml/03-givosiran-specific-aims-nih-format.md.)
VERBATIM extract. The 15 numbered Expert-rating items below map to the A.5.2 rubric (5 "Significance and innovation" + 10 "Rigor and feasibility").
-->

# Drug-repurposing Specific Aims — Selinexor for colon cancer (NIH format, with expert rating)

## Selinexor for colon cancer

#### Disease Description

Colon adenocarcinoma (COAD) is a significant public health concern, with an estimated incidence rate of over 1.9 million new cases and 935,000 deaths globally in 2020. COAD arises from the epithelial lining of the colon and is driven by a complex interplay of genetic mutations (e.g., APC, KRAS, BRAF, TP53) and epigenetic alterations, leading to uncontrolled cell proliferation, impaired apoptosis, and chronic inflammation. These molecular changes disrupt crucial cellular pathways like Wnt/β-catenin signaling, cell cycle control, and DNA damage repair, ultimately driving tumor progression. COAD typically progresses through stages, from localized polyps to invasive tumors with potential for metastasis. Current standard of care involves surgery, chemotherapy, radiation therapy, and targeted therapies, but treatment resistance and recurrence remain major challenges, highlighting the need for new therapeutic approaches.

#### Unmet Need

Current COAD treatments have limitations, including acquired resistance to chemotherapy, significant toxicities, and incomplete responses in advanced disease. Patients often experience diminished quality of life due to treatment side effects and disease burden. High recurrence rates and limited effective treatment options after progression contribute to poor long-term outcomes. This unmet need underscores the urgency for novel therapeutic strategies that can overcome resistance, improve response rates, and minimize toxicity, ultimately extending survival and enhancing quality of life for COAD patients.

#### Proposed Solution

Selinexor, a first-in-class selective inhibitor of nuclear export (SINE), is currently approved for the treatment of multiple myeloma and diffuse large B-cell lymphoma. It specifically targets XPO1 (Exportin 1), a key protein responsible for the nuclear export of tumor suppressor proteins, oncoproteins, and RNA. By binding to XPO1, Selinexor blocks the nuclear export of these molecules, leading to their accumulation in the nucleus and restoration of tumor suppressor function, cell cycle arrest, and apoptosis induction.

Repurposing Selinexor for COAD is rationally supported by its mechanism of action and the molecular characteristics of the disease. Overexpression of XPO1 is common in various cancers, including COAD [1, 2, 6]. Selinexor inhibits XPO1, preventing the nuclear export and restoring the function of key tumor suppressors (p53, RB, FOXO, APC) frequently dysregulated in COAD [2, 3, 4, 5]. Furthermore, Selinexor can suppress constitutively activated NF-κB signaling, a driver of chronic inflammation and tumor progression in COAD, by blocking IκB export and increasing its nuclear accumulation [7, 8]. These mechanisms align with key aspects of COAD pathogenesis and offer opportunities for therapeutic intervention.

We hypothesize that Selinexor will effectively inhibit COAD cell growth and enhance apoptosis by restoring tumor suppressor function and modulating crucial signaling pathways. Selinexor has shown anti-tumor activity in solid tumors in a Phase I trial [3], with observations of nuclear accumulation of tumor suppressor proteins [3, 6]. While not specific to COAD, these findings, coupled with evidence of Selinexor's efficacy in other cancers driven by XPO1 overexpression [3, 6], suggest that a similar mechanism could be effective in COAD. Further supporting our hypothesis, XPO1 overexpression has been linked to NF-κB activation and increased proliferation in COAD [7]. Overall, our goal is: to demonstrate that Selinexor's XPO1 inhibitory activity can effectively target key oncogenic drivers and restore tumor suppressor functions in COAD, ultimately leading to tumor growth inhibition and improved patient outcomes.

### Specific Aims 1

#### Overarching goal:

Determine the in vitro efficacy of Selinexor in inhibiting COAD cell growth and inducing apoptosis.

#### Hypothesis:

Selinexor treatment will significantly reduce the viability and increase apoptosis in a panel of COAD cell lines, including those with varying genetic backgrounds (e.g., APC, KRAS, TP53 mutations).

#### Reasoning:

Selinexor's inhibition of XPO1 leads to nuclear accumulation of tumor suppressors like p53, a key regulator of apoptosis [2, 6]. Restoration of p53 function and suppression of NF-κB, a pro-survival pathway [7, 8], are expected to induce apoptosis in COAD cells. We will evaluate this hypothesis using cell viability and apoptosis assays in diverse COAD cell lines to assess the impact of genetic background on Selinexor's efficacy.

### Specific Aims 2

#### Overarching goal:

Elucidate the mechanisms by which Selinexor inhibits COAD cell growth, focusing on XPO1-mediated restoration of tumor suppressor function.

#### Hypothesis:

Selinexor treatment will increase nuclear accumulation of p53, RB, and FOXO proteins and decrease nuclear export of IκB, leading to cell cycle arrest and decreased NF-κB activity in COAD cells.

#### Reasoning:

Selinexor blocks XPO1, preventing nuclear export of key tumor suppressors (p53, RB, FOXO) [2, 4, 5] and the NF-κB inhibitor IκB [7, 8]. Increased nuclear localization of these proteins should restore their growth regulatory functions, leading to cell cycle arrest and reduced NF-κB-driven proliferation. We will evaluate this hypothesis using immunofluorescence and western blotting to assess protein localization and activity.

### Specific Aims 3

#### Overarching goal:

Characterize the potential synergistic effects of Selinexor in combination with standard-of-care chemotherapies for COAD.

#### Hypothesis:

Combination treatment with Selinexor and 5-fluorouracil (5-FU) will synergistically reduce COAD cell viability compared to either treatment alone.

#### Reasoning:

XPO1 inhibition can sensitize cancer cells to chemotherapy [9]. Combining Selinexor with 5-FU, a common COAD chemotherapy, may enhance cellular stress and improve treatment response. We will test this hypothesis using cell viability assays and investigate the underlying mechanisms of synergy.

#### Pilot Evaluation

A pilot study will evaluate Selinexor's efficacy in a patient-derived xenograft (PDX) model of COAD. The primary objective is to determine the effect of Selinexor on tumor growth. The study will utilize an open-label, single-arm design with escalating Selinexor doses in established COAD PDX models. Inclusion criteria: established COAD PDX models. Exclusion criteria: none. Primary endpoint: tumor volume change. Secondary endpoints: changes in biomarkers (p53, Ki67, NF-κB) within the tumor. Selinexor's established safety profile in other cancers provides a basis for evaluating its safety in this new indication. Potential for expedited review through existing regulatory pathways will be explored.

#### Expert rating

- 1. Strongly Agree (unmet clinical needs)
- 2. Agree (bridges therapeutic gap)
- 3. Strongly Agree (scientifically rigorous rationale)
- 4. Agree (integrates prior studies)
- 5. Agree (avoids over-extrapolation)
- 6. Strongly Agree (clear hypotheses and methods)
- 7. Strongly Agree (clearly stated aims)
- 8. Agree (path to clinical application)
- 9. Agree (well-defined endpoints)
- 10. Agree (meaningful pre-clinical experiments)
- 11. Agree (translational component)
- 12. Strongly Agree (avoids inaccuracies)
- 13. Strongly Agree (evidence-based assumptions)
- 14. Agree (originality and terminology)
- 15. Strongly Agree (clear writing and organization)
````

#### tool-use/alphafold-oct4-protein-design.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/tool-use/alphafold-oct4-protein-design.md` — 39 lines, sha256 `7db4c02573ac`.

````
<!--
SOURCE (canonical, verbatim): references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.6 "An example of tool use in the AI co-scientist with AlphaFold" / Figure A.40 (lines 1956-1964).
  Section-local references cited by the [3]-[7] markers below are reproduced from the A.6 reference list (lines 1970-1974).
PARALLEL SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Supplementary Note 11 "An example of tool use in Co-Scientist with AlphaFold" (lines 1713-1719; Supplementary Fig. 9 caption at line 1769).
CASE STUDY: Tool use / protein design (general-purpose demonstration, not one of the three biomedical wet-lab validations).
ARTIFACT: a qualitative worked example of the AI co-scientist using AlphaFold as a validation tool to assess a proposed OCT4 protein modification. Figure A.40 itself is an image (predicted 3D structures + metrics); only its caption is extractable as text.
VERBATIM extract.
>>> VERSION DIVERGENCE (per the draft's de-dup rule, the arXiv body is kept verbatim and the divergence is noted, not silently reconciled):
    - arXiv (this file): "independently validated the modification using ESM-2 [6] and RoseTTAFold [7]. ESM-2 predicted an increased
      log-likelihood ratio and a similar predicted local distance difference test (pLDDT), and RoseTTAFold predicted similar
      confidence score (GDT) ...".
    - Nature SI Note 11: adds a THIRD validator, ESMFold — "validated the modification using ESM-2, ESMFold, and RoseTTAFold.
      ESM-2 predicted an increased log-likelihood ratio, ESMFold predicted a similar pLDDT, and RoseTTAFold predicted a similar GDT ...".
    The arXiv attributes the "similar pLDDT" to ESM-2; the SI attributes it to ESMFold. Numbers/tools not merged here.
-->

# AI co-scientist tool use with AlphaFold — OCT4 protein-design example (§A.6)

## A.6 An example of tool use in the AI co-scientist with AlphaFold

The AI co-scientist is a general purpose system broadly applicable across different areas of science and medicine. To better understand the capabilities and limitations of the system, we task it with the goal of suggesting protein sequences with specific properties. Determining the correct primary amino acid sequence with the desired properties is an essential part of protein engineering. While LLM-based systems can predict protein properties and suggest modifications [3], they can sometimes generate incorrect sequences (i.e., hallucinations). To address this, we integrate AlphaFold [4], a specialized AI system for predicting protein 3D structure, into our co-scientist. AlphaFold acts as a validation tool, evaluating the structural plausibility of sequences proposed by the co-scientist and provides feedback. This increases the reliability of the sequence design optimization process, which can be further validated with wet laboratory experiments. The approach to integrate tools highlights how specialized AI models can work in collaboration with more general AI systems like the AI co-scientist, facilitating the solution of complex challenges like protein design.

As an illustrative example, we used AlphaFold to assess a co-scientist's proposed modification to the OCT4 (octamer-binding transcription factor 4) protein (Appendix Figure A.40), one of the four Yamanaka factors [5], to increase binding affinity of its DNA binding domain. The co-scientist suggested adding a mechano-sensitive loop to the POU domain (a family of eukaryotic transcription factors) and a dynamic phosphorylation site outside of it. The co-scientist first verified the proposed sequence against the UniProt database via websearch. AlphaFold then predicted the 3D structure of the modified protein, suggesting that the modifications maintained structural stability. These predictions were used to refine the co-scientist's hypothesis, allowing it to improve its protein sequence design in subsequent iterations. We also independently validated the modification using ESM-2 [6] and RoseTTAFold [7]. ESM-2 predicted an increased log-likelihood ratio and a similar predicted local distance difference test (pLDDT), and RoseTTAFold predicted similar confidence score (GDT), compared to the original sequence. The insertion and modification did not seem to disrupt SOX2 and OCT4 interactions, indicated by the similar pLDDT scores between the original and modified OCT4 sequences. However, this example is for demonstration purposes only. Further in silico analysis (e.g., predicting binding affinity and off-target effects), and thorough laboratory validation are necessary to confirm that the proposed modifications actually improve the complex roles of OCT4 binding, while maintaining SOX2 interaction integrity, during pluripotency.

**Figure A.40** | AlphaFold predicted protein 3D structure and metrics for original OCT4 and AI co-scientist suggested modifications. (left panel) original OCT4 sequence with SOX2 and DNA binding (right panel) modified OCT4 sequence with SOX2 and DNA binding. The left 3D structure in each panel is the POU domain of the corresponding OCT4 sequence. The predicted template modeling (pTM) score, the interface predicted template modeling (ipTM), and predicted local distance difference test (pLDDT) are derived from the AlphaFold outputs.

Combining AlphaFold with the co-scientist framework offers a powerful approach for both improving existing proteins and designing entirely new ones. This integrated system allows researchers to iteratively optimize protein sequences for enhanced properties (e.g., stability, binding affinity, or catalytic activity) or putatively to create proteins with novel functions. It enables exploration of protein design while ensuring structural feasibility. Future work will focus on experimentally validating these capabilities and applying them to targeted protein design efforts as well as expansion to integration of other specialized AI tools with the co-scientist.

---

### Section-local references cited above (verbatim, from §A.6 reference list)

- [3] Wang, Y., He, J., Du, Y., Chen, X., Li, J. C., Liu, L.-P., Xu, X. & Hassoun, S. Large Language Model is Secretly a Protein Sequence Optimizer. arXiv preprint arXiv:2501.09274 (2025).
- [4] Jumper, J., Evans, R., Pritzel, A., Green, T., Figurnov, M., Ronneberger, O., Tunyasuvunakool, K., Bates, R., Žídek, A., Potapenko, A., et al. Highly accurate protein structure prediction with AlphaFold. Nature 596, 583–589 (2021).
- [5] Takahashi, K., Tanabe, K., Ohnuki, M., Narita, M., Ichisaka, T., Tomoda, K. & Yamanaka, S. Induction of pluripotent stem cells from adult human fibroblasts by defined factors. cell 131, 861–872 (2007).
- [6] Lin, Z., Akin, H., Rao, R., Hie, B., Zhu, Z., Lu, W., Smetanin, N., dos Santos Costa, A., Fazel-Zarandi, M., Sercu, T., Candido, S., et al. Language models of protein sequences at the scale of evolution enable accurate structure prediction. bioRxiv (2022).
- [7] Baek, M., DiMaio, F., Anishchenko, I., Dauparas, J., Ovchinnikov, S., Lee, G. R., Wang, J., Cong, Q., Kinch, L. N., Schaeffer, R. D., et al. Accurate prediction of protein structures and interactions using a three-track neural network. Science 373, 871–876 (2021).
````

#### validated-outputs/kira6-critiques-and-references.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/validated-outputs/kira6-critiques-and-references.md` — 70 lines, sha256 `22a55d45ec3a`.

````
<!-- SOURCE: references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Note 6 "Detailed Co-Scientist output for a validated AML repurposing candidate" -> "KIRA6 for AML" · lines 816-864 -->
<!--
COMPLETES the KIRA6 output. The sibling file `01-kira6-detailed-output-validated.md` reproduces Note 6
verbatim only through the Novelty review's final "Answer: 3" (source line 814). The supplement's KIRA6
section continues past that point with (a) the numbered reference list [1]-[9] that the captured KIRA6
prose already cites, and (b) a distinct titled "Critiques" subsection summarizing the negative critiques.
Both are reproduced here VERBATIM so nothing from Note 6 is dropped.

This file was added rather than appended to `01-kira6-...` because that file is outside this pass's edit
scope. The two together constitute the complete KIRA6 Note 6 output.

VERBATIM-FIDELITY NOTE: prose and the reference list are reproduced word-for-word. Unlike the inline-link
omission convention used elsewhere in this draft, the standalone reference bibliography [1]-[9] IS retained
here in full (including its URLs) because it is the resolution of the [1]/[5]/[6] etc. citation markers that
already appear in the captured KIRA6 body. The source's "●" bullet (first Critiques item) is kept as-is.
-->

# KIRA6 for AML — references and Critiques (completing Note 6)

## References (Novelty review article list)

[1] Targeting the IRE1α-XBP1s Pathway to Enhance Venetoclax Effectiveness in AML | Blood | American Society of Hematology

(https://ashpublications.org/blood/article/144/Supplement%201/4144/533082/Targeting-the-IRE 1-XBP1s-Pathway-toEnhance)

[2] FLT3 inhibitors in acute myeloid leukemia: ten frequently asked questions | Leukemia (https://www.nature.com/articles/s41375-019-0694-3)

[3] Inhibition of FLT3-ITD Kinase in Acute Myeloid Leukemia by New

Imidazo[1,2-b]pyridazine Derivatives Identified by Scaffold

Hopping | Journal of Medicinal Chemistry

(https://pubs.acs.org/doi/10.1021/acs.jmedchem.3c00575)

[4] Repurposing approved drugs on the pathway to novel therapies - PMC

(https://pmc.ncbi.nlm.nih.gov/articles/PMC7018532/)

[5] The Unfolded Protein Response: A Novel Therapeutic Target in Acute Leukemias - PMC (https://pmc.ncbi.nlm.nih.gov/articles/PMC7072709/)

[6] Drugging the unfolded protein response in acute leukemias | Journal of Hematology & Oncology | Full Text

(https://jhoonline.biomedcentral.com/articles/10.1186/s13045-015-0184-7)

[7] Selective degradation of mutant FMS-like tyrosine kinase-3 requires BIM-dependent depletion of heat shock proteins |

Leukemia (https://www.nature.com/articles/s41375-024-02405-5)

[8] Pharmacology and Toxicology Testing: IC50 for Tumor Cell Lines - Altogen Labs (https://altogenlabs.com/pre-clinicalresearch-services/pharmacology-and-toxicology-testing-ic50 -for-tumor-cell-lines/)

[9] Targeting Mitochondrial Structure Sensitizes Acute Myeloid Leukemia to Venetoclax Treatment | Cancer Discovery

| American Association for Cancer Research

(https://aacrjournals.org/cancerdiscovery/article/9/7/890/41983/TargetingMitochondrial-Structur e-Sensitizes-Acute)

## Critiques

Here's a summary of the negative critiques from the reviews:

- Limited safety data: The biggest concern is the lack of human safety data for KIRA6, requiring thorough preclinical toxicity studies. The drug's safety profile is currently unknown and needs experimental validation.
- Limited scope of cell line testing: Testing primarily focuses on MOLM-13. Expanding to other AML cell lines (with different FLT3 mutations and other genetic backgrounds) and primary patient samples is necessary.
- Limited comparison to other drugs: The idea would benefit from comparing KIRA6 to other IRE1α inhibitors or similar drugs to justify its selection and benchmark efficacy/selectivity. Minimal data exists regarding KIRA6 compared to other drugs.
- Lack of pre-clinical and clinical data: While proposed, in vivo and toxicity data are currently lacking for KIRA6, despite the comprehensive experimental plan.
- Assumptions requiring validation: Several assumptions about KIRA6's selectivity for AML cells over healthy cells, synergy with other drugs, impact on drug resistance mechanisms, and the suggested IC50 concentration range need experimental validation.
- Limited detail in some areas: The rationale for the specific IC50 range could be stronger. The exploration of resistance mechanisms and the details of synergy studies could also be more in-depth. More detail on how KIRA6 impacts MYC, NF-κB and inflammatory pathways is needed. The connection between UPR activation and a lower incidence of FLT3 mutations needs further investigation.
- Potential for resistance: While the idea aims to overcome resistance, there's still a need to investigate how KIRA6 itself might contribute to new resistance mechanisms over time.

Although the idea is considered plausible, novel, and promising, these weaknesses need to be addressed through further research and experimentation.
````

#### validated-outputs/kira6-detailed-output-validated.md

Source: `references/core/google-co-scientist/research/extracted-artifacts/outputs/validated-outputs/kira6-detailed-output-validated.md` — 220 lines, sha256 `b5a22b590874`.

````
<!--
SOURCE (verbatim): references/core/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 6 "Detailed Co-Scientist output for a validated AML repurposing candidate" -> "KIRA6 for AML" (lines 592-821).
CASE STUDY: Drug repurposing for AML (the Nature 2026 paper's primary wet-lab-validated result).
ARTIFACT: a COMPLETE single Co-Scientist proposal -- hypothesis + mechanism + experimental plan + the system's own Review and Novelty review (with self-assigned scores "Answer: 4" / "Answer: 3").
NOTE: Unlike the ALS example, this is a REAL validated candidate. Per the Nature paper, the IRE1alpha inhibitor KIRA6 showed
      in-vitro inhibition of AML cell viability (e.g. IC50 ~10 nM in KG-1a vs ~180 nM in non-AML TK6 control). The system rated
      its own novelty as "moderate", correctly noting IRE1alpha had been targeted in AML before but not with KIRA6.
VERBATIM extract: the PROSE is verbatim (word-for-word; mid-sentence PDF line-wraps in the source were joined into running
  sentences, and inline citation links omitted). Markdown HEADING LEVELS were normalized for readability (some source headings
  were '#'/'###'; rendered here as '###'/'####' to nest under this file's H1). The section's "●" bullets are reproduced as in source.
-->

# KIRA6 for AML — detailed (validated) Co-Scientist output

### Summary

This proposal outlines repurposing KIRA6, an IRE1α inhibitor, for treating acute myeloid leukemia (AML), particularly FLT3-ITD positive AML known for high relapse rates. The hypothesis is that KIRA6 will disrupt protein homeostasis and induce ER stress in AML cells, synergizing with existing therapies and overcoming resistance. The proposal details KIRA6's mechanism, impacting pathways like the UPR and apoptosis, and suggests a comprehensive experimental plan including in vitro and in vivo studies to validate its efficacy and safety, including combination therapy with existing AML drugs. This approach aims to provide a novel, effective treatment strategy for AML patients, particularly those with the challenging FLT3-ITD mutation and other drug resistance phenotypes.

### Hypothesis

#### Introduction

Acute myeloid leukemia (AML) remains a formidable hematological malignancy characterized by the rapid proliferation of immature myeloid blasts in the bone marrow and peripheral blood. Despite advancements in therapeutic strategies, including targeted therapies and hematopoietic stem cell transplantation, a significant proportion of patients experience relapse or develop resistance to treatment, underscoring the urgent need for new therapeutic interventions. The heterogeneous nature of AML, with diverse genetic and molecular aberrations driving disease progression, necessitates the exploration of novel therapeutic targets and the rational design of combination therapies to overcome treatment resistance and improve long-term survival outcomes. Drug repurposing, which involves identifying new uses for existing drugs, offers a cost-effective and efficient strategy to accelerate the development of novel AML treatments by leveraging established safety profiles and pharmacokinetic data. This approach can significantly reduce development time and costs, facilitating the rapid translation of promising agents to clinical trials.

#### Recent findings and related research

Recent research has significantly advanced our understanding of the complex molecular landscape of AML, highlighting the critical roles of various genetic mutations and signaling pathways in leukemogenesis. Recurrent mutations in genes such as FLT3, NPM1, IDH1/2, and TP53 are frequently observed in AML and have been implicated in disease initiation, progression, and treatment resistance. The FLT3-ITD mutation, a particularly challenging subtype, is associated with poor prognosis and a higher risk of relapse, emphasizing the need for effective therapies that target this specific mutation or overcome its downstream effects. Targeted therapies, such as FLT3 inhibitors (midostaurin, gilteritinib), IDH inhibitors (enasidenib, ivosidenib), and the BCL-2 inhibitor venetoclax, have demonstrated clinical efficacy in specific AML subtypes; however, the emergence of drug resistance and the lack of effective treatments for high-risk patients remain critical challenges.

Drug repurposing has yielded several promising candidates for AML treatment, including:

- Arsenic trioxide and all-trans retinoic acid (ATRA): Established treatments for acute promyelocytic leukemia (APL), these have also shown potential in combination therapy for non-APL AML.
- Histone deacetylase (HDAC) inhibitors: Vorinostat and panobinostat have shown modest activity in AML, particularly in combination with other agents, but are known to be poorly tolerated and have limited efficacy as single agents.
- Proteasome inhibitors: Bortezomib and carfilzomib have been explored in combination regimens in AML, especially to overcome resistance, though with limited success.
- Metabolic inhibitors: Targeting glutamine metabolism and other metabolic pathways has shown promise in preclinical studies, though with limited translation due to toxicity and poor absorption.
- Homoharringtonine (HHT): As noted, HHT, a protein synthesis inhibitor, has been approved for CML and has shown promise in AML, although its mechanism of action and specific impacts on resistance mechanisms need to be further explored.
- Immunomodulatory drugs: Thalidomide and lenalidomide have been explored in combination therapies to target the tumor microenvironment and enhance immune responses, though with limited efficacy in AML.
- Kinase inhibitors: Beyond FLT3, new kinase inhibitors that target other pathways are being explored in combination settings to overcome resistance.

Despite these findings, there remains a significant unmet need for novel, effective therapies that can overcome drug resistance, target novel pathways, and improve long-term survival for AML patients.

#### Areas worth exploring

Several areas hold significant potential for identifying novel or repurposed drugs for AML treatment:

- Targeting non-canonical signaling pathways: Explore drugs that target pathways beyond the well-established ones, such as those involved in inflammatory signaling, protein degradation, and DNA damage repair. The interplay between the AML cell and its microenvironment, including inflammatory cytokines and immune cells, remains an area of active investigation and a promising target for therapeutic intervention.
- Targeting RNA processing and translation: Aberrant RNA processing and translation are significant drivers of protein expression in cancer, and are potential targets for novel therapies. Targeting ribosome function, mRNA splicing, and RNA modifications can disrupt the production of key proteins required for cell survival and proliferation.
- Modulating immunometabolism: Cancer cells exhibit altered metabolic demands that influence the immune response, and targeting metabolic pathways that influence immune activation and suppression could enhance anti-leukemic immune responses. This also includes the metabolic dependencies of the myeloid microenvironment, which is critical for disease progression and resistance.
- Leveraging high-throughput screening (HTS) and computational biology: Combine in vitro or ex vivo screening of approved drugs with computational drug repurposing methods, particularly those that integrate multi-omics data, to identify novel drug candidates and potential synergistic drug combinations.
- Focus on drug combinations: Rational drug combinations that address both active malignancy and underlying resistance mechanisms, and can achieve effective treatment regimens at lower concentrations in combination, will have better safety, efficacy and overcome existing resistance. This should include a focus on sequential drug administration and drug scheduling.
- RNA-based therapies: Direct targeting of mRNAs coding for leukemia-driving proteins can be a very impactful strategy that also offers the chance to overcome resistance, for example by interfering with compensatory pathways. This includes RNA interference (RNAi), antisense oligonucleotides (ASOs), and mRNA-based therapies.
- Targeting protein homeostasis: Disrupting the protein homeostasis network, including protein folding, degradation (through ubiquitin-proteasome and autophagy pathways), and quality control mechanisms, can induce cellular stress and apoptosis in AML cells.

## Detailed novel likely correct idea: repurposing the IRE1α inhibitor KIRA6 for AML treatment

**Goal:** Repurpose KIRA6, an IRE1α inhibitor, for AML treatment, specifically targeting the MOLM-13 cell line with FLT3-ITD, with a focus on overcoming resistance mechanisms and enhancing combination therapy efficacy.

**Idea:** KIRA6, by inhibiting IRE1α, a key regulator of the unfolded protein response (UPR), can disrupt protein homeostasis and induce ER stress in AML cells, particularly in cells exhibiting high metabolic demand and increased protein synthesis, such as FLT3-ITD positive cells. This disruption can synergize with other therapies, including FLT3 inhibitors and chemotherapeutics, to overcome resistance and improve therapeutic efficacy. KIRA6 will also suppress chronic inflammatory pathways known to promote cell survival in AML cells.

### Molecular mechanism of action

- Inhibition of IRE1α: KIRA6 is a selective inhibitor of IRE1α, a transmembrane protein in the endoplasmic reticulum (ER) that acts as a key sensor and transducer of ER stress. IRE1α activation initiates the unfolded protein response (UPR) pathway, which is a cellular stress response aimed at restoring protein homeostasis in the ER. Under conditions of increased protein synthesis or misfolded proteins, IRE1α is activated, leading to the splicing of XBP1 mRNA and the subsequent activation of downstream transcriptional targets involved in protein folding, trafficking, and degradation.
- Disruption of ER homeostasis: By inhibiting IRE1α, KIRA6 blocks the adaptive arm of the UPR, preventing the resolution of ER stress and leading to the accumulation of unfolded and misfolded proteins. This disruption creates a protein folding crisis, inducing ER stress and initiating apoptotic pathways. This effect is potentiated in rapidly proliferating AML cells, which have higher metabolic demands and are more sensitive to ER stress.

#### ● Downstream effects:

- The accumulation of misfolded proteins leads to the activation of the PERK and ATF6 arms of the UPR, which further contribute to ER stress and apoptosis.
- Inhibition of IRE1α disrupts the transcriptional program regulated by XBP1, impairing the production of proteins involved in ER homeostasis and cell survival.
- The resulting ER stress induces the activation of the integrated stress response (ISR), leading to the translational suppression of many transcripts and increased apoptotic activity.
- KIRA6 can indirectly inhibit the NF-κB pathway by reducing ER stress and inflammatory cytokine production, reducing cell survival, proliferation and resistance.
- KIRA6 may directly reduce levels of inflammatory cytokines such as IL-1, in turn reducing secondary activation of inflammatory signalling cascades and reduce activation of IRAK1 in the process.
- Impact on FLT3-ITD: FLT3-ITD mutations lead to increased cell proliferation and metabolic demand and stress. KIRA6 can target this through disruption of the UPR, leading to a higher impact on FLT3-ITD cells. FLT3-ITD cells are under high levels of stress already, and require high levels of protein synthesis to maintain viability. By targeting basal or activated IRE1α, KIRA6 can induce significantly more cell death in FLT3-ITD cells than their wild-type counterparts.
- Impact on key dysregulated pathways:
  - MYC: MYC protein levels are directly tied to mRNA translation and are necessary for cell survival and resistance in many cases, including leukemia. Targeting the UPR and downstream translation with KIRA6 directly decreases MYC expression and survival. This also has downstream anti-inflammatory benefits.
  - NF-κB signaling: KIRA6 can reduce NF-κB activity, a key driver of cell survival, proliferation, and resistance, by reducing ER stress and inflammatory cytokine production.
  - MCL-1 and other anti-apoptotic proteins: KIRA6 will reduce the production of short-lived survival proteins, leading to rapid apoptosis by diminishing their production, particularly MCL-1 and other similar proteins, which are involved in anti-apoptotic effects in AML cells, and are known drug resistant mechanisms.
  - Targeting multiple AML resistance mechanisms: KIRA6, by disrupting protein homeostasis, has the capacity to overcome resistance across a wide panel of mechanisms, including through reduced efflux pump protein levels, and reduced repair mechanisms.
  - Synergistic effects: KIRA6 can synergize with FLT3 inhibitors by increasing ER stress, making cells more sensitive to FLT3 inhibition. It can also enhance the activity of chemotherapeutic drugs by disrupting DNA repair pathways.

### Impacted pathways

- Unfolded protein response (UPR): Directly impacted through inhibition of IRE1α.
- Apoptosis: Primarily through the intrinsic pathways, and disruption of anti-apoptotic proteins, and an increase in ER stress, alongside an increase of pro-apoptotic proteins through the integrated stress response.
- Cell cycle: Perturbation of cell cycle progression through reduced levels of cell-cycle proteins.
- NF-κB signaling: KIRA6 can reduce NF-κB activity which reduces inflammation and promotes cell survival, and drug resistance.
- MYC-related pathways: Suppression of MYC and other related oncogene protein levels.
- Inflammatory pathways: By suppressing cytokines, most notably IL-1, KIRA6 can suppress activation of IRAK1 and reduce chronic inflammation that promotes cell survival in addition to killing cancer cells.

### Effect on AML (MOLM-13) cell proliferation inhibition

- KIRA6 selectively inhibits proliferation of MOLM-13 cells, and also AML cells with other mutations that render them drug resistant.
- IRE1α inhibition leads to the activation of apoptotic pathways and reduced cell proliferation and clonal survival.
- Suppression of MYC levels, NF-κB, MCL-1 and other cell survival pathways will reduce cell survival and promote apoptosis, which should be enhanced in FLT3-ITD AML due to their high proliferation rates and increased sensitivity to metabolic/translational stress in comparison to normal myeloid cells.
- In addition to having a direct effect on proliferation, a reduction in inflammatory signalling (IL-1 and IRAK1) can potentiate activity of other drugs.
- KIRA6 treatment results in a dose-dependent reduction in MOLM-13 cell viability.
- KIRA6 leads to a buildup of ER stress and activation of the ISR, all which enhance its effectiveness as a targeted drug.
- When combined with FLT3 inhibitors or chemotherapeutic drugs, KIRA6 is expected to show additional impacts at lower overall drug concentrations (lower levels of both KIRA6 or the alternative drugs in the combination will be required for the same levels of cell death, or greater cell death will be seen at the standard doses used presently in the clinic). This is very important given the high levels of both drug toxicity that are associated with all AML treatments, and the need to reduce those toxicities.

### IC50 assay concentrations

Based on published data for KIRA6 in other cancer cell models and its known mechanism of action, a reasonable starting concentration range for an IC50 assay in MOLM-13 cells would be 100 nM to 10 µM.

- Rationale: This range spans the concentrations that have shown activity in various cell types while being within a pharmacologically achievable range. Prior in vitro studies have shown activity in low micromolar concentrations.
- Specific concentrations: 100 nM, 250 nM, 500 nM, 1 µM, 2.5 µM, 5 µM, 7.5 µM, 10 µM.
- Assay method: Cell viability assays (e.g., MTT, CellTiter-Glo) to determine IC50 values after KIRA6 exposure for 48-72 hours.
- Controls: Appropriate vehicle controls (DMSO) or medium-only controls should be included.
- Positive control: Use a known FLT3 inhibitor, such as gilteritinib, at its reported IC50 in MOLM-13 cells for normalization of assay variability and comparison.
- Combination studies: The combination of a FLT3 inhibitor at a single set concentration, plus a matrix of KIRA6 concentrations at several ratios will be evaluated using the viability assays as a baseline. Additional confirmation using apoptotic assays and cell cycle arrest should be done for any combination that shows better results than single-agent drug effects.

### Safety and toxicity

- Limited safety data: KIRA6 is a relatively new compound and has limited safety data in humans, as it has not gone through clinical trials. Initial in vitro and in vivo studies in other disease settings (mostly cancer) suggest that it is generally well-tolerated. However, thorough preclinical toxicity studies are essential before advancing to human trials.
- Potential toxicity: Given the mechanism of action, potential toxicities include ER stress-related effects on normal tissues, particularly those with high protein synthesis demands (e.g., liver, pancreas). However, since AML cells are under high levels of stress, and have high metabolic demand, they are expected to be disproportionately impacted by this drug, which should reduce systemic toxicity.
- Repurposing advantage: Because KIRA6 has established in vitro activity, and has known pharmacology, it is significantly less risky than a compound that would have to have all of its safety profiles evaluated before human trials.
- Combination therapy impact: Because KIRA6 can be paired with existing therapies, it may be possible to reduce the overall dose of both agents to minimize side-effects and overall toxicity, while enhancing therapeutic efficacy. This should be tested rigorously in vitro through all of the combination studies before any movement into clinical human or animal trials to make sure that the benefit is higher than the risk.

### Testable hypothesis

KIRA6, by inhibiting IRE1α, will selectively inhibit the proliferation of AML cells, especially FLT3-ITD positive cells, by disrupting protein homeostasis and inducing ER stress. The increase in stress and reduced output of essential cell maintenance proteins will trigger apoptotic pathways, leading to cell death, particularly in highly proliferative settings. KIRA6 will potentiate the activity of existing AML therapies such as FLT3 inhibitors and chemotherapeutics. The drug will also have a broader impact on resistance mechanisms.

### Experimental plan

- IC50 determination in MOLM-13: Determine IC50 values in MOLM-13 cells using viability assays with KIRA6 concentrations ranging from 100 nM to 10 µM.
- ER stress marker measurement: Measure levels of key ER stress markers (e.g., BiP/GRP78, CHOP) using Western blotting and ELISA after KIRA6 treatment to confirm the impact on ER homeostasis.
- IRE1α activity: Measure XBP1 splicing using RT-PCR or other assays to confirm KIRA6's impact on IRE1α activity.
- Apoptosis assays: Evaluate apoptosis by Annexin V/PI staining, caspase activity assays, and Western blot analysis of apoptotic markers (cleaved PARP, cleaved caspase-3 levels) in KIRA6-treated MOLM-13 cells.
- Western blots: Analyze key pathway proteins: including MYC, NF-κB, MCL-1, FLT3, AKT/mTOR, and key components of the canonical inflammatory pathways (including IL-1, IL-6, TNF-alpha, IRAK1/4, MyD88), and markers of endoplasmic reticulum (ER) stress in AML cells treated with KIRA6.
- ISR markers measurement: Evaluate the induction of the Integrated Stress Response using assays measuring levels of phospho-eIF2α, ATF4, and CHOP.
- Combination studies: Evaluate the combination of KIRA6 with FLT3 inhibitors like gilteritinib, with chemotherapeutics (cytarabine, daunorubicin) or with venetoclax in MOLM-13 cells using combination matrix studies. This will establish if there is synergistic activity and enable evaluation of lower doses of each drug. Repeat these on additional cell lines with and without FLT3 mutations to confirm consistent synergistic enhancement.
- Cell cycle analysis: Measure cell cycle arrest using DNA staining (propidium iodide) by flow cytometry.
- RNA stress markers studies: Evaluate markers of RNA stress to assess damaged mRNA levels and ER Stress markers to determine cellular stress induced by the drug.
- Efflux pump activity: Measure the activity of key drug efflux pumps (e.g., ABCB1, ABCG2) using specific inhibitors and substrates to evaluate KIRA6's impact on drug resistance mechanisms.
- Expansion to other cell lines: Repeat the above assays on multiple AML cell lines, with both FLT3-ITD and wild-type cells, and lines representing other AML mutations or drug resistance phenotypes. Also evaluate primary AML patient cells in co-culture with stroma and alone with comparable controls, including primary non-leukemic bone marrow derived cells for measuring minimal activity in normal myeloid cells. This should allow for verification of the generalizability of KIRA6.
- In vivo xenograft studies: Evaluate the efficacy and safety of KIRA6 in mouse xenograft models using MOLM-13 cells or other cell lines to assess its overall treatment value and toxicities.
- Pharmacokinetics studies: Evaluate absorption, distribution, metabolism, and excretion of KIRA6 in animals to enable rational dose selection in future trials.

### Conclusion

Repurposing KIRA6, an IRE1α inhibitor, for AML treatment, with a focus on FLT3-ITD positive cells and overcoming resistance mechanisms, represents a promising novel approach. KIRA6's ability to disrupt protein homeostasis, induce ER stress, synergize with existing AML drugs, and potentially overcome resistance mechanisms makes it an excellent drug candidate for testing. The comprehensive experimental plan proposed here offers a thorough framework for validating the potential of KIRA6 in AML and allows for a better way to select drugs for clinical testing by first performing a rigorous scientific evaluation in vitro using a multi-faceted approach. KIRA6 could translate into a new and effective strategy for AML patients, particularly those with the challenging FLT3-ITD mutation and other resistance phenotypes. Due to its mode of action on the UPR, it also has the potential to target underlying resistance mechanisms to existing therapies.

The focus on resistance mechanisms, a more diverse set of cell lines and primary cells, a well-rationalized combination approach, and a specific mechanism of action, all address the feedback from the previous version and provide a strong and detailed rationale for this drug repurposing strategy. The expanded experimental plan provides a thorough framework for assessing the efficacy, selectivity, and safety of KIRA6 in AML.

### Review

#### Relevant article abstracts

- 1: Discusses targeting the IRE1α-XBP1s pathway in AML, directly relevant to the proposed mechanism of KIRA6.
- 5: Reviews the UPR as a therapeutic target in acute leukemias, providing context and supporting the rationale for targeting IRE1α.
- 6: Focuses on selective degradation of FLT3-ITD, offering insights into targeting specific forms of the mutated protein, aligning with the idea's focus on targeting ER-bound FLT3-ITD.
- 7: Offers the background on known pharmacology and toxicological studies for IC50 determination of drug candidates in tumor cells.
- 9: Discusses sensitizing AML to venetoclax treatment, highlighting the potential for combination therapy approaches, relevant to the idea's suggested synergistic effects with other AML drugs.

#### Assumptions

- KIRA6 effectively inhibits IRE1α in AML cells, particularly MOLM-13 cells.
- IRE1α inhibition leads to significant disruption of protein homeostasis and induction of ER stress in AML cells.
- The increased ER stress induced by KIRA6 selectively targets AML cells over healthy cells.
- KIRA6 synergizes with FLT3 inhibitors and chemotherapeutic agents to enhance AML cell death.
- The proposed IC50 concentration range (100 nM to 10 µM) is appropriate for testing in MOLM-13 cells.
- KIRA6 has a manageable safety profile and tolerable toxicity in preclinical models.
- KIRA6 can inhibit the production of short-lived proteins, like MYC and MCL-1, and reduce inflammatory signaling.

#### Reasoning about assumptions

- Plausible: [1] and [5] support the notion of targeting IRE1α in AML. While no direct information shows if KIRA6 effective inhibits IRE1α in AML MOLM 3 cells, it likely works as an IRE1α inhibitor like in other cell types. Needs experimental validation.
- Plausible: This is a core function of the UPR pathway in which IRE1α inhibition, based on the literature [5], should induce this cascade of events causing stress response leading to cell death if prolonged and severe.
- Plausible, but requires careful investigation: AML cells, particularly those with FLT3-ITD, have higher protein synthesis rates and are inherently more sensitive to ER stress. While this is not demonstrated in the literature, the rationale behind targeting ER stress response in leukemia is that tumor cells, particularly with FLT3-ITD, are expected to be more reliant on these processes and therefore may be more susceptible, but this assumption needs further evaluation.
- Plausible, but requires testing: The rationale for synergy is based on the proposed mechanism and general principles of targeting multiple pathways in cancer. [9] offers a related example of synergy with venetoclax, a drug also being tested in FLT3-ITD AML. This hypothesis needs further in vitro testing to be demonstrated.
- Plausible: The suggested range is based on literature and seems reasonable as a starting point. This needs to be empirically confirmed in an IC-50 assay. The provided range in the idea is a well justified assumption that can be verified during the IC-50 viability assays where a broader range of concentrations would capture the optimal values.
- Unknown: This is a vital assumption requiring thorough preclinical testing. [7] has information about pharmacology and toxicity, which provides context. Currently, limited safety data exists for KIRA6 so the drug safety profile is unknown and needs experiments to verify if the drug is safe enough.
- Plausible: IRE1α inhibition and ER stress induction can trigger downstream effects that impact protein translation and inflammatory responses based on the mechanism described in the UPR [5]. [1] suggests that IRE1α impacts venetoclax efficacy. While this is not demonstrated in the literature for KIRA6 in AML, this remains an experimentally verifiable assumption.

#### Improvements to the idea

- Broader cell line testing: The idea primarily focuses on MOLM-13. Expanding to other AML cell lines, including those with different FLT3 mutations and other genetic backgrounds, would strengthen the proposal. This would require additional experiments as well.
- Deeper exploration of resistance mechanisms: While mentioned, the idea could benefit from a more detailed analysis of how KIRA6 addresses specific resistance mechanisms in AML. The idea can also benefit from additional experiments regarding resistance mechanism impacts.
- Investigate drug resistance: There is minimal data regarding KIRA6 impacting drug efflux pumps and other drug resistance mechanisms. It would be beneficial to investigate how impacting the UPR could impact drug resistant cells, which are a major reason for treatment failure in AML.
- Detailed comparison to other IRE1α inhibitors: If there are other IRE1α inhibitors, comparing and contrasting KIRA6 with them and justifying the reasons for choosing this particular drug would add to the idea's strength.

#### Reasoning about correctness and testing

● The idea is plausible and well-reasoned based on known mechanisms of IRE1α and the UPR in cancer. However, key assumptions about selectivity and synergy require experimental validation. The proposed experimental plan is comprehensive and addresses the key questions.
- The idea is novel in its application of KIRA6 to AML, particularly in the context of FLT3-ITD. The focus on combination therapy and overcoming resistance is also promising.
- It is recommended to test this idea due to its plausibility, novelty, and potential clinical significance. While there are uncertainties regarding safety and efficacy, the potential benefits warrant further investigation.
- **Answer: 4**

#### Novelty review

- Targeting the IRE1α-XBP1s pathway to enhance venetoclax effectiveness in AML [1]: This abstract directly relates to the idea by exploring the IRE1α pathway in AML, although in combination with venetoclax, not as a monotherapy or in combination with FLT3 inhibitors.
- The unfolded protein response: A novel therapeutic target in acute leukemias [5]: This review discusses the UPR as a target in acute leukemias, providing a broader context for the idea's focus on IRE1α.
- Selective degradation of mutant FMS-like tyrosine kinase-3 requires BIM-dependent depletion of heat shock proteins [6]: This abstract explores the mechanisms of FLT3 degradation and its connection to BIM and heat shock proteins, relevant to the idea's focus on FLT3-ITD positive AML.

#### Already explored aspects

- Targeting the UPR in AML: The idea of targeting the unfolded protein response (UPR) in AML is not entirely novel. Abstract [5] discusses the UPR as a therapeutic target in acute leukemias, including AML. Abstract [1] specifically explores targeting IRE1α in combination with venetoclax, suggesting existing interest in this pathway for AML. However, the use of KIRA6 as a single agent or in combination with FLT3 inhibitors appears less explored.
- FLT3 inhibitors in AML: Targeting FLT3 in AML with tyrosine kinase inhibitors is a well-established approach, with multiple approved drugs. Abstracts [2, 3] focus on FLT3 inhibitors, highlighting the importance of this target but also the challenges of resistance [6].

#### Novel aspects

● Repurposing KIRA6 for AML: While IRE1α has been targeted in AML [1], the repurposing of KIRA6 specifically for AML treatment, especially in the context of FLT3-ITD positive disease and potential combination with FLT3 inhibitors or standard chemotherapies, seems novel based on the provided abstracts. The idea explores KIRA6's impact on multiple pathways (UPR, apoptosis, NF-κB, MYC) related to AML proliferation and resistance.
- Focusing on FLT3-ITD positive AML & combination therapy: Although FLT3 inhibitors are used in AML, the idea of combining KIRA6 with FLT3 inhibitors or chemotherapeutics to specifically target FLT3-ITD positive AML cells and potentially overcome resistance addresses a current clinical need. The proposed mechanism – disrupting protein homeostasis in already stressed FLT3-ITD cells – offers a rationale for this combination approach.
- Combination of KIRA6 with other AML drugs & mechanism of action: KIRA6 is not mentioned in any of the abstracts, and therefore the proposed combination of KIRA6 and FLT3i to induce apoptosis is also novel. The described mechanism has strong logical support, as the cells' increased translation requirements and ER stress from the FLT3i mutation could greatly increase the effectiveness of IRAK1 inhibition, which may itself directly induce apoptosis, and also improve efficacy of existing drugs.

#### Novelty review

The idea presents a moderate level of novelty. Repurposing KIRA6 for AML, particularly in the context of FLT3-ITD positive disease and combination therapy, is a promising approach. However, targeting IRE1α in AML has been explored [1], albeit not with this specific drug and with different existing treatment approaches. The idea's strength lies in its detailed mechanistic rationale, combination therapy focus, and defined experimental plan. It is crucial to validate the proposed mechanism and selectivity across different AML cell lines and patient samples before concluding its true novelty.

#### Improvements to the idea

- Literature search: Conduct a thorough literature search beyond the provided abstracts to confirm the novelty of KIRA6 in AML. Investigate any existing research on KIRA6 in other hematological malignancies.
- Selectivity testing: Expand selectivity testing to include other healthy cell types beyond normal myeloid cells, to address potential off-target effects and demonstrate greater safety margin.
- Combination exploration: Further explore rational combinations beyond FLT3 inhibitors, including chemotherapeutic agents and other targeted therapies.
- Resistance mechanisms: Thoroughly investigate the impact of KIRA6 on various AML resistance mechanisms through in vitro testing, using resistant cell lines and patient-derived samples.
- In vivo efficacy and toxicity profile: Expand the in vivo studies with multiple cell lines and patient-derived xenograft models, with a focus on establishing the efficacy and toxicity profile of KIRA6, both as single-agent and in the proposed combination strategy.

#### Reasoning about novelty and recommendation

The idea is novel enough to warrant further exploration. While targeting IRE1α isn't completely new, using KIRA6 in AML, especially in the context outlined, hasn't been extensively investigated, and it also has not been previously examined as a companion drug with other therapies used in AML. The proposed combination with FLT3 inhibitors and the detailed rationale provide a strong foundation. The comprehensive experimental plan should be executed to confirm the preliminary findings and assess the true potential of KIRA6 in AML. If the in vitro and in vivo findings are positive, the idea would be worthy of publication in a specialized journal focused on hematological malignancies or drug repurposing.

**Answer: 3**
````

### D. The published architecture and execution flow

The primary sources on architecture, quoted at length rather than summarised.
**Not** `system-architecture-and-orchestration.md`, which is clone-authored and
carries exactly one paper-backed claim (`R3-1`).

The published *algorithm* is Appendix B above: the seven listings were checked
line by line against Nature SI Supplementary Note 8 (L905-1099) and cover
**all 133 of its distinct lines** — the only line not reproduced is the section
heading. So Appendix B is the complete published orchestration loop, not an
extract of it. What follows is the surrounding prose specification.

#### §3–3.3 System overview, task queue, and the agent roster (with the Figure 2 caption)

Source: `references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md` lines 82-141, sha256 `191ae41db9dd`.

````
This section describes the technical details, agents, and framework comprising the co-scientist system. The co-scientist employs a multi-agent architecture built upon Gemini 2.0, integrated within an asynchronous task execution framework. This framework allows for flexible scaling of test-time compute resources, facilitating advanced scientific reasoning.

Given a research goal specified by an expert scientist in natural language, the co-scientist generates hypotheses and research proposals that adhere to the following default criteria:

- Alignment with the provided research goal. The generated outputs must precisely align with the research goals, preferences and constraints defined by the scientist.
- Plausibility. The system outputs should be free of readily apparent flaws. Any potential contradictions with prior literature or established knowledge must be explicitly stated and justified.
- Novelty. A key objective of the co-scientist system is to generate novel hypotheses, conjectures, and research plans grounded in prior literature, rather than simply synthesizing existing information (a capability already addressed by existing "deep research" tools [\[62\]](#page-34-22)).
- Testability. The system outputs should be amenable to empirical validation within the constraints specified by the scientist.
- Safety. The system outputs will be controlled to prevent enabling unsafe, unethical, or harmful research.

Aside from these default criteria, the co-scientist can be configured with additional criteria, preferences, and constraints as needed. For instance, it can be configured to generate outputs in formats preferred by the researcher to improve interpretability and readability.

Throughout this section, we employ a recurring example: generating hypotheses for exploring the biological mechanisms of Amyotrophic Lateral Sclerosis (ALS) to illustrate the various components of the co-scientist system. While this example has been reviewed by domain experts, it remains illustrative and may contain errors. Importantly, this example does not aim to suggest potential therapeutic avenues for ALS and should be interpreted with utmost caution. All the examples are listed in the Appendix Section [A.3.](#page-46-0)

### 3.1 The AI co-scientist system overview

At a high level, the co-scientist system comprises four key components:

- Natural language interface. Scientists interact with and supervise the system primarily through natural language. This allows them to not only define the initial research goal but also refine it at any time, provide feedback on generated hypotheses (including their own solutions), and generally guide the system's progress.
- Asynchronous task framework. The co-scientist employs a multi-agent system where specialized agents operate as worker processes within an asynchronous, continuous, and configurable task execution framework. A dedicated Supervisor agent manages the worker task queue, assigns specialized agents to these processes, and allocates resources. This design enables the system to flexibly and effectively utilize computational resources and iteratively improve its scientific reasoning capabilities.
- Specialized agents. Following inductive biases and scientific priors derived from the scientific method, the process of scientific reasoning and hypothesis generation is broken down into sub-tasks. Individual,

- specialized agents, each equipped with customized instruction prompts, are designed to execute these sub-tasks. These agents operate as workers coordinated by the Supervisor agent.
- Context memory. In order to enable iterative computation and scientific reasoning over long time horizons, the co-scientist uses a persistent context memory to store and retrieve states of the agents and the system during the course of the computation.

The Gemini 2.0 model is the foundational LLM underpinning all agents in the co-scientist system. The specific co-scientist design was arrived at with iterative developments and is reflective of the current capabilities of the underlying LLMs.

### 3.2 From research goal to research plan configuration

The research goal, specified by the scientist, serves as the entry point to the co-scientist system. Leveraging the multimodal and long context capabilities of Gemini 2.0 models, the co-scientist efficiently processes research goals of varying complexity, from simple statements to extensive documents spanning tens of thousands of natural language tokens or other relevant data (e.g., including hundreds of prior publication PDFs). The research goal may also incorporate specific constraints, attributes, and preferences related to the scientist's particular laboratory setting or field of work.

The co-scientist system then parses the goal to derive a research plan configuration for generating research proposals. This configuration captures the desired proposal preferences, attributes, and constraints. For example, it specifies whether the co-scientist should exclusively propose novel hypotheses. It also specifies the criteria for evaluating hypothesis quality, such as novelty and experimental feasibility. These criteria are then used by the system during its auto-evaluation and improvement phases. The attributes, preferences, and evaluation criteria can all be customized to a given research goal. To illustrate this process, we present an example research goal and its corresponding parsed research plan configuration in Appendix Figure [A.9,](#page-46-1) where the goal is to develop a novel hypothesis related to phosphorylation of the Nuclear Pore Complex (NPC) as a causative mechanism for ALS [\[63\]](#page-34-23).

Based on the research plan configuration, the Supervisor agent initiates the creation of a task queue and begins orchestrating the specialized agents. The system operates continuously and asynchronously. Periodically, the Supervisor agent calculates a comprehensive set of summary statistics, reflecting the system's state and progress toward the specified research goal. These statistics inform decisions regarding resource allocation and the determination of whether a terminal state for the overall computation has been reached. The state is periodically written to the associated context memory of the system and leveraged as feedback in subsequent rounds of computation. It also enables easy restarts in-case of any failure in the system components.

### 3.3 The specialized agents underpinning the AI co-scientist

At the core of the co-scientist system are a coalition of specialized agents, each orchestrated by the Supervisor agent. These agents are designed to emulate the scientific reasoning process, enabling them to generate novel hypotheses and research plans. They are also equipped to interact with external tools, such as web search engines and specialized AI models, through application programming interfaces (APIs). These specialized agents are enumerated below:

- Generation agent. The agent initiates the research process by generating the initial focus areas, iteratively extending them and generating a set of initial hypotheses and proposals that address the research goal. This involves exploring relevant literature using web search, synthesizing existing findings into novel directions, and engaging in simulated scientific debates for iterative improvement.
- Reflection agent. This agent simulates the role of a scientific peer reviewer, critically examining the correctness, quality, and novelty of the generated hypotheses and research proposals. Furthermore, it evaluates the potential of each hypothesis to provide an improved explanation for existing research observations (identified via literature search and review), particularly those that may be under explained.
- Ranking agent. An important abstraction in the co-scientist system is the notion of a tournament where different research proposals are evaluated and ranked enabling iterative improvements. The Ranking agent employs and orchestrates an Elo-based tournament [\[64\]](#page-34-24) to assess and prioritize the

generated hypotheses at any given time. This involves pairwise comparisons, facilitated by simulated scientific debates, which allow for a nuanced evaluation of the relative merits of each proposal.

- Proximity agent. This agent asynchronously computes a proximity graph for generated hypotheses, enabling clustering of similar ideas, de-duplication, and efficient exploration of the hypothesis landscape.
- Evolution agent. The co-scientist's iterative improvement capability relies heavily on this agent, which continuously refines the top-ranked hypotheses emerging from the tournament. Its refinement strategies include synthesizing existing ideas, using analogies, leveraging literature for supporting details, exploring unconventional reasoning, and simplifying concepts for clarity.
- Meta-review agent. This agent also enables the co-scientist's continuous improvement by synthesizing insights from all reviews, identifying recurring patterns in tournament debates, and using these findings to optimize other agents' performance in subsequent iterations. This also enhances the quality and relevance of generated hypotheses and reviews in subsequent iterations. The agent also synthesizes top-ranked hypotheses and reviews into a comprehensive research overview for review by the scientist.

<span id="page-8-0"></span>Figure 2 | The AI co-scientist multi-agent architecture design. The co-scientist accepts a natural language research goal from the user and parses this into a research plan configuration. This plan is then dispatched to the Supervisor agent which evaluates this plan to assigns weights and resources to each specialized agent and subsequently queues them as worker processes in a task queue according to these weights. The worker processes execute the queue of agent actions, and the system ultimately aggregates all information to formulate a research overview with detailed hypotheses and proposals for the scientist. The red boxes in the "The AI co-scientist specialized agents" section denote individual agents each with their own unique logic and role. The blue boxes indicate the scientist-in-the-loop inputs and feedback. The dark gray arrows represent the information flow through the co-scientist system, while the red arrows represent the information feedback loop between the specialized agents.

The Supervisor agent's seamless orchestration of these specialized agents enables the development of valid, novel, and testable hypotheses and research plans tailored to the input research goal.

In summary, the Generation agent curates an initial list of research hypotheses satisfying a research goal. These are then reviewed by the Reflection agent and evaluated in a tournament by the Ranking agent. The Evolution, Proximity, and Meta-review agents operate on the tournament state to help improve the quality of the system outputs.

The Supervisor agent periodically computes and writes to the context memory, a comprehensive suite of statistics, including the number of hypotheses generated and requiring review, and the progress of the tournament. These statistics also include analyses of the effectiveness of different hypothesis generation methodologies (e.g., generating new ideas via the Generation agent vs. improving existing ideas via the Evolution agent). Based on these statistics, the Supervisor agent then orchestrates subsequent system operations, i.e., generating new hypotheses, reviews, tournaments, and improvements to existing hypotheses, by strategically weighting and sampling the specialized agents for execution via the worker processes.

Importantly, the Meta-review agent enables feedback propagation and learning without back-propagation techniques (e.g., fine-tuning or reinforcement learning) [\[65\]](#page-34-25). The Meta-review agent generates feedback applicable to all agents, which is simply appended to their prompts in the next iteration—a capability facilitated by the long-context search and reasoning capabilities of the underlying Gemini 2.0 models. Through this feedback loop, the co-scientist continuously learns and improves in subsequent iterations with more compute scaling.

Finally, while our work leverages Gemini 2.0, the co-scientist framework is model-agnostic and portable to other similar models or combinations thereof. Future LLM improvements will likely enhance the co-scientist's capabilities. The multi-agent architecture of the co-scientist is depicted and summarized in Figure [2.](#page-8-0)
````

#### §3.3.1–3.3.6 One subsection per specialized agent — the per-agent flow

Source: `references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md` lines 145-212, sha256 `1981f113d92f`.

````
#### 3.3.1 Generation agent

The co-scientist Generation agent employs a diverse array of techniques and tools to generate novel hypotheses, such as the following:

- Literature exploration via web search. The agent iteratively searches the web, retrieves and reads relevant research articles, and grounds its reasoning by summarizing prior work. It then builds on this summary to generate novel hypotheses and research plans. An example prompt is given in Appendix Figure [A.1.](#page-39-0)
- Simulated scientific debates. Here, the Generation agent simulates scientific debates among experts by employing self-critique and self-play techniques. These debates typically involve multiple turns of conversations leading to a refined hypothesis generated at the end. An example prompt is given in Appendix Figure [A.2.](#page-40-0)
- Iterative assumptions identification. The agent iteratively identifies testable intermediate assumptions, which, if proven true, can lead to novel scientific discovery. These plausible assumptions and their sub-assumptions are identified through conditional reasoning hops and subsequently aggregated into complete hypotheses.
- Research expansion. To identify previously unexplored areas of the hypothesis space, the Generation agent reviews existing hypotheses and the research overview and feedback provided by the Meta-review agent in the previous iteration. This is used to inform additional exploration directions in the research hypothesis space.

An example hypothesis and research proposal output from the Generation agent is presented in Appendix Figure [A.10](#page-47-0) for the aforementioned research goal regarding explaining a basic mechanism related to ALS. The Generation agent also summarizes and categorizes each generated hypothesis, allowing scientists to quickly grasp the core ideas.

### <span id="page-9-0"></span>3.3.2 Reflection agent

Reviews are integral to the co-scientist's effectiveness in generating novel proposals. The Reflection agent searches relevant prior work (via web search or a dedicated scientist-provided repository), assesses existing experimental evidence for or against a given hypothesis, and rigorously verifies the novelty, correctness, and quality of generated outputs. Effective reviews filter inaccurate and, when stipulated, non-novel hypotheses. Moreover, they also provide feedback to all other agents, driving continuous improvement. The Reflection agent employs the following types of review:

- Initial review. Building on the co-scientist's default evaluation criteria, the Reflection agent performs an initial review assessing the correctness, quality, novelty, and a preliminary assessment of safety (ethics) of the generated hypotheses. For a more in-depth discussion on safety considerations see Section [6.](#page-27-0) This initial review, which doesn't use external tools like web search, aims to quickly discard flawed, non-novel, or otherwise unsuitable hypotheses.
- Full review. If a hypothesis passes the initial review, the Reflection agent performs a full review, leveraging external tools and web searches to identify relevant articles for improved reasoning and grounding. This review evaluates the hypothesis's correctness, quality, and novelty similar to the initial review but with full literature search. For correctness and quality, the agent scrutinizes underlying

assumptions and reasoning. For novelty, it summarizes known aspects of the hypothesis and then judges their novelty based on existing literature. An example full novelty review is shown in Appendix Figure [A.11,](#page-48-0) and an example of review critiques is in Appendix Figure [A.12.](#page-48-1) A complete full review example is shown in Appendix Figure [A.13.](#page-49-0)

- Deep verification review. The Reflection agent also conducts a deep verification review, decomposing the hypothesis into constituent assumptions. Each assumption is further broken down into fundamental sub-assumptions, decontextualized, and independently evaluated for correctness to identify invalidating elements for subsequent filtering. Concurrently, the reasons for potential hypothesis invalidation due to incorrect assumptions are summarized. This deep verification helps the co-scientist detect subtle errors within complex hypotheses, such as flaws in reasoning or inaccurate experimental protocols. An identified error doesn't necessarily invalidate the core hypothesis; the Reflection agent assesses whether the incorrect assumption is fundamental to the hypothesis and incorporates this reasoning into the review. Non-fundamental errors can be addressed during subsequent refinement stages. An example deep verification review is provided in Appendix Figure [A.14](#page-50-0) for the previously introduced ALS hypothesis. We also show another example of a deep verification review via probing questions in the context of drug repurposing for AML in Appendix Figure [A.15.](#page-51-0)
- Observation review. In addition, the Reflection agent also explores whether a given hypothesis can account for long-tail observations from prior experimental results. This review aims to determine if the hypothesis can provide insights on existing experimental findings and observed phenomena within relevant articles. For each observation, the agent assesses if the hypothesis is a superior explanation over existing ones, assuming its validity. Positive observations are summarized and appended to the hypothesis. Note that this review often completes without any important findings (as in the case of the ALS hypothesis example). An example prompt to generate observations is provided in Appendix Figure [A.3.](#page-41-0) An illustrative example of an observation review is provided in Appendix Figure [A.16](#page-52-0) in the context of an alternate hypothesis for explaining a mechanism of anti-microbial resistance.
- Simulation review. The Reflection agent also reviews hypotheses by simulating them in a step-wise fashion (e.g., simulating the mechanism of action or the proposed experiment in the proposal). This simulation allows the agent to identify and summarize potential failure scenarios. This review method is built on the assumption that frontier LLMs may have developed an internal world model that enables them to simulate and accurately predict various scientific phenomena.
- Recurrent/tournament review. The Reflection agent adapts its full reviews based on the co-scientist's growing knowledge. By analyzing reviewed hypotheses and results of the tournament conducted by the Ranking agent, the Reflection agent identifies recurring issues and improvement opportunities, refining its reviews accordingly.

Additionally, the co-scientist can incorporate reviews from expert scientists to guide ranking and improvements (further discussed in Section [3.4\)](#page-12-0). We aim to have the Reflection agent's comprehensive set of reviews cover the common methods scientists employ when critiquing and refining research hypotheses and proposals.

#### 3.3.3 Ranking agent

The AI co-scientist explores numerous hypotheses and research proposals towards a research goal, necessitating a ranking mechanism to prioritize computational resources toward the most promising candidates. This task is performed by the Ranking agent. The agent uses an Elo-based tournament [\[64\]](#page-34-24) to automatically evaluate and rank all hypotheses, providing supporting rationale. This ranking serves to communicate to scientists an ordered list of research hypotheses and proposals aligned with the research goal. Despite its assumptions and limitations [\[66\]](#page-34-26), Elo remains a good proxy for relative ranking, and it has previously been applied to rank extracted patterns and ideas in games [\[67\]](#page-34-27). In the future, extensions may be considered [\[68\]](#page-34-28). We set the initial Elo rating of 1200 for the newly added hypothesis.

Because the tournament is computationally intensive, the Ranking agent employs several optimization strategies. Top-ranked hypotheses are compared pairwise in tournament matches through multi-turn scientific debates [\[69\]](#page-35-0). This mitigates ordering bias and focuses on novelty, correctness, and testability. Lower-ranked hypotheses undergo single-turn comparisons in a pairwise fashion in their tournament match. The agent concludes each comparison with a decision regarding which hypothesis is better. Appendix Figure [A.4](#page-42-0) and Appendix Figure [A.5](#page-43-0) show example prompts. Appendix Figure [A.17](#page-53-0) shows an example of the Ranking agent conducting a scientific debate match in a tournament to compare two hypotheses.

The Ranking agent prioritizes tournament matches as follows: (1) hypotheses are more likely to be compared with similar ones (based on the Proximity agent's graph, described in the next section); (2) newer and top-ranking hypotheses are prioritized for participation in tournament matches. Successful hypotheses quickly achieve favorable rankings and this informs the tournament state for subsequent iterations.

### 3.3.4 Proximity agent

The Proximity agent calculates the similarity between research hypotheses and proposals, and builds a proximity graph, taking into account the specific research goal. Although it doesn't directly participate in hypothesis generation, the Proximity agent assists the Ranking agent in organizing tournament matches and showcasing a diverse range of ideas related to the research goal. This allows scientists to quickly explore areas of interest and easily identify related concepts.

### 3.3.5 Evolution agent

The Evolution agent continuously refines and improves existing hypotheses and proposals using several approaches including:

- Enhancement through grounding. Here the agent attempts to improve hypotheses by identifying weaknesses, generating search queries, retrieving and reading articles, suggesting improvements and elaborating on details to fill reasoning gaps.
- Coherence, practicality and feasibility improvements. The agent aims to address issues and creates more coherent hypotheses, potentially rectifying underlying problems with invalid initial assumptions. The agent also refines the hypotheses to make them more practical and feasible. Appendix Figure [A.6](#page-44-0) provides an example of the feasibility improvement prompt.
- Inspiration from existing hypotheses. The agent additionally creates new hypotheses inspired by single or multiple top-ranked hypotheses.
- Combination. The agent also attempts to directly combine the best aspects of several top-ranking hypotheses to create new hypotheses.
- Simplification. The agent simplifies hypotheses for easier verification and testing.
- Out-of-box thinking. The agent also explores out-of-the-box ideas by moving away from a subset of hypotheses and generating divergent ones. Appendix Figure [A.7](#page-44-1) provides an example prompt for this.

The Evolution agent generates new hypotheses; it doesn't modify or replace existing ones. This strategy protects the quality of top-ranked hypotheses from flawed improvements, as each new hypothesis must also compete in the tournament. The evolution of research hypotheses and proposals also allows the co-scientist to iteratively combine different improvement techniques and gradually improve the quality of the results.

### 3.3.6 Meta-review agent

The Meta-review agent plays a crucial role in the co-scientist's feedback loop, enabling self-improvement in scientific reasoning. This agent operates on the tournament state and summarizes common patterns identified in reviews and scientific debates in the tournament matches into a meta-review critique.

By synthesizing insights from all reviews, the meta-review provides valuable feedback to the Reflection agent, leading to more thorough and reliable future reviews. This helps prevent oversight of critical details. Consider the illustrative example of a identifying a repurposing drug candidate for ALS as a research goal: while only 90% of individual reviews might correctly identify a blood-brain barrier permeability issue in a proposed candidate, the meta-review ensures that all future reviews by the Reflection Agent definitively address this crucial factor. Hypothesis and research proposal generation is also enhanced by the meta-review's identification of recurring issues. While the Generation agent uses this feedback selectively to avoid over fitting to these review critiques, it helps prevent the recurrence of common issues.

Appendix Figure [A.8](#page-45-0) provides an example prompt for the meta-review. In Appendix Figure [A.18-](#page-54-0)[A.19,](#page-55-0) we showcase an example of the summarized meta-review critique generated for the reviews of the previously introduced ALS mechanism hypotheses.

Research overview generation. The Meta-review agent periodically synthesizes top-ranked hypotheses into a research overview, providing a roadmap for future research. This overview outlines potential research areas and directions relevant to the research goal, justifying their importance and suggesting specific experiments within each. Each area includes illustrative example topics. The research overview also serves as an additional input to the Generation agent in subsequent iterations.

The research overview serves to effectively map the boundary of current knowledge relevant to the research goal in the co-scientist system and helps highlight future areas of exploration. In Appendix Figure [A.20-](#page-56-0)[A.21,](#page-57-0) we show an example of a research overview for the ALS mechanism research goal.

The Meta-review agent can further format these overviews using constrained decoding techniques [\[70\]](#page-35-1) to adhere to common research publication and grant formats (e.g., National Institute of Health (NIH) Specific Aims Page format). We demonstrate the effectiveness of this in subsequent sections.

Research contacts identification. The Meta-review agent uses prior literature review to suggest qualified domain experts for research hypotheses and proposal review, including the reasoning behind each suggestion. These potential contacts are summarized in the research overview, providing researchers with additional perspectives and potential avenues for collaborations. An example research contact (with the researcher name redacted) is shown in Appendix Figure [A.22.](#page-58-0)
````

#### §3.4–3.5 Expert-in-the-loop and tool use

Source: `references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md` lines 213-229, sha256 `fe43d8c4c6fd`.

````
### <span id="page-12-0"></span>3.4 Expert-in-the-loop interactions with the co-scientist

The AI co-scientist empowers scientists to actively guide the system through an expert-in-the-loop design (Figure [2\)](#page-8-0). Scientists can interact with the system in several ways:

- Refine the initial research goal in light of the generated hypotheses and research overview.
- Provide manual reviews of generated hypotheses (see Section [3.3.2](#page-9-0) for other system generated review types), which the co-scientist uses to evaluate and improve the hypotheses and proposals.
- Contribute their own hypotheses and proposals for inclusion in the tournament, where they are ranked alongside and can be combined with system-generated hypotheses and proposals.
- Direct the co-scientist to follow up on specific research directions (for example restricted to a smaller collection of prior publications). When this research is referenced in the research goal, the co-scientist can prioritize generation methods that can access and synthesize it.

### 3.5 Tool use in AI co-scientist

The co-scientist leverages various tools during the generation, review, and improvement of hypotheses and research proposals. Web search and retrieval are primary tools, important for grounded, up-to-date hypotheses.

For research goals that explore a constrained space of possibilities (e.g., all known cell receptors of a specific type or all FDA-approved drugs), the co-scientist agents utilize domain-specific tools, such as open databases, to constrain searches and generate hypotheses. The co-scientist can also index and search a private repository of publications specified by the scientist.

Finally, the system can utilize and incorporate feedback from specialized AI models like AlphaFold. We demonstrate this qualitatively with a protein design example in the Appendix Section [A.6.](#page-79-0)
````

#### §4.2 Test-time compute scaling — the paper's own framing of how the system spends more effort

Source: `references/core/google-co-scientist/research/papers/towards-an-ai-co-scientist.md` lines 230-278, sha256 `c7217c4cb3f3`.

````
### 4 Evaluation and Results

We now discuss the methods for evaluating the AI co-scientist system and the corresponding results. The initial evaluations aim to benchmark and verify the choice of the strategies and metrics underpinning the co-scientist. We then proceed to perform a small-scale evaluation with domain experts to assess the quality of the system.

Furthermore, to assess the practical utility of the system's novel predictions, we also perform end-to-end wet-lab validations (laboratory experiments) of the co-scientist-generated hypotheses and research proposals in three key biomedical applications: drug repurposing, discovering novel treatment targets, and elucidating the mechanisms underlying antimicrobial resistance. The varying complexity and nature of these applications enable a more comprehensive assessment of the system. Notably, all three validations involved expert-in-theloop guidance and prioritization of experiments. These applications are summarized in Table [1.](#page-13-0)

<span id="page-13-0"></span>

| Application      | Drug repurposing       | Novel treatment target discovery | Explain mechanism of<br>gene transfer evolution |
|------------------|------------------------|----------------------------------|-------------------------------------------------|
| Challenge        | Combinatorial search   | Identifying novel targets        | Understanding complex systems                   |
| Complexity       | Medium                 | High                             | Very high                                       |
| Scale            | Moderate, data-limited | Moderate, experiment-limited     | Large, data and computation-limited             |
| Unknown elements | Constrained            | Large                            | Vast and dynamic                                |

Table 1 | Three real-world applications in biomedicine for end-to-end validation of the AI co-scientist.

### 4.1 The Elo rating is concordant with high quality AI co-scientist results

The Elo auto-evaluation rating is a key metric that guides the self-improvement feedback loops within the co-scientist system. Therefore, it's necessary to measure and ensure higher Elo ratings correlate with higher quality results. To assess this, we analyzed the concordance between the Elo rating and the system's accuracy on the GPQA benchmark dataset. Ideally, higher Elo ratings should correlate with a higher probability of correct answers.

The GPQA dataset is a challenging, multiple-choice question answering benchmark developed by experts in biology, physics, and chemistry [\[71\]](#page-35-2). To ensure that the co-scientist Elo rating serves as an objective metric reflecting the validity and correctness of results from the system, we utilized questions within the GPQA diamond set, a subset of the GPQA dataset known for its high difficulty, framing each question as a research goal into our AI system to elicit responses. For each question, we first compared each co-scientist response against the ground truth answer to evaluate its correctness. Then, we categorized all generated responses across all considered questions based on their Elo rating into discrete buckets: Elo rating of 1001-1050, 1051-1100, 1101-1150, etc. in 50 point increments, until the highest rating achieved. Finally, we calculated the average accuracy for each Elo rating bucket, as the percentage of correct responses within each bucket.

We employed the underlying Gemini 2.0 models in the AI co-scientist to create a reference baseline. The reference is necessary because responses within a particular Elo rating bucket are not uniformly distributed across the GPQA questions - some of which are inherently more challenging than others. This non-uniformity could introduce bias into the analysis and potentially lead to erroneous conclusions. We therefore used the reference to generate 32 responses for each GPQA question. The fraction of correct responses from Gemini 2.0 was used as a reference accuracy on that particular question. To determine reference accuracy for a specific Elo bucket, we averaged the reference accuracy of the GPQA questions that had co-scientist responses within that bucket. We also computed the co-scientist accuracy on the GPQA diamond set by using the result with the highest Elo rating for each question and comparing it against the ground truth.

Our analysis using questions from the GPQA diamond set reveals a concordance between the Elo rating and averaged accuracy of generated co-scientist results, as depicted in Figure [3.](#page-14-0) By selecting the top-rated co-scientist result for each question, the co-scientist achieves a top-1 accuracy of 78.4%.

<span id="page-14-0"></span>Figure 3 | Concordance of the auto-evaluation Elo metric with AI co-scientist performance on GPQA. The blue line in the figure shows the average accuracy of co-scientist responses, grouped by their Elo rating. The red line indicates the average accuracy of the corresponding reference Gemini 2.0 responses to the same set of GPQA questions, grouped by Elo rating. Note that Elo metric is auto-evaluated and not based on the ground truth.

#### 4.2 Scaling test-time compute improves scientific reasoning of the AI co-scientist

To evaluate the effects of test-time compute scaling and the co-scientist's progress during iterative scientific reasoning and hypothesis generation, we measured the Elo ratings of the co-scientist generated hypothesis and proposals over the course of the tournament. This analysis was done across 203 distinct research goals curated across broad scientific topics (predominantly in biomedicine, but also included other topics such as mathematics and physics) and entered into the co-scientist system until February 3, 2025.

<span id="page-14-1"></span>Figure 4 | Impact of scaling test-time compute on AI co-scientist as measured by Elo auto-evaluation. The co-scientist's research hypotheses and proposals were partitioned into ten temporal buckets of equal size, with the last bucket corresponding to the most recently generated results from the system. For each bucket, we determined the maximum individual Elo rating (the "best Elo") and the average Elo rating of the top 10 hypotheses across 203 unique research goals. The resulting upward performance trends, across both metrics, suggest improvements in the co-scientist result quality with scaling of test-time compute. Note that the Elo metric is auto-evaluated and not based on independent ground truth.

The co-scientist's research hypotheses and proposals were partitioned into ten temporal buckets of equal size. Each bucket corresponded to a sequential 10% of the total generation time with the first bucket containing the earliest 10% of generated co-scientist results, while the tenth bucket comprised the most recent 10%. For each bucket, we determined the average Elo rating of the top 10 hypotheses and the maximum individual Elo rating (the "best Elo"). These average and best Elo ratings were averaged across 203 research goals and their corresponding tournaments. The resulting performance trends as seen in Figure 4, across both metrics, serves as a measure of the co-scientist's quality improvement over time. The most recent results demonstrated a significant quality enhancement compared to the initial outputs. Notably, although the Elo rating is not the direct optimization target, its progressive increase emerges from the system's self-improvement feedback loops.

<span id="page-15-0"></span>Figure 5 | Comparison of the AI co-scientist with other baselines as measured by Elo auto-evaluation on a subset of 15 challenging expert-curated research goals. The AI co-scientist's research hypotheses and proposals were partitioned into ten equal-sized temporal buckets, with the last bucket representing the most recent system-generated results. For each bucket, we calculated the maximum individual Elo rating ("best Elo") and the average Elo rating of the top 10 hypotheses across 15 challenging research goals, curated by biomedical experts. These metrics were then compared to the performance of several baselines: Gemini 2.0 Pro Experimental, Gemini 2.0 Flash Thinking Experimental 12-19, OpenAI o1, OpenAI o3-mini-high, DeepSeek R1, and the "best guess" hypotheses provided by the expert curators. These baseline performances are represented by colored dashed lines. On this expert-curated subset of research goals, we consistently observed upward performance trends with increased test-time compute. Furthermore, the co-scientist significantly outperformed both the human experts and the other state-of-the-art LLM baselines, as measured by the Elo metric. It's important to note that the Elo metric is auto-evaluated and not based on independent ground truth. This auto-evaluation metric may favour results with attributes that do not necessarily align with scientists' preferences, quality, or accuracy.

To further contextualize this observation, we focused our analysis on a subset of 15 research goals, curated as challenging problems by seven biomedical experts in their respective fields of expertise. These experts held doctoral degrees in biological or life science disciplines and were actively working as postdoctoral researchers or faculty members at academic biomedical research institutes. These research goals were consistently structured and formatted, encompassing a research title, a clear set of goals, preferences specifying biological or disease areas of interest, desirable solution attributes, and constraints on experimental techniques.

In addition to the research goals, the experts provided their "best guess" hypotheses or solutions. We then included outputs from other state-of-the-art LLMs and reasoning models—Gemini 2.0 Pro Experimental, Gemini 2.0 Flash Thinking Experimental 12-19, OpenAI o1, OpenAI o3-mini-high, and DeepSeek R1—in a tournament along with the expert "best guess" and co-scientist for each curated goal. Performance was assessed using the co-scientist Elo rating metric.

The trends previously observed with test-time compute scaling in Figure 4 were consistent within this subset. Furthermore, as shown in Figure 5, the co-scientist surpassed the other frontier LLMs and reasoning models in Elo rating with increased computational resources for iterative improvement. Notably, newer reasoning models, such as OpenAI o3-mini-high and DeepSeek R1, demonstrated competitive performance while requiring significantly less compute and reasoning time. Finally, we observed no evidence of performance saturation as measured by Elo, suggesting that further scaling of test-time compute in this paradigm could yield continued improvements in result quality of the co-scientist system. Its worth noting again that the co-scientist architecture is model agnostic and is likely to benefit from further advancements in frontier and reasoning LLMs.

Building upon the co-scientist system's ability to combine, refine and improve research hypotheses and proposals iteratively, we investigated its potential to improve upon expert "best guess" solutions. Consistent with our previous observations, the co-scientist demonstrated the capacity to enhance expert's "best guess" solutions over time, as evidenced by the Elo metric in Figure 6. Notably, the improvement trends initially mirrored those of the co-scientist's autonomously generated solutions but subsequently surpassed them. While this is a preliminary finding requiring further validation, it suggests a promising avenue for capable AI systems, such as the co-scientist, to augment and accelerate the work of expert scientists.

<span id="page-16-0"></span>Figure 6 | AI-augmented expertise with the co-scientist through Elo-based auto-evaluation. Through its selfimprovement process, the co-scientist refines and enhances expert "best guess" solutions over time, as measured by the Elo rating on a subset of 15 curated research goals. It is important to note that the Elo metric is auto-evaluated and not based on independent ground truth.
````
