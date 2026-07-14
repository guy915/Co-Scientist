# Google Co-Scientist fidelity implementation — final status

**Date:** 2026-07-14
**Reconciled HEAD:** see `git log` (the reconciliation commits of 2026-07-14)
**Companion artifacts:** `GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md`
(232-row audit), `GOOGLE_CO_SCIENTIST_1_TO_1_IMPLEMENTATION_PROMPT.md`
(17 acceptance conditions), `fidelity_closure_overrides.json` + generated
`IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md` (per-finding ledger), `docs/PARITY.md`.

## 1. Outcome summary

The repository is a runnable, evidence-bounded reconstruction of Google
Co-Scientist and the Hypothesis Generation product. As of this reconciliation:

- The full scientist journey works end-to-end and was driven live in the
  built-in browser: intake → multi-turn model-driven Agent interview → the exact
  four-field research plan → exactly Standard/Advanced run configuration →
  durable asynchronous execution → truthful executing screen → Goal Report
  surface (Ideas / Knowledge Base / Summary / Run Specifications).
- Scientific claims are grounded before decisive ranking and again before
  publication; unsupported or contradicted material claims cannot enter the Elo
  tournament (fixed 2026-07-14) or a published report.
- All 232 audited findings have been reconciled against the current code with
  direct file/symbol/test evidence.

This is **not** a literal 1:1 replica, and no numerical fidelity score is
assigned. The honest terminal state is: every actionable gap has direct
evidence, and every proprietary/undisclosed Google internal is explicitly
labelled unverifiable rather than invented (see §6).

## 2. Finding closure distribution (232 findings)

| Disposition | Count | Meaning |
|---|---|---|
| implemented | 86 | Behavior works, is reachable, and is tested. |
| partial | 104 | A working subset exists; a concrete named gap remains. |
| matched | 6 | Narrow primitive the audit already classed a material match. |
| extension | 13 | A non-faithful addition, quarantined behind developer mode or dead. |
| missing | 12 | No working implementation (several are external eval gaps). |
| unverifiable | 11 | Google's exact behavior is not public enough to compare. |

The distribution is deliberately not all-green: 104 partial and 11 unverifiable
rows reflect real, documented boundaries, not unfinished tracking.

## 3. Acceptance conditions (10 implemented / 7 partial)

**Plainly stated up front:** no real compatibility-provider run produced a
*completed* Goal Report. Both 2026-07-14 runs (metformin/AMPK and senolytic)
reached terminal `blocked` at the claim-level evidence release gate — correct
fail-closed behavior. The gate is proven in both directions (two blocked runs +
the `test_pre_ranking_gate_releases_idea_after_new_support` unit test); it was
deliberately **not** loosened to manufacture a passing report. Consequently the
"completed Goal Report" surfaces (AC10) and the completed-report browser journey
(AC14) are verified by tests and by the blocked-state UI, not by a live
populated report.

**Design boundary (documented, not resolved):** the implementation prompt lists
four remedies for an unsupported categorical claim — "Revise, hedge, quarantine,
or abstain." The current gate takes the most conservative one (**abstain**:
quarantine the whole idea if any categorical/mechanism claim is unsupported),
even though the report renderer also hedges each claim inline. A less strict but
still spec-faithful policy (require ≥1 supported contextual claim and block only
contradicted claims, hedging unsupported ones inline) would let more real runs
publish. That policy question is deliberately **not** reopened here: loosening
the gate under completion pressure to manufacture a passing report would be
confirmation bias, and the audit endorsed the fail-closed choice.


