# External Reference Campaign for Co-Scientist

Improve the existing Co-Scientist implementation by studying the nine specified repositories sequentially, adopting useful code or techniques, and verifying each improvement against the current product and published Google behavior. Done means every repository has a complete evidence-backed assessment, every accepted improvement is implemented and verified, each repository’s changes are merged and deployed, and retained documentation explains every adoption and rejection. Non-goals are replacing the current stack, adding a separate computational-discovery product, redesigning the workbench, claiming knowledge of Google’s private implementation, or incurring additional charges.

## Campaign contract

### Authority and boundaries

- Preserve documented Google behavior. External implementations provide hypotheses about improvements, not evidence of what Google built.
- Label findings **Google-backed requirement**, **external technique**, or **local design choice**.
- Retain FastAPI, React, LangGraph, SQLite, and the existing Vercel/Railway services. Allow justified libraries and optional adapters.
- Improve existing screens, reports, and workflows autonomously. Record new product modes and substantial redesigns as out of scope.
- Preserve append-only lineage, durable task recovery, authenticated event replay, evidence provenance, safety gates, and deployment invariants.
- Study all nine repositories in the listed order. Permit at most three additional repository investigations, each justified by a specific unresolved gap.
- Merge and deploy after each repository. If investigation produces no product changes, record that outcome and verify the current deployment; do not manufacture an improvement or force a redundant deployment.

### One repository at a time

Use one ignored checkout at `references/work/<slug>/`. Here, “fork” means a local working copy; creating GitHub forks is unnecessary unless maintaining an upstream modification becomes justified.

For each repository:

1. Pin its upstream URL and commit; inspect its actual license and relevant component licenses.
2. Map its substantive code, prompts, tests, documentation, and operational assumptions.
3. Compare mechanisms against the current local implementation, including improvements adopted earlier in this campaign.
4. Implement accepted findings, verify them, merge, and deploy.
5. Preserve the assessment, evidence, and attribution, then remove the temporary checkout before acquiring the next repository.

Do not execute upstream setup scripts or agent workflows before inspecting them. Run necessary upstream experiments in isolated environments without ambient credentials. Preserve adopted code in its proper maintained location with attribution; temporary reference checkouts must not become runtime dependencies.

### Persistent records

`PLAN.md` is the authoritative execution state. Supporting evidence lives under `references/external/`:

- `README.md`: source inventory, pinned revisions, assessment status, and links to dossiers.
- `campaign.md`: verification commands, fixed evaluation inputs, selected free models, baseline results, and operational procedures.
- One dossier per repository: architecture map, inspected areas, candidate decisions, source permalinks, local counterparts, experiments, adopted changes, and release evidence.

Each candidate receives a stable ID and records:

- The concrete gap and affected user or scientific behavior.
- Upstream evidence and corresponding local implementation.
- Fidelity classification and reuse approach: copy, adapt, independently implement, or use an existing dependency.
- Acceptance criteria, test boundary, evaluation results, and costs.
- Final disposition: adopted, already covered, rejected with evidence, or outside the authorized scope.

Promising but inconclusive candidates remain open. Rate limits, inconvenience, or the turn limit are not evidence for rejection.

### Zero additional spending

Before any campaign inference:

- Inspect current local and deployed model settings without exposing credentials.
- Select explicit OpenRouter models whose current applicable prices are zero. Include new or stealth models when available, but assess capability rather than assuming novelty implies quality.
- Test structured output, tool calling, streaming, long prompts, and reasoning-budget behavior through the project’s actual interfaces.
- Enforce zero-cost routing on campaign calls and system-default free-model paths, including retries, fallbacks, auxiliary models, embeddings, and evaluation runners. Disable paid plugins and metered tools for campaign experiments.
- Treat unknown prices or unverifiable billing paths as unavailable. Preserve users’ explicit BYOK behavior separately.
- Recheck prices and availability before live experiment batches. Record the model actually served.
- Honor rate limits and resume recorded experiments later. Never substitute a paid model, fabricate live results, or present offline output as live evidence.

