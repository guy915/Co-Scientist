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
- [x] M1-03b2: Prevent campaign and credential-scoped executions from reading or writing shared node caches, including forced cache paths; verify isolation without changing ordinary cache behavior.
- [x] M1-03b3: Verify zero-cost admission and credential isolation through durable task execution/recovery and auxiliary engine calls; correct any bypass while preserving task lifecycle semantics.
- [x] M1-03c1: Map retrieval, tools, plugins, skills and embeddings to outbound paths and retained cost evidence; record concrete enforcement gaps and acceptance tests.
- [x] M1-03c2a: Prevent metered web-provider requests/fallbacks and credentialed OpenAlex billing in campaign mode at the standalone MCP provider boundary; preserve anonymous public retrieval and non-campaign behavior.
- [x] M1-03c2b: Qualify resolved MCP server/tool identities and enforce campaign restrictions on both direct and model-driven invocation paths, including custom configurations and availability probes.
- [x] M1-03c2c: Enforce campaign restrictions on workspace network execution and skill credential injection while preserving local computation; verify confinement including the Linux sandbox checks.
- [x] M1-03c3a: Correct the live-discovered PubMed availability mismatch: anonymous retrieval succeeds while the probe returns false before querying. Verify successful and failed actual reachability through the probe without treating a contact email as proof of availability.
- [x] M1-03c3: Verify real public-evidence retrieval through the guarded project interfaces using isolated credentials/configuration; record provenance, availability and rate limits without paid fallback.
- [x] M1-03c3b: Make Europe PMC and its preprint wrappers distinguish transport/parse failures from genuine empty searches through the public tool boundary; preserve failure provenance without paid fallback and verify existing callers handle it.
- [x] M1-03d0: Audit maintained live evaluation entry points, credential loading and evidence gaps; retain the concrete runner map and implementation boundaries.
- [x] M1-03d1: Isolate live scaling, ablation and claim-support runner configuration before app imports: require explicit free OpenRouter settings, prevent paid credential/default and dotenv loading, and verify fail-closed routing through the LLM boundary.
- [x] M1-03d2: Remove the golden runner’s paid configuration assumptions; preserve its INDRA-specific acceptance meaning and fail closed where campaign tool qualification cannot satisfy it. Provide the authorized public-evidence workflow for campaign acceptance without weakening the INDRA check.
- [x] M1-03d3a: Migrate live citation, citation-usefulness and Elo panels to explicit free configuration before app/engine imports; remove paid defaults and verify fail-closed admission without changing offline evaluation behavior.
- [x] M1-03d3b1: Preserve requested and observed model identity plus missing usage/pricing evidence in shared completion telemetry and durable metric merges; keep old checkpoints compatible.
- [x] M1-03d3b2a: Retain raw model telemetry and explicit unknown-cost/observed-model summaries in durable scaling, ablation, claim-support and golden artifacts without mistaking old zero estimates for verified costs.
- [x] M1-03d3b2b1: Capture direct citation/usefulness/Elo panel telemetry and explicit requested-live/offline modes; verify successful panel responses and observed usage through their public interfaces.
- [x] M1-03d3b2b2: Record explicit deterministic-fallback evidence for citation and ranking judgments in direct and durable artifacts, preserving legacy unknowns; verify fallback and no-fallback behavior without changing scientific decisions.
- [x] M1-03d4a: Persist reproducible per-arm identities for exact public inputs, resolved configuration, model roles, fallback/request policies and disabled response caches; retain them in comparison artifacts.
- [ ] M1-03d4b: Enforce matched baseline/candidate identities across comparison consumers and direct panels, allowing only declared tier/ablation differences; reject missing or mismatched evidence or rerun both sides, and specify matched retrieval requirements.
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

### 2026-09-19 — Cycle 6, M1-03b2

Previous turn: progress, committed app admission as `f400defe`; began clean.
Split the remaining b2 scope into node-cache isolation (b2) and durable/auxiliary
execution verification (b3), preserving all criteria. Reproduced four shared
cache leaks for campaign/BYOK contexts with and without force. The cache now
ignores reads and writes in those contexts; ordinary behavior remains covered.
Chose the existing credential ContextVar and campaign flag over a new namespace
because old entries carry no experiment or credential provenance.

Architecture: whole-node reuse can no longer skip campaign execution or share
BYOK outputs across runs. This complements the earlier LLM response-cache guard.
A literature-node regression observes source failure rather than stale success.
Seventy cache/storage/generation/literature-node tests, targeted mypy, Ruff and
diff checks pass. Scoped cleanup found no redundant runtime abstraction or UI
change. No live inference, spending, dependency installation, PR or deployment.
Fresh Railway status confirms API/MCP SUCCESS at `7dce086d`.

Read-only review traced recovery and auxiliary credential flow; it found no
structural bypass. Evidence and next behavioral tests are retained in the
baseline dossier. M1-03b3 stays open until worker-level and auxiliary admission
checks pass. Open count remains 61 after splitting and completing one item;
turn limit remains 180. M1 acceptance is still unverified.