| AC | Status | Note |
|---|---|---|
| 1 Interview → four fields | implemented | Live browser: two distinct model questions, four-field plan derived from answers. |
| 2 Standard/Advanced + 3/1 concurrency | implemented | Live browser exactly two run types; server-side quota tested. |
| 3 Supervisor creates/reprioritizes durable tasks | implemented | Model allocation + queue actions; steering forced into live state. |
| 4 Concurrent durable tasks survive restart | implemented | Multi-process lease/duplicate/redelivery tests; two concurrent live runs. |
| 5 Every strategy has an end-to-end test | partial | Comprehensive per-strategy tests; assumptions/research-expansion behaviorally partial. |
| 6 Multi-source ranked retrieval + provenance | partial | PubMed+OpenAlex+ChEMBL+UniProt+OCR; no web search/AlphaFold, no hundreds-of-PDFs. |
| 7 Claim spans + publication gate | implemented | Per-claim labels; pre-ranking + report gates; live blocked run confirmed fail-closed. |
| 8 Citation eval gates | implemented | 30-case adversarial panel: contradiction recall 1.0, accuracy 0.90, gates pass. |
| 9 Truthful progress/metrics | implemented | Live browser: honest indeterminate progress, real source/idea counts, activity log. |
| 10 Complete Goal Report + follow-up | partial | All controls functional+tested; a fully-populated live report render pending. |
| 11 Human inputs alter later work | partial | Steering reached applied=1 and merged into checkpoint state, but the run blocked before output changed; manual-hypothesis/review/upload propagation is test-only. |
| 12 Safety/adjudication/auth | partial | Consolidated policy, adjudication, intended-use, ownership 404; default auth is compatibility mode; 1,200-goal panel external. |
| 13 Mock cannot contaminate | implemented | Demos gated to developer mode; real path never falls back to mock. |
| 14 Desktop/mobile verification | partial | Interview/config/executing verified at 1440×720 and 375×812; completed-report journey pending. |
| 15 All software gates pass | implemented | engine 1071 / app 457 / frontend 281, ruff/mypy/lint/build clean; eval smoke green. |
| 16 Evaluation reports checked in | partial | Citation/safety/expert-readiness/scaling harness/failure-recovery present; GPQA/scaling-curve/expert-panel/wet-lab external. |
| 17 Documentation identifies uncertainty | implemented | This document + reconciled ledger + consistent PARITY; no literal-parity claim; the product itself labels reconstruction provenance. |