Use a fixed selected model configuration for each baseline/candidate comparison. If it changes, rerun both sides. Do not automatically redeploy production whenever a new free model appears.

## Verification and release rules

### Acceptance evidence

**Correctness and reliability changes:** reproduce the defect, write a failing behavioral test, implement the smallest correction, and verify through the affected public interface.

**Scientific-quality changes:** declare the primary metric and non-regression criteria before implementation. Reuse the existing citation, claim-support, safety, ranking-concordance, retrieval, and ablation evaluators. Use frozen public inputs, isolated caches, identical model settings, and matched retrieval evidence where appropriate. Begin with three paired trials; require improvement on the declared metric without a material regression elsewhere. Treat inconsistent results as inconclusive and continue investigating.

A higher self-reported score or Elo rating alone does not establish improved scientific quality. Model judgments supplement observable evidence; they do not establish equivalence to expert or wet-lab validation.

**Tool additions:** verify a real response, parameter/error handling, provenance, and integration into a real workflow. A registered schema or mocked response alone is insufficient.

**UI changes:** exercise the affected flow in a browser, including loading, errors, refresh, and accessible interaction.

The authorized test boundaries are the API lifecycle and ownership interfaces, durable task execution/recovery, engine workflow outputs, LLM request boundary, retrieval/tool interfaces, report publication, and browser workflows. Record the applicable boundary for each candidate; no further interview is required.

### Required checks

Run targeted checks while developing. Before each code-bearing repository release, run:

```bash
make test-all
make lint
make typecheck
make build
make eval-smoke
(cd app/frontend && bun run test)
make e2e
```

Run `make test-sandbox-linux` when execution confinement or container behavior changes. Run applicable live evaluations with the verified free configuration. Reuse successful checks only when the relevant code, dependencies, configuration, and evaluation inputs are unchanged.

Do not weaken assertions, loosen evaluation thresholds, or add skips merely to obtain a passing release.

### Deployment

- Use a campaign milestone branch and commit after each completed item. Merge through a pull request after required checks pass; attach the PR to the task.
- Deploy only to the existing services. Record the commit, deployment IDs, non-secret configuration changes, and observed deployment status.
- Preserve the API’s single replica, required volume permissions, cache placement, and startup/recovery behavior.
- Use backward-compatible migrations. Verify a consistent backup before any migration touching persistent production data.
- Run the existing production smoke evaluator and exercise a campaign-owned public research goal through the deployed product.
- Disable notifications on campaign test runs. Do not alter other users’ runs or use their private documents as evaluation inputs.
- On failure, restore the last verified release and investigate. A rollback must retain the zero-cost configuration; never restore paid model settings as a recovery shortcut.
- Keep the release item open until the intended deployment is healthy and its required behavior has been observed.

## Cycle protocol

At the start of every turn, read `PLAN.md`, relevant project instructions, and the active dossier. Check the working tree and actual release state before acting.

Take the first unchecked item. Search the current codebase before implementing. Replace oversized implementation items with concrete candidate-ID checkboxes before starting them, preserving scope and acceptance criteria on disk.

Use `tdd` for behavioral changes and `ponytail` for minimal implementation. Commit after each item. Discovery and documentation items require concrete, checked evidence; implementation items require working behavior.

At milestone completion:

1. Run its `Done when` check.
2. Invoke the existing `end-of-work-cleanup` skill, including its scoped `deslop` pass and report-only UI scan where applicable.
3. Rerun checks affected by cleanup.
4. Append `— verified` to the milestone’s `Done when` line.
5. Add an architecture and release note to `## Log`.

A turn advances one milestone, or a few items within a large milestone. Resolve implementation ambiguities autonomously and log the options, choice, and reason. Do not reopen settled product decisions.

For transient limits, record the failed operation, reset/retry time, and remaining work. Continue independent work within the current milestone where possible. Never busy-loop requests or mark a blocked acceptance check complete.

End each execution turn with only the required status as its final content:

- Milestone table: name · done/open.
- Open-item count from a fresh grep.
- Next item, or the concrete blocker.