### 2026-09-19 — Cycle 7, M1-03b3

Previous turn made progress: node-cache isolation committed as `dc73a822`.
Started clean. Rechecked durable dispatch, recovery and auxiliary call sites;
all already share the intended credential and admission boundaries. Added
worker-level behavioral evidence rather than another runtime wrapper.

Eighteen new cases exercise persisted credential reload, fresh and reclaimed
leases, child tasks and the off-loop/async bridge, across claim, batched claim
and semantic safety calls. Paid campaign requests stop before transport;
synthetic qualified free requests carry zero ceilings and the run's key;
ordinary paid BYOK remains separate. Recovered tasks increment their attempt,
complete, and leave no credential context behind. Admitted transport calls stop
at a test sentinel, so this is request/lifecycle evidence, not live inference
or scientific-quality evidence. No defect required a new runtime correction.

Forty-five worker/recovery/BYOK/bridge tests pass, with six existing dependency
warnings. Scoped cleanup extracted repeated outgoing-request assertions and
kept the test within lint complexity limits; all 18 new cases pass afterward.
Ruff and diff checks pass. No UI, dependencies or production settings changed.
Fresh Railway read shows API/MCP SUCCESS at `7dce086d`; no PR/deployment or spend.
Next: M1-03c retrieval/tools/plugins/skills/embeddings audit and free retrieval
verification. Open count: 60. M1 acceptance and the 180-turn limit are unchanged.

Final read-only review added an explicit assertion that ordinary paid BYOK
requests do not carry the campaign zero-price cap. All 18 cases pass with that
assertion, and targeted lint/format checks remain clean.

### 2026-09-19 — Cycle 8, M1-03c1 cost-path audit

Previous turn made progress: durable admission tests committed as `a44fc721`.
Started clean. Split c into evidence-backed audit, implementation and live
retrieval acceptance; no scope removed. Recorded source paths, current official
pricing references, seven concrete findings and required boundary checks in
`references/external/baseline/retrieval-cost-audit.md`.

Findings: web provider credentials/fallbacks, optional OpenAlex credentials,
custom MCP servers and skill credential injection escape the model-only guard.
Whole-node cache isolation is already handled. No embedding API exists in the
maintained app/engine path; semantic retrieval and proximity use guarded LLMs.
Official OpenAlex and Tavily docs confirm free allowances can coexist with paid
usage; no account billing guarantee was inferred. The separate read-only audit
confirmed both MCP invocation paths and configuration override routes.

Decision: use the existing campaign flag across upcoming enforcement rather
than a second opt-in that can leave partial protection. Qualify actual server
and tool identities, not just advertised names/effect labels. Keep local
computation and useful public retrieval, and preserve non-campaign behavior.
Implementation choices remain c2 work, to be driven by failing boundary tests.

No runtime files changed; source inspection and official documentation reads
only. No model/retrieval experiment, spending, dependencies, PR or deployment.
Railway status returned API/MCP SUCCESS at `7dce086d`; CLI also warned that token
refresh persistence lacked filesystem permission, but its read succeeded.
No credentials were printed or changed. Scoped documentation cleanup distinguishes
inventory from qualification and records remaining implementation/live evidence.
Next: M1-03c2. Fresh open count: 61 (split adds two; audit completion removes one).
M1 remains open, and the limit remains 180 turns.

Final independent audit review corrected the network-enabled workspace source
to `open_draft_workspace` (review workspaces default to network disabled), and
clarified that configured web search is conditionally registered at runtime.
These corrections are retained in the audit; no enforcement is claimed.

### 2026-09-19 — Cycle 9, M1-03c2a

Previous turn: progress, audit committed as `a3541dd2`; started clean. Split
provider enforcement, custom MCP admission and workspace confinement into c2a,
c2b and c2c without removing acceptance criteria. Four red tests reproduced
metered direct transport, provider/fallback availability and OpenAlex host-key
attachment under campaign mode.

The standalone MCP package now enforces the existing strict campaign flag before
metered web transport and provider selection. OpenAlex uses anonymous requests
with environment proxy routing disabled; 429 remains unavailable and does not
retry with a host key. Chose a small independent parser because this server is
packaged/deployed without the engine; no dependency or alternate flag added.
No arbitrary local result cap was added: anonymous access is bounded by provider
quota, with rate limits surfaced rather than paid fallback. Deployment must
explicitly configure the MCP service too; caller environment is not inherited.

Eighty-seven targeted tests and strict mypy on four changed files pass. Extra
coverage checks actual server startup registration, invalid values, normal keys,
quota failure and HTTP request serialization. Scoped cleanup uses existing HTTP
fixtures; no UI changed. Live retrieval/model capability remains unverified.
Fresh Railway read shows API/MCP SUCCESS at `7dce086d`; the same nonfatal CLI
refresh-persistence warning appeared. No deployment, PR, inference, provider
search, dependency installation or spending. Next: M1-03c2b. Open count: 62;
M1 stays open and the 180-turn limit is unchanged.