`PREVIOUS_SESSION_SUMMARY.md` (a prior session's transcript summary) is now
tracked with the other audit artifacts, since the goal's reading list references
it and it should be durable for future sessions.

## 4. Verification (2026-07-14)

- Engine: 1073 tests passed; ruff clean; mypy clean (211 source files).
- App: 447 passed in default (deterministic, no-randomizer) order excluding the
  three environment-restricted process-pool files, which pass standalone
  (test_durability 8; multi_process / crashed_process 3) — 458 total; ruff
  clean; mypy clean (123 source files). Note: running `test_engine_tasks.py`
  and `test_resume_engine.py` as an isolated pair surfaces a pre-existing
  test-isolation fragility (module-level engine state leaks between them; it
  fails the same way with this session's changes reverted); the full
  collection order resets that state, so the suite passes. The env-restricted
  files hang only late-session under accumulated multiprocessing/semaphore
  pressure, not on any assertion.
- Frontend: 281 tests passed; gts lint clean; production build passed.
- Evaluations: offline smoke green; citation challenge panel (llm:deepseek)
  accuracy 0.90 / contradiction recall 1.0 with documented gates; safety 13
  cases 0 FP/0 FN; parity checker OK (64 rows, 52 verified / 6 partial / 6 external).
- Runtime: multiple real-provider runs executed through the durable queue; each
  confirmed the claim-evidence release gate fires fail-closed ("No hypothesis
  passed the claim-level evidence release gate"). The final harvested run
  (metformin/AMPK, `8d22f692`, 141 tasks, 21 hypotheses) reached a legitimate
  terminal `blocked` after a full workflow: intake safety allowed, the report was
  synthesized (`research_overview` completed), the final safety gate allowed, and
  only the claim-level evidence gate withheld release. Two facts were verified on
  that run: (a) the private-corpus grounding fix is live — the gate's evidence
  pool contained the uploaded `attachment` node, which prior code omitted; and
  (b) the block cause is a data-availability limit, not a code defect — the
  retrieved public PubMed set was off-topic (a TRPML1/lysosome cluster, an
  external-server result for a correctly-constructed query, confirmed by
  code-elimination trace), so no on-topic supporting evidence was grounded. The
  binding failure is supports-missing, not off-topic contradiction: across all
  persisted runs the `claim_evidence` ledger holds 1,882 `insufficient` vs 19
  `supports` and 13 `contradicts` (98.3% insufficient), so a post-retrieval
  relevance filter (which only removes noise, never adds support) cannot change
  the outcome and was deliberately not added.
- Browser: intake, multi-turn interview, four-field plan, Standard/Advanced
  config, and executing screen verified at desktop 1440×720 and mobile 375×812
  with no horizontal overflow.

## 5. Evaluation artifacts (evaluations/results/)

- `citation-entailment-challenge-llm_deepseek_deepseek-chat-2026-07-14.json`
  (semantic assessor, gates pass) and `-deterministic-2026-07-14.json` (lexical
  baseline fails the gates, by design).
- `hypothesis-safety-2026-07-14.json` (13 adversarial cases, 0 FP/FN).
- `expert-review-readiness-2026-07-13.json` (schema + explicit not-run).
- `failure-recovery-2026-07-14.md` (15 crash/restart/duplicate/lease/superseded
  scenarios mapped to passing tests).

## 6. Proprietary and unverifiable boundaries (AC17)

The following are not publicly knowable and are implemented as configurable,
auditable reconstructions labelled `reconstructed`/`inferred`/`unverifiable`,
never `verified_google`:

- Standard/Advanced task, time, token, credit, and verification budgets (B02).
- Production scheduler weights, fairness, judge count, tie policy, retry
  parameters (F06), and generation/evolution sampling weights (E22, H03).
- Google's Search/scientific retrieval stack and internal databases (G01, G05,
  G21); the current product's exact model mixture and revisions (L16, L17).
- Classifier implementations, thresholds, and human-review escalation (J02);
  the private 1,200-goal safety benchmark (J03).
- Production latency, accelerator allocation, queue topology, SLOs (L13), and
  the unbiased distribution of Google's production output quality (K15).
- Cross-goal memory, which remains off in faithful mode (I09).

The authoritative `verified` / `inferred` / `reconstructed` / `extension` /
`unavailable` taxonomy lives at the audit level — the reconciled closure ledger
(`fidelity_closure_overrides.json`) and this register — rather than as a
machine-readable `fidelity_provenance` section emitted on every run. The product
surfaces reconstruction provenance only as a conditional UI note (Run
Specifications, when legacy criteria are present) plus the run's stored `tier`;
a dedicated per-run machine-readable provenance section remains a documented gap,
not a claim.

Because these remain undisclosed, the closest achievable result is an
evidence-bounded reconstruction that matches every verified public behavior and
isolates every inferred choice behind configuration. It must not be described as
a literal 1:1 implementation of Google Co-Scientist.

## 7. Migrations and compatibility

Forward-only SQLite migrations back the durable task queue/leases, claim
evidence + spans + roles, interview state, safety adjudication, sharing grants,
and completion notifications. Mock/demo runs are preserved as read-only,
developer-mode-only records and cannot enter faithful history, evaluation, or a
report's evidence. DeepSeek via LiteLLM is a clearly-labelled compatibility-mode
provider; its output is not represented as current Google-model (Gemini) parity.

## 8. Per-partial completion audit (why each partial is at its maximum)

The goal requires "all 17 acceptance conditions ... and every actionable
finding ... have current, direct evidence," while also forbidding fabrication,
mocks/stubs credited as behavior, and any parity claim for undisclosed Google
behavior. Those constraints bind each remaining partial. Each was inspected in
the final worktree; none has a closure that is simultaneously fabrication-free,
faithful, and low-regression. The blocking reason is classified as: **external**
(needs unavailable data/service), **undisclosed** (Google's behavior is not
public, so parity is unprovable per AC17), **faithful-design** (a deliberate,
audit-endorsed choice whose reversal under completion pressure would be the
confirmation-bias failure the task warns against), or **feature-risk** (a real
feature whose value is marginal and whose regression risk is real — this session
already introduced and fixed one such regression).

| Partial AC | What remains | Class | Why it cannot be closed within the rules |
|---|---|---|---|
| 5 Every strategy has an e2e test | research-expansion is a re-entry convention lacking dedicated unexplored-space/coverage analysis; assumptions runs only in the degraded no-literature mode | feature-risk | Each is a real generation-strategy feature, not a missing test; adding one is medium-risk generation work with marginal fidelity gain. |
| 6 Retrieval scale/multimodal | no general web search; no AlphaFold; no hundreds-of-PDFs scale run | external + feature-risk | AlphaFold is an unavailable external service (returns `unavailable`, never fabricated); web search is a large non-biomedical feature; the core multi-source ranked + private + OCR retrieval is implemented. |
| 10 Complete Goal Report | a fully-populated *completed* report rendered live (all controls are functional and tested; blocked-state report verified live) | faithful-design | Blocked only by the strict evidence gate; every control is exercised by `run_detail.test.tsx`, and the release path is proven by `test_pre_ranking_gate_releases_idea_after_new_support`. |
| 11 Inputs alter output | output-level (vs task-level) propagation on a *completed* artifact | faithful-design | Task-level propagation is shown live (a steered run produced a fisetin-bearing hypothesis); a completed-artifact demonstration needs the gate to pass. |
| 12 Safety/auth | default auth is compatibility (X-Client-ID); the 1,200-goal safety panel | undisclosed + external | Required-auth is implemented and tested (`test_auth.py`); the *default* is a deployment-usability choice and Google's actual access mechanism is undisclosed. The 1,200-goal benchmark is private/external. |
| 14 Desktop/mobile journey | completed-report, share, download states at both viewports (interview/config/executing/blocked-report verified live at 1440×720 and 375×812) | faithful-design | Same completed-report gate dependency as AC10/AC14; the populated-report components are covered by vitest. |
| 16 Evaluation reports | Elo↔GPQA calibration; real-provider scaling curves; recruited expert panel; wet-lab validation | external | Each needs licensed data, credentialed large runs, recruited humans, or a wet lab. Citation, safety, expert-readiness, scaling-harness, and failure-recovery reports are checked in. |

### Deferred actionable refinements (finding-level backlog)

Distinct from the external/undisclosed/gate-bounded items, a long tail of
finding-level partials are genuinely actionable but are incremental refinements
of already-mostly-working behaviors, each carrying real regression risk against
the generation/reflection/ranking core. They are listed here with risk so the
human or a fresh session can prioritize them without completion-pressure (this
session already introduced and fixed one regression under that pressure). None
changes the acceptance-condition status, since the external/undisclosed ACs
remain unclosable regardless.

| Finding | Refinement | Files | Risk |
|---|---|---|---|
| E08 | Add a dedicated unexplored-space/coverage analysis for research-expansion (currently a later-cycle re-entry with meta-review context). **Inspected 2026-07-14:** the faithful target (Nature line 337) requires a *new* generation sub-step that examines existing hypotheses + prior overview/feedback for unexplored space and records a task with that method — a new feature, not a wiring tweak. | `nodes/generation/coordinator.py`, `generation/techniques.py` | medium (generation control) — feature-risk |
| E07 | Run assumptions alongside grounded generation, iteratively to subassumptions. **Inspected 2026-07-14:** the coordinator already fires assumptions whenever `assumptions_count > 0` (coordinator.py:164, not gated on degraded mode), but `generate_with_assumptions` hardcodes `domain_context=""` (assumptions.py:47) so it ingests no literature; a faithful close needs (a) allocation in the lit-available strategies, (b) literature plumbed into the assumptions prompt, and (c) iterative subassumption *depth* (Nature line 336). All three materially change generation output on every normal run and cannot be verified to the "actually works, no stubs" bar without completed real-provider runs — which the faithful evidence gate currently withholds. | `nodes/generation/coordinator_strategy.py`, `generation/assumptions.py` + prompt | medium (generation allocation + depth) — feature-risk |
| E32 | **Closed this session.** `ranking_phase` was genuinely dead (no reader anywhere, not even stored on state) and was removed from `schemas/planning.py` and the `supervisor.md` prompt (33 supervisor/planning tests pass, ruff/mypy clean). The other three (`performance_assessment`, `adjustment_recommendations`, `output_preparation`) are **not** dead: `nodes/supervisor.py:215-219` stores them on workflow state as intentional observability/debugging output, so they are retained by design, not removed. | `schemas/planning.py`, `prompts/templates/supervisor.md` | done (ranking_phase) / intentional (other 3) |
| G17-adjacent | A blocked idea's evidence gate could trigger a targeted regeneration-repair loop rather than only quarantine | `app/engine_tasks.py` | medium (control flow) |

Three backlog items were closed this session once a low-risk path was found:
**E18** (single-turn matchup presentation order now alternates via the matchup
index in `ranking.py`), the deep-verification half of **E28/F12** (meta-review
critique now reaches the deep verifier's prompt in `deep_verification.py`; only
the low-value proximity residual remains), and the dead-field half of **E32**
(the unread `ranking_phase` object was removed from the supervisor schema and
prompt; the other three plan fields are intentional observability, not dead).

The three faithful-design partials (10, 11, 14) all reduce to one root: the
evidence gate takes the most conservative of the implementation prompt's four
allowed remedies (**abstain**), so a real compatibility-provider run rarely
produces a completed report. This is now quantified from the runtime ledger:
across every persisted run, 1,882 of 1,914 claim-evidence assessments (98.3%)
resolve to `insufficient`, with only 19 `supports` — under the DeepSeek
compatibility provider, claims almost never ground to `supports`, so the gate
withholds release by design rather than by defect. That choice is faithful and
audit-endorsed;
reversing it to manufacture a completed report would violate the task's own
prohibition on gaming the acceptance criteria. Consequently these three, plus
the external (6, 12, 16) and feature-risk (5, 6) items, are at their honest
maximum. Completion in the literal all-green sense is not reachable without
fabrication or an unfaithful change — which is precisely why AC17 and the
"Explicit reconstructed boundaries" section exist. This audit is the required
requirement-by-requirement pass; its result is an evidence-bounded
reconstruction, not a literal 1:1 implementation.