### Starting the loop

When implementation mode is enabled, save this plan as `PLAN.md`, commit it on the initial campaign branch, verify the fresh checkbox count, and return the goal prompt without starting the goal automatically.

This initial plan contains **60 open items**, giving **180 turns**. Recalculate before launch if the checklist changes. Subsequent discoveries may increase work; they do not silently increase the authorized turn limit.

```text
/goal `grep -cE '^[[:space:]]*- \[ \]' PLAN.md` prints 0 — every item in PLAN.md is checked and each milestone's "Done when" holds. Each turn, run /milestone. Stop after 180 turns.
```

## M1 — Free-model walking skeleton and trustworthy baseline

**Done when:** the existing research flow completes locally and in production using verified free models, required baseline checks pass, zero-cost enforcement covers campaign execution paths, and reproducible baseline artifacts are recorded.

- [x] M1-01: Establish campaign records, capture the starting commit and deployment state, and verify access to GitHub, Railway, Vercel, and OpenRouter without exposing credentials.
- [x] M1-02: Reproduce and correct the known disagreement between the live publication gate and release evaluator for speculative contradictions; add a behavioral regression test.
- [x] M1-03a1: Ensure catalogued zero-token-price OpenRouter routes carry zero prompt, completion and per-request price ceilings through the shared request builder, fallbacks and retries; preserve explicitly paid BYOK routing. Verify through the public LLM request boundary.
- [x] M1-03a2: Enforce fresh verified zero-cost eligibility at the shared LLM boundary, including unknown models, retries and fallbacks; preserve explicit BYOK. Reject paid/unknown/unverifiable campaign routes before transport, block charged add-ons, and verify eligible requests carry binding zero-price constraints. The static cap in M1-03a1 alone does not establish current free eligibility.
- [x] M1-03b1: Enforce shared zero-cost admission on app interview, Q&A, announcement, title and restatement completions and credential probes; verify outgoing requests, streaming/reasoning preservation and explicit BYOK isolation.
- [ ] M1-03b2: Verify zero-cost admission and credential isolation through durable task execution/recovery and auxiliary engine calls, including node-cache behavior; correct any bypass while preserving task lifecycle semantics.
- [ ] M1-03c: Audit retrieval, tools, plugins, skills and embeddings for metered paths; disable unverifiable or paid campaign capabilities and verify that remaining public-evidence workflows have usable free retrieval.
- [ ] M1-03d: Make campaign live evaluation runners use explicit verified free configurations without loading paid DeepSeek defaults or credentials; verify fail-closed routing, served-model/cost evidence, and matched baseline/candidate settings.
- [ ] Compare compatible current free OpenRouter candidates, including available new releases; select and document a primary and compatible free fallbacks using representative application tests.
- [ ] M1-09: Resolve the discovered release-evaluator safety gaps for absent/pending hypothesis statuses and final report screening: reproduce through publication interfaces, reuse live rules or enforce verified completed-artifact preconditions, and retain fail-closed safety behavior.
- [ ] Run the baseline verification suite and browser flow; resolve failures that prevent trustworthy campaign evaluation.
- [ ] Complete a local live run with public evidence through interview, retrieval, durable execution, recovery/reopen, and report publication; retain sanitized artifacts.
- [ ] Merge and deploy the free-model configuration and necessary support changes; verify actual serving configuration, production smoke checks, and a campaign-owned live run.
- [ ] Freeze the post-switch baseline, evaluation inputs, model settings, cache-isolation procedure, and release/rollback procedure for subsequent comparisons.

## M2 — Kaimen-Inc/Co-Scientist