Final independent read-only review found no c2a blocker. All 18 new cases pass
after the final proxy-setting assertion; the other provider checks are unchanged.

### 2026-09-19 — Cycle 10, M1-03c2b

Starting commit `d3ba165b`. The intervening goal-prompt reply made no repository
progress; revalidated the pending implementation and resumed its red tests.
Two stale-client schema/availability tests failed before adding discovery guards.
The original direct/model rejection tests also failed before admission existed.

The client now binds one explicit operator-qualified reference endpoint and its
reviewed public tool set before discovery, then rechecks serving policy and
configuration before both invocation paths. Custom transports, multiple servers,
redirects and environment proxies cannot change that route. Registered server
calls enforce the same allowlist even if registered before campaign mode.
The server package remains independent of the engine; a cross-package policy
contract test catches drift without creating a runtime dependency.

Decision: use the existing caller/server campaign flag plus an explicit endpoint
binding, rather than infer trust from familiar tool names or arbitrary server
metadata. Metadata checks compatibility, not source authenticity. Operators must
verify our deployed revision and trusted network/TLS route. Every call rechecks
policy rather than caching it across potential deployment changes. No new tool
runtime or dependency was introduced.

Verification: 75 engine MCP boundary tests and all 264 standalone MCP tests pass;
strict mypy passes for the two changed engine modules and all 70 server files.
Ruff lint/format and diff checks pass. Scoped cleanup retained the small duplicated
wire-protocol constants because packages deploy independently; no UI was changed.
Evidence is offline, not live retrieval. No inference, provider search, spending,
PR or deployment occurred. Fresh Railway state: API and MCP SUCCESS at
`7dce086dd483831b40a12532a84cf7321f058e52`, deployment IDs unchanged from cycle 9.
Next: workspace confinement and skill credentials (M1-03c2c); live retrieval and
all milestone acceptance/release checks remain open. The 180-turn limit remains.

Final independent read-only review found no concrete admission bypass. Item
M1-03c2b is complete locally; its implementation and evidence are committed with
this cycle. Fresh open count: 61. M1 acceptance remains unverified.

### 2026-09-19 — Cycle 11, M1-03c2c

Starting commit `407c3a04`; previous cycle made progress by committing MCP
admission. Re-read the first unchecked item, code paths and cost dossier.
Reproduced real network access after campaign mode on both bounded and persistent
workspace commands, then enforced offline OS confinement at both launch paths.
Two local computations and a live loopback connection control distinguish actual
network denial from a sandbox that cannot launch commands.

Decision: scope the policy to workspace execution, rather than globally changing
all sandbox wrapping. The global option would reject trusted Git snapshot calls
and damage provenance; those are host-owned local operations, not model-authored
commands. Custom full-access/external workspace policies fail closed. Schemas
use the effective policy too, including old sessions. Remote skill instructions
are withheld; drafting keeps qualified MCP retrieval. Campaign commands receive
no skill credentials and record no unperformed source-query attribution.
Independent review found two stale-provider gaps; reproduced each before closing
old read_skill dispatch and skill attribution in an offline command.

No new dependency, runtime, reference checkout, inference or provider search.
Docker Desktop was stopped and was started for required Linux verification.
The initial nested macOS sandbox could not launch; elevated local tests proved
real confinement instead of counting that launch failure as a passing denial.
Fresh Railway read: API/MCP remain SUCCESS at `7dce086d`; no deployment or PR.
Final validation and commit are recorded below. Next item is real guarded public
retrieval (M1-03c3); M1 acceptance and release remain open.

Final verification: 87 affected macOS checks pass; strict mypy covers seven
changed modules; Ruff lint/format and diff checks pass. `make test-sandbox-linux`
passes with preflight-confirmed Landlock (133 passed, 3 existing platform skips)
and bubblewrap (132 passed, 4 existing platform skips). All seven campaign tests
also pass against each backend with the final tool-dispatch module mounted;
none of the new campaign checks is skipped. The scoped cleanup/deslop pass found
no unused code or scratch files in the change; no UI changed. Final independent
read-only review reports no remaining bypass. M1-03c2c is complete locally;
commit contains its implementation and evidence. Open count: 60. No free-model
selection, live retrieval, production acceptance or deployment is claimed.


### 2026-09-19 — Cycle 12, M1-03c3a and live retrieval

Starting commit `3bd22758`; cycle 11 made progress by committing verified
workspace confinement. Isolated local MCP and engine-client processes used
empty environments, dotenv disabled, campaign mode enabled, no credentials or
proxies, and temporary caches. Real searches for PMID 22745249/the matching
paper title returned one record each from PubMed, Europe PMC and OpenAlex.
Both direct invocation and a model-shaped tool envelope were exercised without
any model inference. The initial PubMed canary falsely returned unavailable
solely because the contact-email variable was absent, while retrieval succeeded.

