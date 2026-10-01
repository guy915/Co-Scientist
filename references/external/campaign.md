# Campaign procedures

## Current execution state

Current state — 1 October 2026: all nine source assessments are closed; the campaign remains incomplete. [PR #88](https://github.com/guy915/Co-Scientist/pull/88) is the current verified release (`a7767153`), with [existing-service release evidence](m12-pubmed-batching-release-2026-10-01.json). Metadata batching and bounded recovery remain disabled by default in production. The [seventh novelty comparison](sakana/novelty-pilot-v7-terminal-2026-10-01.json) stopped on PMC fulltext HTTP400 after16 valid model responses and24 retrieval events; three of six pairs completed. All seven consumed comparisons are incomplete and unscored. The four original scientific/final gates remain open, with a bounded default-preserving fulltext opt-out correction and its release observation now recorded as preparatory items i1/i2 in PLAN. No further model qualification, replay or new comparison registration is authorized by this update.

### Historical preparation record through studies5–6

As of 1 October local time, all nine required source investigations are closed. The
[corrected Space Bunny screen](m12-space-bunny-corrected-result-2026-09-30.md),
[71-task public flow](m12-free-default-public-acceptance-2026-09-30.json) and
[17-task Robin continuation](m12-robin-continuation-acceptance-2026-09-30.json)
have recorded acceptance evidence, including their scientific limits. The four
original M12 gates concern result-conditioned novelty, its disposition,
candidate reconciliation and final acceptance. No further model qualification
is authorized. The third novelty study has its own
[frozen registration](sakana/novelty-result-conditioned-pilot-prereg-v3.json);
its [recorded result](sakana/novelty-pilot-v3-interruption-2026-09-30.json)
stopped on an upstream metadata-fetch error. All three admissions are consumed;
no replay or scientific disposition follows from those interruptions.
The separately registered fourth study completed its operational preparation:
[protocol4](sakana/novelty-result-conditioned-pilot-prereg-v4.json), fresh bank5,
independent review, committed loaders and actual credential-free MCP/CLI preflight.
Its [sole admission stopped incomplete](sakana/novelty-pilot-v4-terminal-2026-09-30.json)
after 13 model responses and 19 outer searches. Both permitted EFetch 429 recoveries
succeeded; a later ELink 429 exhausted the two-retry study ceiling. All four
admissions are consumed, with no scientific scoring, replay, adoption or rejection.
Original scientific thresholds and four acceptance gates remain unchanged.
The [request-volume audit](sakana/novelty-study4-retrieval-audit-2026-09-30.json)
and [batching feasibility review](sakana/novelty-pubmed-batching-feasibility-2026-09-30.json)
support a default-off, bounded metadata/PMC-link batching path. PLAN f1/f2 are
closed by [offline implementation and independent verification](sakana/novelty-pubmed-batching-verification-2026-09-30.json):
371 MCP tests, strict typing and preserved legacy studies/full-text downloads.
The code remains unreleased. The separately registered fifth comparison
[was admitted once](sakana/novelty-pilot-v5-launch-2026-09-30.json), then
[stopped incomplete](sakana/novelty-pilot-v5-terminal-2026-09-30.json) after 14
zero-cost model responses and 21 outer searches. The last search was empty with
no recorded upstream error; strict raw-trace validation passed, but returned-link
validation falsely demanded batching metadata despite zero returned papers.
No arm scoring, scientific disposition, confirmation or replay is authorized.
All five admissions are consumed. The [offline empty-result guard repair](sakana/novelty-empty-result-guard-verification-2026-10-01.json)
passes 89 runner and 26 reader tests and independent review, retaining all nonempty
link and upstream-error proof requirements. It does not authorize another bank or run.

The [strict batch reader](sakana/novelty-batch-reader-verification-2026-09-30.json)
now passes 26 offline tests, including the maintained public-tool producer with
one metadata batch and two PMC pages. Its exact metadata proof excludes search,
full-text and recovery from savings; it makes no total-request or page-completeness
claim. [PLAN f4 integration](sakana/novelty-batch-pilot-integration-verification-2026-09-30.json)
now routes prospective v5 traces through that reader and validates a non-executing
outside-repo draft preflight; 88 runner tests pass. Actual execution still requires
an unchanged committed bank6/protocol5 with a distinct exclusive admission, and
[f5 preparation and committed loaders](sakana/novelty-pilot-v5-registration-verification-2026-09-30.json)
now pass with the real isolated CLI/MCP preflight. Source review verifies all twelve
primary records and finite-set disjointness against 644 prior IDs; selection is exploratory.
The preflight process is stopped. F6 rechecked the exact current free route/account,
attested a fresh isolated MCP, and consumed its sole admission; both live PIDs and
listener are now absent. Historical records and assertions are unchanged; their exact original runner is retained in Git. Strict typing of
new tests passes, with inherited whole-reference diagnostics explicitly retained.
The [required maintained-code checks](m12-batching-release-checks-2026-09-30.json)
passed on pinned product trees; they do not establish live scientific acceptance.

The registered v5 comparison uses the strict batch reader to validate records
instead of historical per-ID call-count assertions:

- Pin the opted-in producer and versioned reader before admission; retain all four historical registrations and consumed markers unchanged.
- Require every selected PMID to have resolved metadata and an unambiguous `pubmed_pmc` link outcome, or a digest-verified cache origin; reject fetch errors, missing mappings and truncated proof.
- Reconcile each batch's inputs, cache hits, EFetch requested/returned IDs and actual ELink subset with per-record provenance, search order and retained artifacts. The batch bound is nine; sampled traces cannot prove an unsampled record.
- Verify that logical request counts and separately counted client attempts cover actual batches, search and unchanged full-text downloads. Never describe these as wire-level HTTP counts or infer scientific reliability from request-volume savings.
- Preserve the scientific metrics, model settings, zero-cost checks, isolation, blind labels and outer/model call caps. Any retrieval recovery policy needs prospective bounds; batching adds no retries. A new comparison needs its own source preparation and exclusive admission, without replaying exposed studies.

The [protocol5](sakana/novelty-result-conditioned-pilot-prereg-v5.json) and
[bank6](sakana/novelty-fixture-bank-prereg-v6.json) are committed together before
admission. Their metadata-only preparation does not authorize scoring partial results
or close scientific gates. The f4-v5 registry labels are the fixed workflow-integration
anchor; f5 prepares and f6 executes study_version5. No historical replay follows.

The corrected runner now supports a distinct study6 registration, verified by the
[dispatch checks](sakana/novelty-study6-dispatch-verification-2026-10-01.json).
Its [bank7 source review](sakana/novelty-v7-source-review-2026-10-01.json) checks
twelve fixed papers against the finite 818-ID prior exposure set; the separate
958-ID manifest includes current discovery for future exclusion. Two draft scope
errors were corrected before performance queries. The [actual process preflight](sakana/novelty-pilot-v6-process-readiness-2026-10-01.json)
passed with no credentials, scientific calls or admission; its process and listener
are stopped. Protocol6/bank7 registration and committed-loader proof are recorded
separately. Preparation establishes no scientific gain and authorizes no historical
replay. Study6 requires fresh free-route/account/process checks before its one
admission; all five interrupted studies remain unscored.

The release recorded before studies6–7 was [PR #80](https://github.com/guy915/Co-Scientist/pull/80),
`73459c6c85726864c97a1b4aa28cb184bfca9976`, with healthy existing-service
deployments and 5/5 keyless smoke. Its reference-only changes preserve PR #79
product content. See the
[release receipt](m12-reference-evidence-release-2026-09-30.json) and
[rollback reconciliation](m12-current-release-reconciliation-2026-09-30.json).

### Historical M1/M2 decisions

M1's model-testing loop ended at the user's direction on 2026-09-22. The
[free-model decision](baseline/model-choice-2026-09-22.md) selected Nex Pro from
then-current official pricing/capability metadata and retained local results, with no
automatic unqualified fallback. The [qualification inventory](baseline/model-qualification/README.md)
retains successes, failures and inconclusive alternatives without new trials.
Guarded anonymous retrieval was verified [locally](baseline/retrieval-2026-09-19/README.md).
One M1 public-goal run reached interview, retrieval, verification and ranking;
it was paused before report publication and is partial evidence only. The M1 code
passed the retained [release checks](baseline/release-verification196.json).
PR [#22](https://github.com/guy915/Co-Scientist/pull/22) merged at
`0d2fec9804d3d2179c7c492922ac31d71b514065` on 2026-09-23 after the user
explicitly waived the GitHub CI gate, which failed before running because of an
account hold. The full local release suite and independent review passed;
GitHub CI did not pass. On 23 September, the user extended this exception to
subsequent campaign merges while GitHub Actions jobs fail before execution on
an account hold. Required local checks and review still run; each release must
record that hosted CI did not pass. The [M2 staging record](baseline/m2-production-staging.md)
and [production run record](baseline/m2-production-run.json) track that historical
deployment and bounded public-goal verification. The Kaimen milestone closed
after these checks and removal of its temporary checkout. The bounded run did
not return a provider response or publish a report, and claims neither result.

Starting branch: `feat/external-m01-free-baseline`; execution starts at
`927d2bd3a0f8480833661ff3a83b8c3549a6e85f`. The plan was committed at `cd54b76c`.
The intervening deployment-trust-boundary documentation is preserved.

## Verification

Target the changed public boundary during development. Before release run:

```bash
make test-all
make lint
make typecheck
make build
make eval-smoke
(cd app/frontend && bun run test)
make e2e
```

Run `make test-sandbox-linux` for confinement/container changes. Release also
requires the existing production smoke evaluator and a bounded public flow when
the accepted change needs live workflow evidence. Inspect diagnostic probes
before calling them: a read endpoint
may itself use a metered retrieval provider.

Scientific comparisons require a declared primary metric and non-regression
criteria, three initial paired trials, identical model configuration and fixed
evidence where appropriate. Freeze exact inputs, hashes, selected models, and
isolated cache locations for scientific comparisons. Do not restart M1 model
qualification or claim the paused run completed.
Do not reuse an old result after relevant code/configuration/input changes.

## Inference and isolation

Do not trust ambient credentials or evaluation-driver defaults. Historical local
settings included paid routes; the selected current route and its role overrides
are recorded below, but every campaign process still needs explicit admission.
Before inference, enforce zero-cost routing across engine, app, tools and runners;
verify current applicable prices from OpenRouter. Unknown prices are unavailable.
Preserve explicit user BYOK separately. Disable paid tools/plugins and notifications
for campaign runs. Do not load private documents or other users' run data.

Record actually served models and live versus offline evidence explicitly.
Record rate-limit reset times and resume later; never substitute paid models.

## Release and rollback

Use the existing three services only. Preserve one API replica, root UID on its
volume, off-volume cache, and durable startup/recovery. Merge via PR after required
local checks and review; attach it to the task. The user explicitly waived
GitHub CI for campaign merges while its hosted jobs fail before execution on
an account hold. This does not waive deployment verification. Record exact
commits, deployment IDs and health.
The [initial deployment snapshot](baseline/releases-2026-09-19.json) is a starting
reference, not a verified zero-cost rollback target. Current source rollback
points and dated backup evidence are distinguished below.
Never restore paid routing on rollback. Verify a consistent backup before any
persistent-data migration. The campaign explicitly authorizes required merges
and deployments; routine implementation choices do not require re-interview.

The current known-good source point for future releases is
`a4a06abd723f8af8392a307457301837b15dc244`. If reverting the trace-support
release itself, the preceding verified recovery source is
`8bb80e28f141e7a78727cfce18fb322efb2819bb` (PR #78). These are different
uses of a rollback point; do not describe redeploying the current source as
reverting PR #79. Both preserve the selected zero-cost role overrides and
leave production tracing disabled. The earlier `ef9684ab` rollback in PR #77's
receipt applies to that older release, not the current recovery instruction.
No rollback or configuration mutation occurred during reconciliation.

The historical M8 production anchor was [PR #35](https://github.com/guy915/Co-Scientist/pull/35),
merge commit `6a9baa9ef8a233ac251085dd26781ac356ef0563`. Its
[OpenScience dossier](synthetic-sciences-openscience.md#final-m8-release-and-architecture)
records successful Railway/Vercel deployments, the live additive receipt schema,
smoke checks, and the bounded owned create/replay/conflict probe. The consistent
[pre-M8 backup](openscience/m8-production-backup.json) is retained for separately
justified data recovery; ordinary code rollback should preserve the additive
schema and current zero-cost routing. Hosted GitHub Actions did not run
successfully for this merge under the existing user waiver.

The [PR #77 role readback](m12-free-default-release-2026-09-30.json) records
`MODEL_NAME=SUPERVISOR_MODEL_NAME=CHAT_MODEL_NAME=SEMANTIC_SAFETY_MODEL=openrouter/stealth/space-bunny-alpha`;
`CLAIM_VERIFIER_MODEL` and the global free-mode setting were unset. System-default
zero-cost policy preserves explicit BYOK separately; BYOK encryption was observed
disabled, not enabled by this release. PR #79 made no configuration changes and
did not reread secret-bearing variable values. The exact role readback is therefore
dated evidence, not a fresh runtime attestation on every later commit. Recheck
official catalog and sole-endpoint zero pricing before each permitted live batch;
unknown prices, unavailable routes and paid substitutions remain prohibited.

The historical M2 release's system-default configuration was
`MODEL_NAME=SUPERVISOR_MODEL_NAME=CHAT_MODEL_NAME=SEMANTIC_SAFETY_MODEL=openrouter/nex-agi/nex-n2.5-pro:free`;
`CLAIM_VERIFIER_MODEL` remains unset and inherits `MODEL_NAME`. This route has
no model-level fallback, and its requests retain zero-price ceilings. The
pre-switch production readback on 23 September showed four explicit old
MiniMax values; all four then served the selected Nex Pro route. The dated catalog
marked this free route as expiring 25 September 2026 (see the
[dated receipt](baseline/nex-pro-catalog-2026-09-23.json)). Recheck current
eligibility before each live batch; if the route retires, stop live calls and
select an exact zero-priced replacement from current public information and
retained compatibility evidence. No unqualified automatic or paid substitution.

### Engine zero-cost admission

Set `COSCIENTIST_REQUIRE_FREE_MODELS=1` for campaign inference processes. This
forces current-price admission even when a runner explicitly supplies a key;
it disables the LLM response cache so every campaign completion reaches that
admission boundary. App completions, node caches, durable tasks and qualified retrieval/workspace
paths now have locally verified campaign controls (M1-03b/c). Evaluation-runner
configuration and evidence controls are verified in M1-03d; see the
[runner audit](baseline/evaluation-runner-audit.md). These local controls have
not yet been deployed or verified through a full live research run.

Outside campaign mode, system `:free` requests still use current-price admission;
explicit/scoped user BYOK remains separate. Catalog evidence expires after 60
seconds and cannot be reused on failed refresh. A catalog fetch is not inference
and can be used to assess availability without spending model credits. A
`FreeModelEligibilityError` is terminal for that LLM request: change/qualify the
configuration or wait for metadata availability, never substitute a paid model.

### Retrieval qualification status

The [retrieval cost audit](baseline/retrieval-cost-audit.md) maps outbound routes
and retained cost evidence. M1-03c2/c3 now cover local provider restrictions,
MCP identity admission, workspace confinement and real anonymous public retrieval.
The caller and server controls are deployed on the merged commit, and the
campaign-owned production run recorded an authenticated MCP connection and tool
registry. Evaluation-runner isolation and model qualification were verified
locally before campaign inference. No paid retrieval route was enabled.

### MCP qualification

Before campaign tool use, verify the endpoint is our reference MCP deployment
at the intended campaign commit, then set `COSCIENTIST_CAMPAIGN_MCP_URL` to its
exact `/mcp` URL in the caller. The resolved MCP configuration must contain only
that one streamable-HTTP server and its existing shared-secret header, if used.
The authenticated campaign marker enforces the free policy on MCP requests;
leave the global flag unset in these shared services to preserve explicit BYOK.
Deploy/verify the MCP policy before enabling caller admission. An old production
server lacking the policy must fail admission; do not qualify it by tool names.

Policy metadata is a compatibility check on an independently trusted endpoint,
not cryptographic source attestation. Public transport must use HTTPS; local
loopback and the existing Railway private network can use HTTP. No redirects,
environment proxies, custom transport factories or additional servers are
admitted. Each call checks the live policy; a missing or changed policy prevents
execution. Retain exact serving revision/configuration in release evidence.

### Workspace execution

Campaign mode forces workspace processes offline and rejects unverified external
or full-access sandbox policies. Both bounded and persistent launches check the
current flag, so reusing an older online workspace does not preserve egress.
Start campaign processes with the flag already enabled; do not toggle it around
an already-running command. Skill credentials are omitted and remote skill
instructions are withheld; scientific retrieval goes through qualified MCP.
Local calculation, file operations and trusted Git provenance remain available.
Run `make test-sandbox-linux` after changes here; its preflight must prove a
working backend before denial assertions can count as confinement evidence.

### Shared live evaluation configuration

Scaling, ablation and claim-support live runners require a fresh process with
explicit `MODEL_NAME=openrouter/<qualified-model>` and `OPENROUTER_API_KEY`
supplied in the environment. They no longer read provider keys from disk.
All model roles use that selected model, other API keys are removed, and dotenv
loading is disabled before app imports. The request boundary checks fresh
prices and fallback eligibility on every call; supplying a name alone does not
qualify it. Existing MCP qualification is still required for retrieval.

Regression evidence: `evaluations/tests/test_live_runner_config.py` exercises
subprocess isolation, dotenv suppression and the public LLM boundary using
synthetic credentials and mocked catalog/completion responses. This does not
qualify a live model. Golden and direct-panel migration, observed-model/cost
artifacts and comparison identities are verified under M1-03d. Full workflow
acceptance still requires the selected qualified model configuration.

### Public-evidence acceptance workflow

This procedure uses existing product interfaces; execution remains pending until
M1 model qualification and runner evidence controls pass. It does not substitute
for the separate INDRA golden acceptance, which campaign mode rejects.

1. Start an isolated local API, UI and reference MCP at the campaign revision,
   with fresh SQLite/cache paths and the same qualified model settings on all
   roles. Enable campaign mode on both API and MCP; disable dotenv and supply
   only the required OpenRouter credential and existing MCP authentication.
   Qualify the exact MCP endpoint using the procedure above. Keep notifications
   disabled and use a campaign-owned identity with no uploaded documents.
2. In the browser, submit the public research goal: “What testable mechanisms
   explain acquired resistance to EGFR inhibitors in EGFR-mutant lung cancer?”
   Complete the interview, retain its final research specification, and start
   the express research flow. Record the exact inputs before comparisons.
3. Observe actual public retrieval, durable task progress and authenticated
   event replay. Pause/resume and reopen the campaign run; for local recovery,
   restart only the isolated API while preserving its database. Confirm work
   resumes without duplicated lineage. Never restart production for this test.
4. Retain sanitized `/api/runs/{id}/evidence`, `/claim-evidence`, `/metrics`,
   `/tasks`, `/events` and `/report` responses plus report Markdown under the
   baseline directory. Inspect source identifiers and nonempty quoted passages;
   require a completed real-backend run, published report, safety/claim gates,
   observed model/price evidence and functional browser refresh/error flows.
   Offline output, a queued task or an empty report does not satisfy acceptance.
5. Score the isolated run using `evaluations.claim_support_eval --run <id>`
   with `COSCIENTIST_DB_PATH` set to the isolated database path and
   `PYTHON_DOTENV_DISABLED=1`. There is no database CLI argument. That existing-run
   scoring path is read-only;
   retain raw artifacts alongside its score. A score alone does not establish
   scientific quality. Use the existing release gate and other applicable
   evaluators; resolve failures under M1 rather than lower thresholds.
6. After merge/deployment, run the existing production smoke evaluator and a
   bounded campaign-owned public flow appropriate to the accepted change.
   Record deployment IDs, serving configuration and actual observed behavior.
   A smoke check alone does not prove a full research run published; preserve
   that limitation explicitly when no completed run is observed.

The M1 interview and partial local run are retained separately. The merged
production run uses the frozen four-role Nex Pro route and a distinct public
PETase goal; its observed stages are recorded in
`baseline/m2-production-run.json`. This is release-path evidence, not a paired
scientific-quality result or proof of report publication.

Direct citation and Elo panels now share the same isolated configuration. Elo
loads production rating math lazily so importing its evaluator does not load
engine/provider settings before live admission. Citation usefulness accepts an
explicit model argument or MODEL_NAME; both pass the same OpenRouter validation.
Direct capture and deterministic-fallback disclosure have been verified. The
Nex Pro usefulness screen is accepted with retained physical request evidence;
the ranking screen is also accepted. Nex Pro now passes the fresh multi-claim
schema series and all three post-Q1/Q2 scientific trials. Overall model
qualification remains open for an independently qualified fallback. See the
[qualification status](baseline/model-qualification/README.md) for current receipts.

### Usage evidence semantics

Shared telemetry retains requested model counts separately from its response-model
aggregate key. `observed_model_calls` counts explicit nonblank response identities;
`reported_usage_calls` counts explicit valid prompt/completion token totals;
`priced_usage_calls` additionally requires an observed model with a static pricing
entry. Subtract each counter from physical `calls` to identify incomplete evidence.
Old checkpoint fields default to zero evidence, not retrospective verification.
`cost_usd` remains a legacy static estimate and is never a billing receipt.
Evaluator artifacts must expose these distinctions under M1-03d3b2 before live
results can serve as campaign evidence.

Durable golden/arm, scaling, ablation and claim-support artifacts now retain
`usage_evidence`, including raw snapshots and requested/observed identities.
`estimated_total_usd` is null when evidence is incomplete; `billed_total_usd`
is always null until an actual receipt is retained. Legacy numeric cost fields
are labeled `partial_static_estimate`. Derived ablation estimated means are
null if any included arm lacks a complete estimate. These fields are static
accounting evidence, not proof of scientific quality.

Citation, citation-usefulness and Elo public live panel entry points now capture
physical calls into the same summary. `execution_mode=live_requested` records
intent, while observed model and usage fields record provider response evidence;
it does not claim that every verdict came from a model. Offline panels have
`execution_mode=offline` and null usage evidence. Elo labels its three offline
controls separately and attaches captured evidence to its live comparator.
The successful-path tests use synthetic provider responses, including citation's
async bridge and Elo's per-match event loops. They are not live evaluations.
Deterministic substitutions now appear as `recorded_deterministic_fallbacks`
in these summaries and in persisted-run artifacts. Events are keyed to the
requested model: `claim_single` and `claim_batch` count substituted claim
judgments; `ranking_invalid_turn` counts invalid turns and `ranking_tied_votes`
counts matchups resolved by the deterministic tiebreaker. A matchup may contain
both kinds. Events do not increment physical calls. A batch with no retrieved
evidence makes no call and emits no substitution event.

`fallback_evidence=recorded_events_only` is deliberately not a completeness
claim: an empty event map does not prove absence of fallback, especially for
legacy records or other uninstrumented mechanisms. Inspect judgment provenance
and raw artifacts when accepting scientific results; never label a whole run
pure-model solely because this map is empty. This instrumentation does not alter
claim verdicts, ranking winners, safety gates or their acceptance thresholds.

### Controlled arm identities

Scaling, ablation and claim-support arms retain `evaluation_identity` in the
persisted run configuration and exported artifacts. Version 1 records the exact
goal hash, resolved run configuration, declared backend, configured model roles,
production-built gateway routing (including ordered fallbacks and reasoning
modes), request-policy source hashes, tool configuration identity and selected
execution flags. Canonical JSON supplies its digest. Credentials are not part
of the record; tool paths/endpoints and local tool-file contents are hashed.

These are declared inputs, not observed serving or retrieval results. Model
responses remain in usage evidence; retrieved material must be retained or
replayed separately when matching evidence is part of the experiment. The
existing artifact provenance retains revision and prompt-template identity.

Comparison drivers disable response caching before imports and scope caching
off during arm execution, covering an existing cache singleton as well. Identity
capture rejects an enabled-cache configuration. Missing legacy identities remain
null when scoring old runs; they are not reconstructed after execution.

M1-03d4b remains open: validate identity integrity and comparison groups, check
for runtime configuration drift, allow only declared tier/ablation changes,
include direct-panel dataset identities, and reject missing/mismatched records
before accepting a comparison. The presence of a digest alone is not acceptance.

The durable driver now verifies manifest integrity and current persisted
controls before enqueueing and after the worker returns. It retains the initial
manifest to reject a replacement even if its digest was recomputed. The checks
bind the actual stored config, goal and backend to the current model/routing/
policy environment. A mismatch raises before an arm result is emitted; rerun
both members of a scientific pair after restoring the intended settings.
These boundary checks do not prove absence of transient changes between checks.
Cross-arm and direct-panel matching are verified in M1-03d4b; the additional
cross-goal intervention consistency check is verified in M1-03d4c.

Scaling/ablation drivers and the `scaling_eval` artifact CLI now validate
comparison inputs before producing reports. Descriptors retain exact goal,
tier and declared overrides. Each arm freezes its baseline config and tier
field set so historical records are not reinterpreted using current defaults.
Missing identities/profiles, changed shared controls, undeclared differences,
unapplied or unchanged override declarations, duplicate goal/arm entries and
one exact goal relabeled as multiple goals are rejected. Ablation goal groups
must contain the same arms, including an unchanged baseline.

`comparison_validation.status=matched_declared_inputs` covers those controls
only. `retrieval_matching=not_verified` deliberately prevents treating it as
matched scientific evidence. Run repeated paired trials as separate invocations;
do not relabel the same goal to inflate independent-goal counts. Earlier records
without frozen baseline profiles cannot pass this comparison gate and must be
rerun. The low-level metric functions remain descriptive calculations; campaign
comparison artifacts go through the validated drivers or artifact CLI.

Direct citation-entailment, citation-usefulness and Elo panels now retain a
`kind=panel` identity with their full ordered dataset, requested model, mode,
cache policy, evaluator wrapper and shared request-policy hashes, and routing.
The runner freezes these before evaluation and checks again afterward; caches
are disabled for the scope. Compare retained reports with
`python -m evaluations.panel_comparison BASELINE.json CANDIDATE.json`.
Missing, incomplete or mismatched identities and inconsistent execution modes
are rejected. Its success means matched declared inputs, not scientific
acceptance or a successful live provider call. Inspect usage/fallback evidence
and the declared primary/non-regression metrics separately.

Production assessor/ranking implementation may differ as the candidate under
evaluation; retain both source commits with the trial records. Evaluation
rubrics and model request policies must remain fixed. Changing those requires
rerunning both sides. Panel inputs include supplied passages, so comparison
matches that evidence exactly; matching retrieval for whole research runs
remains open under M1-03d4b.

### Matched retrieval requirements

Classification: local design choice. A matching goal, model configuration or
source URL does not prove identical evidence reached the model. Apply these
rules before accepting a scientific-quality candidate:

| Comparison | Required control and evidence |
| --- | --- |
| Citation, claim entailment, review or ranking change with retrieval held fixed | Freeze the exact ordered questions/claims/hypotheses and supplied passages, including labels and source provenance; run both versions on that same public panel. Direct panel manifests and `panel_comparison` enforce equality of their supplied dataset. |
| Retrieval algorithm or evidence-selection change | Freeze public questions, relevance/support labels, source corpus revision/content hashes and candidate-independent corpus availability. Returned passages may differ because they are the intervention. Declare retrieval and downstream non-regression metrics before running; retain requests, results and failure provenance for each arm. |
| Whole-run scaling or ablation with fresh searches | Treat results as descriptive until the required controls are established. `retrieval_matching=not_verified` is not acceptance evidence for an isolated scientific improvement. Increasing a tier or disabling search can legitimately change evidence; report that as part of the intervention, not matched retrieval. |
| Whole-run change requiring identical retrieved evidence | Retain and compare the exact evidence actually supplied at each affected model request, including order, text, identifiers, source/version and retrieval failures. A saved DB evidence inventory alone is insufficient because prompts can select different subsets. Use a bounded matched panel instead when the affected behavior can be exercised there. |

For a fixed-evidence trial, missing or unequal evidence makes the pair
inconclusive: freeze a common public input set and rerun **both** versions.
Do not infer a match from equal citation counts, URLs, cache settings, aggregate
scores or empty retrieval ledgers. No automatic whole-run replay is currently
claimed. If an accepted future candidate requires one, add its concrete replay
and verification work to that repository's milestone before implementation.

Keep baseline and candidate source commits, dataset artifacts and their
manifests, exact invocation/configuration, observed model/fallback telemetry,
primary metric and non-regression criteria with each of the initial three paired
trials. Different served models or fallback behavior require investigation and
matched reruns before attributing quality changes to the code. Model configuration
or evaluation-rubric changes require rerunning both sides. A successful manifest
comparison is a prerequisite, not scientific acceptance; production smoke and
full workflow checks remain separate release requirements.

`claim_support_eval.drive_and_score` is a single-run descriptive measure. It
requires the same paired identity and retrieval procedure before its output can
support a baseline/candidate acceptance decision. Offline results test contracts;
they do not establish improved live scientific quality.

### M1 database release preparation

The main campaign branch adds `claim_evidence.verification_method`, a non-null text
column defaulting to `legacy_unknown`. Existing rows are not scientifically
reclassified. The migration is idempotent; old named-column inserts receive the
default. Existing public-store migration coverage is in
`app/tests/test_claim_verification_provenance.py`. The synthetic local WAL drill
in `baseline/backup-readiness-cycle58.json` is preparation, not production proof.

The reviewed policy work integrated through `865adcf9` additionally adds non-null text
`execution_policy` columns on `runs` and `interviews`, defaulting existing rows
to `standard`. Include all three columns in the intended release's schema
inventory; policy persistence
and recovery coverage lives in `app/tests/test_campaign_policy_persistence.py`
and `app/tests/test_campaign_policy_integration.py`. Existing rows must retain
standard behavior, while newly authorized campaign markers survive recovery.

Before merging to the auto-deployed production branch, create a consistent
backup using SQLite's online backup API from a separate read-only connection;
do not copy just the main DB file while WAL is active. Use the existing approved
storage location only after checking available capacity, and never emit private
rows into logs or campaign artifacts. Verify the completed backup with
`PRAGMA quick_check`, record its timestamp, size, hash and secure location, and
retain the pre-migration schema identity. Do not run VACUUM or a forced checkpoint
in the serving process. If consistent backup verification fails, keep release open.

The additive columns normally remain during application rollback; do not drop them
or restore an older data snapshot merely to roll back code. Restoring data would
lose writes made after the backup and requires a separately justified recovery.
The verified [M2 production backup](baseline/m2-production-backup.json) and
zero-cost code rollback anchor `11285e63ca619bfdfb76d8d2a2c6111c9379738b`
were recorded before merge. The merged API's three additive columns are present,
and post-merge production smoke passed. Continue using the exact free route only
while its current catalog price and availability are verified.