**Done when:** its substantive mechanisms have recorded dispositions, all accepted changes pass their criteria and are deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [Kaimen’s repository](https://github.com/Kaimen-Inc/Co-Scientist); inspect implemented strategies, prompts, schemas, storage, tests, benchmarks, and licensing.
- [ ] Compare citation provenance, structured output, proximity, scheduling, model routing, and budget handling with current local behavior; distinguish shipped mechanisms from advertised or unfinished ones.
- [ ] Expand accepted candidates into concrete implementation items and complete them test-first, preserving the existing workflow and provider contracts.
- [ ] Run candidate evaluations, milestone verification, and cleanup; retain evidence for adoption, coverage, and rejection decisions.
- [ ] Merge, deploy, verify, complete the dossier and architecture log, and remove the temporary checkout.

## M3 — conradry/open-coscientist-agents

**Done when:** the archived implementation has been assessed against current code, justified improvements are verified and deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [conradry’s repository](https://github.com/conradry/open-coscientist-agents); inspect the framework, supervisor, model pools, research integration, monitoring, and licensing.
- [ ] Assess specialist-model assignment, action history, research synthesis, tournament inspection, and visualization; account for synchronous execution, in-memory state, and stated evaluation limitations.
- [ ] Expand and implement accepted candidates without importing the prototype’s durability or concurrency limitations.
- [ ] Verify each change against the current baseline, run release checks and cleanup, and document covered or rejected mechanisms.
- [ ] Merge, deploy, verify, complete retained documentation, and remove the temporary checkout.

## M4 — LLNL/open-ai-co-scientist

**Done when:** claimed and implemented behavior are distinguished, accepted improvements are verified and deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [LLNL’s repository](https://github.com/llnl/open-ai-co-scientist); inspect agent execution, UI lifecycle, artifacts, timeout handling, tests, and licensing.
- [ ] Compare failure visibility, cycle artifacts, model selection, hypothesis interchange, and scientific agent behavior; identify simplified or placeholder mechanisms.
- [ ] Expand and implement only candidates that improve a demonstrated local gap.
- [ ] Run behavioral and applicable live checks, release verification, and cleanup; preserve the assessment evidence.
- [ ] Merge, deploy, verify, finish the dossier and architecture log, and remove the temporary checkout.

## M5 — raktim-mondol/co-scientist

**Done when:** substantial scientific and operational mechanisms have recorded dispositions, accepted changes preserve Google-backed invariants and pass evaluation, and the release and cleanup are complete.

- [ ] Acquire and pin [raktim-mondol’s repository](https://github.com/raktim-mondol/co-scientist); inspect scheduling, research, evidence, reflection, ranking, proximity, feedback, experiment design, tests, and licensing.
- [ ] Compare ranking position bias, uncertainty-aware pairing, atomic rating updates, retrieval-failure handling, provenance, and review depth; explicitly assess differences from the paper-backed Elo system.
- [ ] Expand and implement accepted mechanisms while retaining documented Elo behavior and existing hypothesis lifecycle semantics.
- [ ] Run ranking, evidence, scheduling, and other affected evaluations; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve decisions and architecture notes, and remove the temporary checkout.

## M6 — K-Dense-AI/scientific-agent-skills

**Done when:** the catalog has a documented coverage assessment, each selected skill works through the existing harness with appropriate attribution and bounded dependencies, and the release and cleanup are complete.

- [ ] Acquire and pin [K-Dense’s repository](https://github.com/K-Dense-AI/scientific-agent-skills); inventory skill families, scripts, dependencies, selection metadata, and component licenses.
- [ ] Compare coverage against existing MCP tools and the vendored Google DeepMind skills; identify concrete domain or workflow gaps without conflating the two bundles.
- [ ] Expand and integrate justified skills or techniques through the existing selection, workspace, and confinement mechanisms; avoid wholesale catalog installation.
- [ ] Verify useful execution, dependency availability, provenance, context overhead, and affected scientific behavior; run release checks and cleanup.
- [ ] Merge, deploy, verify, update attribution and retained findings, and remove the temporary checkout.

## M7 — SakanaAI/AI-Scientist

**Done when:** applicable novelty and review techniques have been evaluated, reuse complies with the pinned source’s terms, accepted changes are deployed, and the temporary checkout is removed.

- [ ] Acquire and pin [Sakana’s repository](https://github.com/SakanaAI/AI-Scientist); inspect novelty search, review ensembles, experiment feedback, evaluations, and the actual source license.
- [ ] Compare applicable techniques with existing novelty, reflection, simulation, and reporting behavior; separate them from autonomous paper production and the removed discovery product.
- [ ] Expand and implement justified techniques through a compatible reuse route; do not copy restricted code under an assumed permissive license.
- [ ] Evaluate novelty/review improvements against fixed evidence and existing baselines; complete release checks and cleanup.
- [ ] Merge, deploy, verify, record evidence and attribution, and remove the temporary checkout.

## M8 — synthetic-sciences/openscience

**Done when:** relevant workbench and runtime mechanisms are assessed, accepted changes improve existing flows without adding a second runtime, and the release and cleanup are complete.

- [ ] Acquire and pin [OpenScience](https://github.com/synthetic-sciences/openscience); inspect sessions, request admission, events, permissions, artifacts, provider handling, tests, and licensing.
- [ ] Compare request receipts, idempotency, cancellation, capability discovery, provenance, and reconnect behavior with current durable tasks and authenticated SSE.
- [ ] Expand and implement accepted improvements within existing API and UI flows, preserving ownership and restart behavior.
- [ ] Verify retries, cancellation races, reconnects, artifact visibility, and affected browser interactions; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve the assessment and architecture notes, and remove the temporary checkout.

## M9 — mims-harvard/ToolUniverse

**Done when:** tool-system and catalog opportunities have recorded dispositions, accepted connectors or techniques work through the existing runtime, and the release and cleanup are complete.

- [ ] Acquire and pin [ToolUniverse](https://github.com/mims-harvard/ToolUniverse); map discovery, schemas, validation, errors, caching, composition, connectors, tests, and licenses.
- [ ] Compare its contracts and connector families with existing tools; inspect individual connectors where a concrete coverage or reliability gap exists.
- [ ] Expand and implement selected connectors or mechanisms without introducing a competing tool runtime; maintain free execution and explicit capability availability.
- [ ] Verify real connector behavior, failures, provenance, caching, and offline contracts; run applicable live checks, release checks, and cleanup.
- [ ] Merge, deploy, verify, preserve per-component attribution and findings, and remove the temporary checkout.

## M10 — Future-House/robin

**Done when:** applicable research-feedback mechanisms are evaluated, accepted improvements work without unauthorized paid dependencies, and the release and cleanup are complete.

- [ ] Acquire and pin [Robin](https://github.com/Future-House/robin); inspect candidate generation, trajectories, assay planning, analysis feedback, prompts, persistence, and licensing.
- [ ] Compare feedback from experimental findings, multi-trajectory synthesis, and experiment-design specificity with the existing hypothesis workflow; identify Edison-dependent behavior explicitly.
- [ ] Expand and implement justified mechanisms using existing compatible interfaces and available free services, without adding a separate experimental-execution product.
- [ ] Verify feedback propagation and affected scientific outputs with fixed public examples; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve findings and architecture notes, and remove the temporary checkout.

## M11 — Select justified additional references

**Done when:** every proposed additional repository has a recorded selection decision, no more than three are selected, and each selected source has a complete sequential milestone before final acceptance.

- [ ] Review the follow-up register and identify specific unresolved gaps that the nine required repositories did not adequately address.
- [ ] Select zero to three additional repositories based on distinct relevant mechanisms, accessible evidence, reuse feasibility, and the campaign boundaries; document exclusions.
- [ ] Insert one five-stage milestone per selected repository using the same acquire, compare, implement, verify, and release/cleanup contract; renumber final acceptance and refresh the open-item count without extending the turn limit.

## M12 — Final integration and campaign acceptance

**Done when:** all required and selected repositories are closed, no accepted or promising candidate remains unresolved, all applicable checks pass, the final intended release is healthy, and a fresh grep reports zero open items.

- [ ] Reconcile every candidate, milestone, source reference, attribution record, and acceptance result; resolve gaps rather than relabeling unfinished work.
- [ ] Verify the combined system across research generation, evidence, ranking, recovery, tooling, reports, ownership, and browser behavior using the final code and free-model configuration.
- [ ] Confirm intended commits and configuration are deployed, run final production smoke and public-goal verification, and establish the final known-good rollback point.
- [ ] Complete the campaign report with adopted improvements, rejected mechanisms, measured outcomes and limits; remove temporary checkouts and scratch artifacts, perform final cleanup, commit the closing records, and verify the checklist count.

## Log

**Decisions established before execution**

- Fidelity-led improvement is the objective; external implementations do not establish Google behavior.
- Existing UI and report flows may change autonomously; major redesigns and separate product modes remain out of scope.
- The current stack and hosting structure remain.
- References are investigated locally, one at a time, with durable findings retained after checkout removal.
- The nine named sources are mandatory and ordered; at most three additional sources may be selected.
- Additional spending is prohibited; free-model compatibility and zero-cost enforcement precede live campaign work.
- Promising but inconclusive candidates stay open for further investigation.
- Verified changes are merged and deployed after each repository.
- A repository may legitimately produce no changes when the assessment supports that conclusion.
- The initial limit is 180 turns. Reaching it with open work is an incomplete campaign, not successful completion.

**Cycle entry format**

Date and cycle number; milestone and item IDs; starting and resulting commits; actions and evidence; decisions with alternatives and rationale; architecture changes and connections; PR/deployment identifiers; free-model configuration and rate-limit state; remaining work and next action. Do not put checkboxes in this log.

### 2026-09-19 — Cycle 1, M1 in progress

Started at `927d2bd3` on `feat/external-m01-free-baseline` (preserves the trust-boundary documentation added after plan commit `cd54b76c`). Previous preparation made progress by committing the approved plan; this is execution cycle 1 of 180.

M1-01 complete: created source inventory, campaign procedures and baseline dossier with sanitized access and deployment snapshots under `references/external/`. Ignored sequential work checkouts. GitHub, Railway, Vercel connector and authenticated OpenRouter metadata reads succeeded; API health is healthy. All three services still serve `7dce086d`. No inference or production mutations. Local model settings are paid-route names; production selects a free-suffix model whose current pricing and availability remain unverified. Use Vercel connector reads after CLI token failure; do not interpret platform READY/health as scientific workflow acceptance. Campaign deployment authorization remains in force under the task's precedence over general confirmation guidelines.

Architecture: records now connect the authoritative checklist to source inventory, operational procedures, and dated sanitized deployment evidence. No runtime change yet. Next: M1-02, reproduce evaluator drift and reuse the live claim-role-aware predicate. Independent read-only review supports this approach. Full baseline and zero-cost qualification remain open.

M1-01 committed as `765288a6`. M1-02 then reproduced the defect with a failing public evaluator test (`withhold` instead of `release`) and removed its duplicated contradiction predicate in favor of the live helper's supplied-edge interface. Verification: 10 evaluator tests and 44 app publication/grounding/drain tests pass offline; targeted Ruff lint/format and mypy pass. Cleanup/deslop removed the obsolete helper; no UI changed. The preexisting Starlette/httpx deprecation warning is recorded, not suppressed. Production is unchanged; no PR or deployment yet.

The source audit split the oversized zero-cost item into M1-03a–d without changing its scope. Review found a separate legacy safety-status mismatch, recorded as M1-09; it is not bundled silently into the contradiction fix. App direct completions already reuse the engine's thinking/gateway body builder, so investigate actual outgoing requests before adding any abstraction. Unknown/free static pricing currently omits a gateway price cap. No live batch is authorized to run until enforcement and fresh price qualification hold. Fresh open count is 62 after two completions, a four-way split and one discovered item; the limit remains 180 turns. Next cycle starts with M1-03a. M1 acceptance is not yet satisfied.

Final independent review found no M1-02 blocker and confirmed the obsolete helper is fully removed. It also noted that evaluator artifacts cannot currently reproduce final rendered-report safety screening; M1-09 now explicitly includes that preexisting gap. All 44 targeted app checks had passed before accepting M1-02. No additional cleanup changes were needed.

### 2026-09-19 — Cycle 2, M1-03a1

Previous turn: progress, with campaign records and the verified evaluator correction committed. Current start is `0e3ae327`, clean branch. Fresh Railway read confirms unchanged API/MCP SUCCESS deployments at `7dce086d`; no release action this cycle.

Split M1-03a into the bounded request-ceiling correction (a1) and fresh eligibility enforcement (a2), preserving all acceptance requirements. Official OpenRouter provider-routing documentation supports inclusive zero token and per-request ceilings. Chose to fix the existing shared builder, rather than introduce another routing abstraction. The former zero-price early return was reproduced as three failing public-boundary cases. Now free routes send zero prompt/completion/request ceilings, including JSON budget escalation and tool calls; paid BYOK retains its existing priced route. A real LiteLLM serialization test with HTTP transport mocked proves the wire JSON preserves the cap. This is offline request evidence, not live pricing/serving evidence.

Verification: 61 engine routing/reasoning/BYOK tests, 19 app model/thinking tests, targeted Ruff lint/format and mypy, and diff checks pass using the root `.venv` (LiteLLM 1.80.17, httpx 0.28.1, pytest 9.0.3). Scoped cleanup/deslop removed contradictory comments and retained no extra runtime abstraction. SDK Pydantic and async shutdown warnings remain unsuppressed; no assertion was weakened. No UI changed.

Review execution incident: the read-only reviewer invoked `uv run`, generating `engine/uv.lock` and syncing the separate preexisting `engine/.venv` (46 packages installed, 43 uninstalled). Removed its confirmed generated lock; did not guess the previous package set. Root `.venv` is separate and unchanged, and all reported acceptance checks use it. Future checks use the existing root runner, never dependency-manager commands for read-only review.

Architecture: one shared provider block now carries the zero ceiling across all callers that already use it. Full model eligibility, unknown/paid route rejection, charged add-on control, app/tool coverage, and live comparisons remain open. No provider inference, credentials changes, PR or deployment. Next: M1-03a2. Open count remains 62 (one split adds one; a1 completion removes one); the 180-turn limit is unchanged.

### 2026-09-19 — Cycle 3, finish M1-03a1 review and commit

The preceding prompt-only handoff made no execution progress. Revalidated the
pending work against disk: cycle 2's a1 changes were still uncommitted at
`0e3ae327`. Completed its review before starting the next dependent item.
Railway read confirms API `a6ddd7f0-3bb5-4ad1-bed8-14809846e88e` and MCP
`0d49864d-782b-421f-ab8b-02b608a9c5d4` remain SUCCESS at `7dce086d`.

Review corrections: removed stale uncapped-free-route claims from pricing
comments; expanded the catalog assertion to standalone routes; exercised a
real tool-result continuation in the offline public-boundary test. Reused the
existing queued completion fixtures instead of duplicating them. Root runner:
61 engine tests and 19 app tests pass again; Ruff lint/format, targeted mypy and
diff checks pass. Existing SDK warnings remain documented. No inference,
production change, migration, or new dependency. Fresh eligibility remains
M1-03a2; the static cap is not a current-price qualification. The architecture
and release state recorded in cycle 2 otherwise remain unchanged.

Final fresh-context read-only review found no blocker and confirmed the fixture
simplification. M1-03a1 is ready for its item commit; M1 remains open. The next
cycle starts at M1-03a2. Fresh open count: 62; authorized limit: 180 turns.

### 2026-09-19 — Cycle 4, M1-03a2

Previous turn: progress, committed M1-03a1 as `367d8a22`; this cycle began with
a clean tree. Fresh Railway status still shows API/MCP SUCCESS at `7dce086d`
with unchanged deployment IDs. No inference, production mutation or PR.

Implemented current-price admission at the shared physical-completion boundary,
before moving the existing provider counter there from its three callers.
Exact model/fallback entries are checked against public catalog data cached for
60 seconds; expired evidence cannot survive refresh failure. Decimal prices,
text-only request scope and binding zero-price ceilings enforce the selected
contract. Campaign mode applies even to explicit credentials; ordinary BYOK
remains separate. No paid substitute is attempted. Declared the already-installed
httpx 0.28.1 as a direct engine dependency; no environment was synchronized.

Decision: listed :free variants with explicit zero token prices can use the
provider's documented free-inference contract for omitted ancillary fields;
other zero-price promotions need explicit ancillary rates. A suffix or missing
price alone is insufficient. Nonempty conditional schedules are unqualified
until their applicability can be established; this is not a permanent candidate
rejection. All selected fallback routes must pass, rather than silently deleting
unavailable ones. Full policy and source links are in the baseline dossier.

Review uncovered two admission bypasses: old paid BYOK cache entries skipped the
transport seam, and LiteLLM global aliases/fallbacks could reroute later. Both
were reproduced before fixing. Chose campaign-only LLM cache disable over a
second pre-cache admission implementation; ordinary BYOK cache behavior stays
intact. Rejected SDK routing overrides without modifying shared globals.
Malformed request/catalog structures now produce terminal policy errors rather
than retries. The engine test catalog is a synthetic external-boundary fixture;
it never replaces the policy under test or makes live network calls.

Verification: six initial missing/paid-price cases failed before implementation;
three cache cases, two SDK-route cases, six malformed-container cases and three
malformed-modality cases also failed before their corrections. All 429 LLM tests
passed before the final malformed-structure tightening; all 109 affected policy,
wire-format, budget, cache and wrapper tests passed afterward. Targeted Ruff
lint/format and mypy pass; existing LiteLLM Pydantic/shutdown warnings remain
unsuppressed. Scoped cleanup/simplification reused the shared cache and counter
instead of adding parallel machinery. No UI changed.

A real credential-free catalog request and the actual admission function found
447 entries, 22 metadata-qualified routes, and the deployed primary absent.
Retained sanitized evidence in `openrouter-eligibility-2026-09-19.json`; this is
metadata evidence, not an inference or capability result. Current production is
unchanged and M1 is not accepted. Next: M1-03b, wire and verify the same admission
policy in streaming/auxiliary app paths and durable tasks. Open items: 61;
authorized turn limit remains 180.

Final independent read-only review found no remaining M1-03a2 blocker after
confirming the request/cache/SDK protections and strict modality validation.

### 2026-09-19 — Cycle 5, M1-03b1

Previous prompt-only turn made no execution progress. Revalidated pending b1
work at `56684cbb` and completed its verification. Split b into app admission
(b1) and durable execution/cache isolation (b2) to preserve concrete boundaries.
Six red tests demonstrated paid campaign requests reaching app transports.
One shared app wrapper now applies existing engine admission to interview, Q&A,
announcement, title, restatement and credential probes. It preserves streams,
reasoning and existing retry/fallback behavior. Review's unscoped BYOK-flag
bypass was reproduced before removing the flag; credential probes instead use
the existing scoped credential context. This avoids a second provenance scheme.

Verification uses the root virtual environment and synthetic provider/catalog
fixtures, never live inference. Q&A tool continuation and interview reasoning
retry exercise repeated admission; forced-offline tests include restatements
and announcements. Scoped cleanup/deslop reused existing QA fixtures and removed
the redundant override. No UI changed. Full app mypy reports 21 errors in three
unchanged safety modules around the HypothesisSafetyReview alias; keep baseline
verification open to resolve these, with no skipped assertions or weakened rules.

Fresh Railway read: API/MCP still SUCCESS at `7dce086d`, deployment IDs unchanged
from cycle 4. No PR, deployment, new model selection, spend or live evaluation.
App request-boundary tests do not establish scientific or production acceptance.
Next: M1-03b2 durable execution/recovery, auxiliary calls and node-cache isolation.
The 180-turn limit is unchanged; M1 remains open.

Final result: 103 targeted app tests pass; Ruff and diff checks pass. Existing
six dependency deprecation warnings remain unsuppressed. Independent final
read-only review found no remaining app-admission blocker. M1-03b1 is complete
at the request boundary; its item commit records these changes. Fresh open
count: 61.