Added M1-03c3a before implementation. Two behavioral cases failed: anonymous
success and anonymous transport failure must both actually query the service.
Removed the email prerequisite while retaining the actual canary and its failure
handling, and corrected the startup diagnostic. After restarting our isolated
server, the live probe returned true; a paid web-tool attempt was rejected before
execution. All 266 standalone MCP tests pass, strict mypy passes 71 files, and
the two new regression cases pass after formatting. No dependency or UI changes.
Scoped cleanup removed the now-unused os import; no generic probe harness added.
This correction is committed separately from the retained retrieval evidence.


Live retrieval evidence is retained at
`references/external/baseline/retrieval-2026-09-19/`, including exact results,
source IDs, DOI, abstract hashes, input queries, durations, serving policy,
filtered source status logs and the isolated experiment script. Independent
review approved the PubMed correction and bounded retrieval acceptance.
M1-03c3 is verified locally; no model inference or spending occurred. Discovery
also exposed Europe PMC's service-error/empty-result ambiguity; added M1-03c3b
rather than silently treating it as covered. Rate limiting was not observed and
is not claimed tested live. Production API/MCP remain SUCCESS at `7dce086d`.
No PR or deployment. After the evidence commit, next item is M1-03c3b; fresh
open count is 60. M1 acceptance and the 180-turn limit remain unchanged.


### 2026-09-19 — Cycle 13, M1-03c3b

Starting commit `b6eba783`; previous cycle committed the PubMed correction and
real public retrieval evidence. Re-read the current plan and failure paths.
Nine failing server cases reproduced false-empty and malformed-response behavior
across Europe PMC and its wrappers. Two failing engine cases exposed the legacy
MCP error text returning an empty dictionary and SDK errors being re-requested.
A separate failing HTTP429 case pinned preservation of Retry-After.

Decision: reuse SDK ToolException at the existing search boundary rather than
add a parallel error protocol. Source-labelled server errors carry status/retry
hints in text because that is what survives MCP serialization. Reported failures
are not immediately retried or broadened; genuine transport/decoding transients
retain bounded retry. Existing per-source exception handling retains diagnostics
while allowing healthy sources to finish. No paid fallback or new dependency.

Actual local MCP transport with an injected 429 returned the expected exception
and preserved its retry hint after exactly one source attempt. This was local
fault injection, not a live public-service quota event; no inference or external
provider request occurred. The temporary server was stopped. Retained evidence:
`references/external/baseline/europepmc-errors-2026-09-19.json`.

Final verification: all 274 standalone MCP tests and 34 affected engine tests
pass; strict mypy passes all 71 MCP files and the changed engine module. Ruff
and diff checks pass. Scoped cleanup removed the false-empty helper and duplicate
error logging; no UI changed. Independent final review approved the behavior and
retained evidence. Fresh Railway status remains API/MCP SUCCESS at `7dce086d`;
no PR or deployment. Item complete locally. Next: M1-03d evaluation-runner
admission and served-model/cost evidence. Fresh open count: 59; M1 remains open.


### 2026-09-19 — Cycle 14, M1-03d0

Starting commit `5b39e218`; the intervening goal-prompt reply changed no campaign
state. Revalidated the clean worktree, runner source and Railway deployment
metadata. API/MCP remain SUCCESS at `7dce086d`; no inference or release occurred.
Read-only independent review and direct inspection identify two credential
loaders, three paid panel defaults, independent Pydantic dotenv loading, and
missing served-model/comparison evidence. Retained audit:
`references/external/baseline/evaluation-runner-audit.md`.

Split M1-03d into concrete implementation boundaries before edits. Audit complete;
all configuration, telemetry, comparison and live acceptance work remains open.
Reuse the existing transport admission and telemetry rather than another pricing
or routing system. Do not require a :free suffix alone: a freshly verified
zero-price promotional route can qualify under the existing policy. Preserve
unknown observed costs as unknown; estimated zero is not a billing receipt.
Golden run requires INDRA, which campaign MCP does not admit; preserve that
check and use the authorized public-evidence research flow for campaign acceptance.
No runtime changes, dependencies or new reference acquisitions in this cycle.
Next: M1-03d1. Turn limit remains 180.

Independent final review found no lost scope and corrected the audit wording:
only scaling/ablation live modes require the paid key; offline modes do not.
Scoped documentation cleanup also corrected stale campaign procedure statements
about already-verified local controls, without claiming production qualification.
No runtime code changed; source cross-check and `git diff --check` pass.
Fresh open count: 62 (three additional unchecked items from the explicit split).


### 2026-09-19 — Cycle 15, M1-03d1

Starting commit `a16e3458`; previous cycle completed the runner audit and
implementation split. Revalidated the worktree and live Railway metadata:
API/MCP remain SUCCESS at `7dce086d`. No campaign inference or deployment.

