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
| implemented | 85 | Behavior works, is reachable, and is tested. |
| partial | 105 | A working subset exists; a concrete named gap remains. |
| matched | 6 | Narrow primitive the audit already classed a material match. |
| extension | 13 | A non-faithful addition, quarantined behind developer mode or dead. |
| missing | 12 | No working implementation (several are external eval gaps). |
| unverifiable | 11 | Google's exact behavior is not public enough to compare. |

The distribution is deliberately not all-green: 105 partial and 11 unverifiable
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

The one intentionally-retained untracked file is
`PREVIOUS_SESSION_SUMMARY.md` (a prior session's transcript summary), left in
place rather than committed or discarded.

## 4. Verification (2026-07-14)

- Engine: 1071 tests passed; ruff clean; mypy clean (211 source files).
- App: full suite 457 passed (fresh session-start environment); ruff clean;
  mypy clean (123 source files). After the only app-code change (G17) the
  affected files were re-verified (46 passed) and each environment-restricted
  process-pool file passes standalone (test_durability 8; multi_process /
  crashed_process 3). The full app suite hangs late-session under accumulated
  multiprocessing/semaphore pressure — an environment artifact, not a code
  failure; every test file passes individually.
- Frontend: 281 tests passed; gts lint clean; production build passed.
- Evaluations: offline smoke green; citation challenge panel (llm:deepseek)
  accuracy 0.90 / contradiction recall 1.0 with documented gates; safety 13
  cases 0 FP/0 FN; parity checker OK (64 rows, 52 verified / 6 partial / 6 external).
- Runtime: two real-provider runs executed concurrently through the durable
  queue; a prior real run confirmed the claim-evidence release gate fires
  fail-closed ("No hypothesis passed the claim-level evidence release gate").
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