Reproduced absent free-mode enforcement through a fresh-process shared-runner
test. Removed the DeepSeek disk loader and obsolete CLI key gates. Scaling,
ablation and claim-support now require explicit OpenRouter MODEL_NAME and an
environment OpenRouter key before app imports. A shared evaluation helper pins
all model roles, enables existing physical request admission, strips other API
keys and disables dotenv; app Settings now honors that disable flag. A second
failing subprocess exposed case-insensitive credential loading; removal now
also handles lowercase keys. Calls after app settings load are rejected rather
than pretending an already-configured process has been isolated.

The public call_llm test supplies synthetic catalog/provider responses: paid
metadata is rejected before transport, while a zero-price response carries
zero prompt/completion/request ceilings. This is behavioral verification, not
live model qualification or billing evidence. dotenv restoration and auxiliary
model isolation are exercised in fresh subprocesses with synthetic credentials.
No additional dependencies or pricing implementation. Golden/direct-panel
migration and telemetry/comparison evidence remain M1-03d2–d4.

Verification: 19 targeted evaluation tests pass, including offline ablation,
scaling and claim-support flows. Five configuration tests pass again after the
case-insensitive credential fix. Strict evaluator mypy passes four changed
modules; app config typecheck passes. Ruff lint/format and diff checks pass.
Independent read-only approach and final reviews found no blocking issue;
scoped cleanup removed the obsolete credential loader without unrelated changes.
No UI changes. Next: M1-03d2. Fresh open count: 61; M1 remains unverified.


### 2026-09-19 — Cycle 16, M1-03d2

Starting commit `23cdf92f`; previous cycle committed verified shared-runner
isolation. Fresh Railway metadata still reports API/MCP SUCCESS at `7dce086d`.
No model inference, upstream acquisition or deployment occurred.

The golden runner still hard-coded a DeepSeek key loader and allowed implicit
model defaults. Its INDRA requirement cannot be satisfied by campaign public
tools. Independent approach review rejected making it an always-campaign runner,
which would disable its distinct noncampaign purpose. Decision: retain explicit
noncampaign INDRA acceptance; reject campaign invocation before configuration,
run persistence or execution. No campaign opt-out was added.

A failing public-run regression proved execution began before campaign admission.
The corrected path rejects with an INDRA-specific explanation. Noncampaign
configuration now requires an explicit model and matching environment credential,
pins all model roles and never loads keys from disk. A second regression exposed
LiteLLM's import-time dotenv loading; dotenv is now disabled before importing
the engine policy, not merely before app Settings. Tests use synthetic keys and
stop before any execution or network request.

Provided the public-evidence acceptance procedure in campaign.md using existing
browser/API, persisted-run claim-support scoring and production smoke interfaces.
It includes interview, retrieval provenance, local recovery, event replay, report
publication and production observation. This is an execution procedure, not live
acceptance evidence; the corresponding M1 live items remain open.

Verification: five golden/shared-runner tests pass, Ruff lint/format and strict
golden-runner mypy pass. AST comparison confirms INDRA acceptance, real-completion
predicates and run-persistence logic are unchanged. Scoped cleanup removed the
obsolete DeepSeek loader and stale reproduction instructions; no UI changed.
Next: M1-03d3 direct-panel admission and observed usage artifacts. Open count: 60.

Final independent review approved the runtime behavior and identified two stale
procedure details. Corrected the scaling/ablation key requirements in the
evaluator README and named COSCIENTIST_DB_PATH explicitly for persisted-run
scoring. No remaining review blocker; diff check passes.


### 2026-09-19 — Cycle 17, M1-03d3a

Starting commit `bc8b73ff`; previous cycle completed golden admission/configuration
and the public-evidence procedure. Fresh Railway status remains API/MCP SUCCESS
at `7dce086d`. No live inference, spending, deployment or reference checkout.

Split M1-03d3 before implementation: panel admission now; observed usage, unknown
costs, deterministic fallback and missing provider identity remain M1-03d3b.
Three failing subprocess cases reproduced implicit-model acceptance. Reused the
shared environment configurator, returning its validated model and allowing an
explicit model argument for citation usefulness. Removed panel paid defaults.
Elo imports production rating math lazily so live configuration precedes engine
imports; the formula and comparison thresholds are unchanged.

Independent review found citation run's arbitrary-assessor injection bypassed
the configured factory. Repository caller search found no external consumers
of that argument. A failing public-run regression preceded replacing it with
`use_llm=True`, which constructs the admitted assessor internally. CLI and
programmatic live calls now use that same path. Offline behavior stays default.

Verification: 32 targeted tests pass (six panel rejection/import cases, existing
citation/usefulness/Elo cases and shared configuration/public LLM admission
tests). Strict mypy passes four changed modules; Ruff and diff checks pass.
The shared physical-boundary test uses mocked catalog/completion responses;
no test is claimed as a live scientific result. Positive panel response and
fallback/served-model artifact evidence remain part of M1-03d3b. Scoped cleanup
removed obsolete model imports/defaults and updated usage documentation. No UI
changes. Next: M1-03d3b. Open count: 60; turn limit unchanged at 180.


### 2026-09-19 — Cycle 18, M1-03d3b1

Starting commit `a3bc5fc7`; prior cycle committed panel admission. Split remaining
evidence work into shared telemetry fidelity and evaluator artifact integration
before implementation. No live inference or deployment. Railway status snapshot
retained locally at `/tmp/coscientist-cycle18-release.json`; production acceptance
remains open.

A failing public call_llm test reproduced missing requested/observed identity
evidence. Added additive observed_model_calls, reported_usage_calls and
priced_usage_calls plus requested_models counts. Positive counters deliberately
leave old checkpoints without observation evidence; calls minus each counter
identifies missing evidence. cost_usd remains a static estimate for compatibility,
not a billing receipt. A priced call requires observed model identity, explicit
valid prompt/completion counts and a static pricing entry. Failure attempts
retain requested identity without claiming observed usage or known cost.

Durable merge uses the existing count-map helper for request identities and
errors. Tests cover observed fallback, absent/blank identity, absent usage, a
known-zero estimate, provider failure, fan-out/checkpoint aggregation and legacy
records. Independent review found whitespace-only model identities created
bogus aggregate keys; a failing regression preceded normalizing that field.
No LLM output, prompt content, credentials or per-call database writes added.

Scoped cleanup reused the existing map merger and corrected the misleading
claim that unscoped telemetry was captured. Artifact consumers still need scopes
and explicit uncertainty/fallback handling in M1-03d3b2; they must not interpret
old numeric zero as proof of zero billed cost. No UI changes. Next: M1-03d3b2.

Final validation: all 88 targeted engine telemetry/runtime/model tests pass;
strict mypy passes both changed source modules; Ruff lint/format and diff checks
pass. Production API/MCP remain SUCCESS at `7dce086d`. Fresh open count: 60;
no milestone acceptance or live scientific result is claimed.


### 2026-09-19 — Cycle 19, M1-03d3b2a

Starting commit `1a425c99`; previous cycle committed observation telemetry.
Split artifact integration into durable summaries now and direct panel scopes/
fallback disclosure next. Preserved all original acceptance requirements.
No live inference, release, spending or reference acquisition in this cycle.

Failing artifact tests reproduced loss of raw usage, missing model identity and
unknown-cost evidence in golden/arm reports and derived scaling points. Added
a shared summary retaining raw snapshots, requested model counts, observed
model names and missing-evidence counts. Complete static estimates are null
for missing/legacy/incomplete telemetry; billed_total_usd remains null because
no receipt has been observed. Legacy numeric cost is explicitly labeled a
partial static estimate. Known-zero complete estimates remain zero.

Golden, arm metrics, scaling points, ablation paired records/summary means and
claim-support artifacts now retain the evidence. Persisted claim scoring labels
the configured backend without claiming that configuration proves a live call.
A missing cost value and impossible evidence counters each produced a failing
regression before being made incomplete rather than a complete zero estimate.
Reused existing store and evaluator interfaces; no schema migration or dependency.

Independent review found no dropped durable evidence or compatibility blocker.
Scoped cleanup consolidated partial-cost summation in the shared helper. Direct
panel response capture and deterministic fallback reporting remain unchecked in
M1-03d3b2b; no scientific result or billing observation is claimed. No UI changes.
Next: M1-03d3b2b.

Validation: 31 targeted evaluator checks pass, including offline durable scaling/
ablation flows and golden admission; persisted-run scoring retains the same
evidence. Strict mypy passes six changed modules; Ruff lint/format and diff
checks pass. Production API/MCP remain SUCCESS at `7dce086d`. Fresh open count:
60; the campaign and M1 acceptance remain incomplete.


### 2026-09-19 — Cycle 20, M1-03d3b2b1

Starting commit `e522e5f1`. The intervening goal-prompt reply made no campaign
progress; resumed from the current uncommitted panel changes. Split direct
capture from fallback instrumentation before further implementation, preserving
both requirements. This cycle completes capture only; no live inference,
spending, deployment or reference acquisition.

The initial failing usefulness public-path test exposed absent execution mode
and usage evidence. Shared scoped capture now wraps the citation assessor,
citation-usefulness judge and Elo comparator. Reused the durable usage summary;
no second accounting representation. Offline paths explicitly report offline;
requested live mode is not proof of an observed provider response. Elo labels
its deterministic controls separately. Scientific metrics and gates unchanged.

Successful public-path tests verify requested versus observed route identity,
unknown pricing, physical call count and outgoing zero-price caps. Citation
crosses the actual synchronous-to-async bridge; Elo crosses its per-match event
loop. Provider/catalog responses are mocked, not live scientific evidence.
Fallback behavior remains unverified and open in M1-03d3b2b2: instrument single
and batch claim deterministic substitution and invalid/tied ranking judgments,
retain events through durable merges, and preserve legacy tracking unknowns.
Do not interpret absent fallback records as proof that no fallback occurred.

Validation: 38 targeted panel/admission/artifact tests pass; strict mypy passes
four changed source modules; Ruff lint/format passes. Scoped cleanup reused the
existing summary and normalized imports. No UI changes. Production API/MCP
latest deployments remain SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`
(snapshot `/tmp/coscientist-cycle20-release.json`); campaign deployment acceptance
remains open. Next: M1-03d3b2b2. Open count: 60; turn limit remains 180.


### 2026-09-19 — Cycle 21, M1-03d3b2b2

Starting commit `92eb82aa`; preceding turn made progress by committing direct
panel capture. Reproduced absent fallback evidence through the public single
and batch claim interfaces and ranking judge, then added additive in-memory
substitution counts. Events use the requested model and do not create physical
calls or database writes. Single/batch claim judgments and invalid ranking
turns/tied vote resolutions retain their original decisions.

The shared metric reducer preserves event maps across fan-out/checkpoint JSON;
the evaluator summary retains recorded counts through direct panels and stored
run scoring. No-evidence batch skips and valid judgments emit no substitution.
Chose `recorded_events_only` rather than a completeness counter derived from
physical calls: several calls can produce one judgment, one batch can produce
several judgments, and old records have no tracking. Empty maps therefore
remain inconclusive, not proof of pure-model execution.

Public failed-citation panel test verifies that three failed physical attempts
produce one recorded substitution. Stored-run tests retain the same evidence
through arm metrics and claim-support scoring. Ranking tests cover valid JSON
without a prose verdict, malformed winner, and a position-balanced vote tie.
Independent approach/final review found no remaining disclosure blocker.

A pre-existing reasoning test failed admission because its mocked free model
had no qualifying metadata. Primary-only metadata also failed: admission checks
every fallback route. Reused the engine suite's synthetic full-route catalog
pattern, preserving the original reasoning assertions and avoiding live metadata.
No live model inference or scientific-quality claim. Scoped cleanup normalized
imports and count-map documentation; no UI or dependency changes.

Validation: 30 app and 32 engine targeted checks pass; 11 evaluator checks pass.
Engine changed-module type checks and evaluator type checks pass. App checking
still reports 19 existing safety type-alias errors in human_input.py and
hypothesis_screening.py, outside changed modules; baseline repair remains open.
Ruff and diff checks pass. Production state snapshot retained at
`/tmp/coscientist-cycle21-release.json`; no deployment performed. M1 acceptance
remains open. Next: M1-03d4, matched comparison identities. Open count: 59.


### 2026-09-19 — Cycle 22, M1-03d4a

Starting commit `933e459e`; preceding cycle made progress by committing fallback
disclosure. Split M1-03d4 into persistent identity capture and comparison
validation before implementation; no acceptance requirement removed.

Failing persisted-run and scaling-artifact tests reproduced absent frozen input
identities. Added one canonical manifest at persist_arm_run, shared by scaling,
ablation and claim-support. It contains exact goal identity, resolved config,
declared backend, configured model roles, production-rendered routing and
ordered fallbacks, request/reasoning policy source identities, selected process
flags and hashed tool settings. Deep-copied before attaching to run.config to
avoid circular/mutable records. Existing artifact provenance remains the source
for revision and prompt identities; observed models remain usage evidence.

Disabled response caching at comparison setup and scoped arm execution rather
than switching per-arm directories against a memoized singleton. Capture
rejects enabled caches. Tests verify stable repeated inputs, changed goals,
changed primary model and changed fallback list, rejection of enabled cache,
and persistence through real offline durable runs and artifact shaping.
Legacy scoring preserves missing identity as null. This does not prove matched
retrieval or comparable scientific results.

Independent approach/final review found no capture blocker. Scoped cleanup
corrected cache documentation and preserved score_run's missing-run behavior.
All targeted identity, scaling, ablation, environment, usage and claim-support
suites pass; strict mypy passes six changed source modules, Ruff/diff checks pass.
No live inference, external checkout, release or UI change. Production API/MCP
remain SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52` (snapshot
`/tmp/coscientist-cycle22-release.json`).

Next M1-03d4b must check manifest integrity, runtime drift and matched groups;
allow only declared tier/ablation differences; cover direct-panel dataset
identity and matched retrieval requirements. Missing or mismatched evidence
must prevent accepted comparisons. Open count: 59; turn limit unchanged.


### 2026-09-19 — Cycle 23, M1-03d4b (partial)

Starting commit `3fe71d5f`; prior cycle progressed through committed arm
identity capture. M1-03d4b remains unchecked: this cycle adds execution-boundary
drift checks, not cross-arm or direct-panel comparison acceptance.

Failing public-driver tests showed that missing/corrupt identities and changed
model settings still reached the worker. Added manifest version/digest validation
before scheduling and after completion. Reconstruction uses actual persisted
config, goal and backend, not the manifest's own frozen config. An independent
review caught that self-comparison risk before implementation. Repository search
confirmed durable execution does not write runtime config annotations: only the
identity field is excluded, so added/changed execution options cannot hide.
The original identity is held through execution, rejecting even a resealed
replacement. Boundary checks cannot detect a transient mutation restored before
the final check; observed usage remains separate evidence.

Tests exercise missing/corrupt identity and model/config drift before execution;
model/config/resealed-identity drift after the worker; and unchanged real offline
scaling/ablation workflows. No scientific decisions or thresholds changed.
Independent final review found no blocker. Scoped cleanup normalized imports and
formatting; no UI changes. Type checking of both changed source modules, Ruff
and diff checks pass. No inference, release or external checkout.

Production state snapshot: `/tmp/coscientist-cycle23-release.json`. Next remains
M1-03d4b: enforce cross-arm matching with declared tier/ablation differences,
cover direct-panel dataset identity and matched retrieval requirements, and
reject missing/mismatched comparison evidence. Open count: 59.


### 2026-09-19 — Cycle 24, M1-03d4b (partial)

Starting commit `448685c2`; prior cycle progressed by committing execution-boundary
drift checks. This cycle adds cross-arm validation; M1-03d4b stays unchecked
until direct-panel identities and matched retrieval requirements are handled.

Failing artifact-CLI tests reproduced acceptance of missing identities, different
goals and changed model roles. Added shared comparison validation used by scaling/
ablation drivers and the artifact CLI before results. Descriptors now retain
exact goal, tier and declared overrides. Shared model/routing/cache/policy
controls must match. Config differences must be the declared intervention;
scaling permits only the recorded tier profile. Froze baseline profiles and tier
field sets in the manifest instead of re-resolving old runs through today's
defaults, following independent review. Historical-profile tests verify this.

Review found duplicate arms could overweight aggregates and a baseline could
be relabeled as an intervention without applying its override. Both reproduced
in failing CLI tests before fixes. Validation now rejects duplicate goal/arm
entries, one goal under several labels, incomplete arm sets and unapplied or
unchanged declarations. Existing default ablations remain valid. No metric,
threshold or scientific gate was relaxed. The validation status explicitly says
matched declared inputs; retrieval remains not_verified. Repeated paired trials
use separate invocations, not invented independent-goal labels.

Validation includes group rejection/acceptance and historical-profile tests,
identity/drift regression suites and real offline scaling/ablation workflows.
Strict mypy passes six changed modules; Ruff and diff checks pass. Final review
found no further blocker. Scoped cleanup kept low-level metrics descriptive and
reused the canonical digest/manifest validator. No UI changes, model inference,
spending, checkout acquisition or deployment. Production latest API/MCP remain
SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`, snapshot
`/tmp/coscientist-cycle24-release.json`.

Next: finish M1-03d4b direct-panel dataset/model identity and comparison checks,
and define/enforce matching retrieval evidence where required. Open count: 59.

### 2026-09-19 — Cycle 25, M1-03d4b (partial)

Starting commit `28c053f8`. Previous goal work made progress in cross-arm
validation; the intervening user-facing goal-prompt answer did not change
execution state. Resumed the existing panel capture changes and confirmed the
previous test process completed successfully rather than restarting it.

Direct citation, usefulness and Elo reports now freeze ordered datasets,
requested models, evaluation mode, cache policy, wrapper/request-policy hashes
and routing before evaluation, with a post-evaluation drift check. Cache use
is disabled in the panel scope. The new panel comparison CLI rejects missing,
incomplete, wrong-kind and mismatched identities or inconsistent modes.
Failing CLI tests preceded implementation, including a resealed incomplete
manifest regression. Successful validation claims matched declared inputs only;
scientific acceptance still requires metrics and physical usage/fallback review.

Independent review proposed hashing production assessor/ranking code as an
identical control. Rejected that option because this code can be the scientific
candidate itself; source commits are retained with trial records, while evaluator
rubrics and request policy remain matched controls. This is a local design
choice, not a claim about Google's implementation.

Panel admission/usage/comparison tests: 17 passed, with synthetic physical
provider responses only. Strict mypy passes five modules; Ruff and diff checks
pass. Scoped cleanup reuses the existing canonical manifest validator and usage
capture, and introduces no dependencies or UI changes. No campaign inference,
spending, reference checkout or deployment. Railway snapshot
`/tmp/coscientist-cycle25-release.json` reports latest API/MCP SUCCESS at
`7dce086dd483831b40a12532a84cf7321f058e52`.

M1-03d4b remains open: define/enforce matched retrieval requirements for whole-run
comparisons and finish any remaining comparison acceptance gaps. Open count: 59.

Final review found no further correctness blocker. The existing citation,
usefulness and Elo regressions plus the comparison CLI tests pass (29 tests).
