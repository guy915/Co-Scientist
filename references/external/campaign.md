# Campaign procedures

## Current execution state

M1 is establishing the baseline. Guarded anonymous retrieval was verified
locally; see [retained evidence](baseline/retrieval-2026-09-19/README.md).
Live capability probes and an initial scientific challenge have run through
verified zero-cost admission; [model qualification](baseline/model-qualification/README.md)
retains all results, including failures. No model is selected for production and
no full campaign research run has completed. The final Nex Pro magnitude candidate
passed all three matched pairs with the documented provenance correction; earlier
failed candidates remain retained. See the [accepted comparison](baseline/model-qualification/opposition-magnitude-pro-corrected-summary.json).
Three fresh Nex Pro usefulness trials passed; ranking trials 1 and 2 passed,
with trial 3 still running. Model selection and full workflow verification remain
open. These bounded results do not establish production readiness.
Per-assessment method provenance is now retained locally through assessment,
recovery, storage and report output; it has not been deployed. Existing model names alone do not prove current eligibility.

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
requires the existing production smoke evaluator and a campaign-owned public
research flow. Inspect diagnostic probes before calling them: a read endpoint
may itself use a metered retrieval provider.

Scientific comparisons require a declared primary metric and non-regression
criteria, three initial paired trials, identical model configuration and fixed
evidence where appropriate. Freeze exact inputs, hashes, selected models, and
isolated cache locations after M1 live qualification. None is frozen yet.
Do not reuse an old result after relevant code/configuration/input changes.

## Inference and isolation

Do not run live evaluation drivers using their current defaults: local `.env`
selects a model without a free suffix and retains paid-provider credentials.
Before inference, enforce zero-cost routing across engine, app, tools and runners;
verify current applicable prices from OpenRouter. Unknown prices are unavailable.
Preserve explicit user BYOK separately. Disable paid tools/plugins and notifications
for campaign runs. Do not load private documents or other users' run data.

Record actually served models and live versus offline evidence explicitly.
Record rate-limit reset times and resume later; never substitute paid models.

## Release and rollback

Use the existing three services only. Preserve one API replica, root UID on its
volume, off-volume cache, and durable startup/recovery. Merge via PR after required
checks; attach it to the task. Record exact commits, deployment IDs and health.
The [initial deployment snapshot](baseline/releases-2026-09-19.json) is a starting
reference, not a verified zero-cost rollback target. Establish that target in M1.
Never restore paid routing on rollback. Verify a consistent backup before any
persistent-data migration. The campaign explicitly authorizes required merges
and deployments; routine implementation choices do not require re-interview.

### Engine zero-cost admission

Set `COSCIENTIST_REQUIRE_FREE_MODELS=1` for campaign inference processes. This
forces current-price admission even when a runner explicitly supplies a key;
it disables the LLM response cache so every campaign completion reaches that
admission boundary. App completions, node caches, durable tasks and qualified retrieval/workspace
paths now have locally verified campaign controls (M1-03b/c). Evaluation-runner
configuration and evidence remain open in M1-03d; see the
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
Production qualification remains open: caller and server controls must both be
deployed and observed before a live production campaign run. Evaluation-runner
isolation and model qualification must also pass before campaign inference.
No production retrieval billing settings have been altered.

### MCP qualification

Before campaign tool use, verify the endpoint is our reference MCP deployment
at the intended campaign commit, then set `COSCIENTIST_CAMPAIGN_MCP_URL` to its
exact `/mcp` URL in the caller. The resolved MCP configuration must contain only
that one streamable-HTTP server and its existing shared-secret header, if used.
Set `COSCIENTIST_REQUIRE_FREE_MODELS=1` on the MCP service as well as the caller.
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
artifacts and comparison identities remain open; do not start campaign
inference until those controls and model qualification are complete.

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
6. After merge/deployment, run the existing production smoke evaluator and
   repeat the browser public-goal flow under a campaign-owned production identity.
   Record deployment IDs, serving configuration and replay/report evidence.
   Production smoke does not create a run and cannot replace this observation.

The frozen model configuration, exact interview output, run IDs and observed
results will be added during M1 live execution. None is claimed verified here.

Direct citation and Elo panels now share the same isolated configuration. Elo
loads production rating math lazily so importing its evaluator does not load
engine/provider settings before live admission. Citation usefulness accepts an
explicit model argument or MODEL_NAME; both pass the same OpenRouter validation.
Direct capture and deterministic-fallback disclosure have been verified. The
Nex Pro usefulness screen is accepted with retained physical request evidence;
the ranking series and overall model qualification remain open. See the
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
Cross-arm and direct-panel matching remain open in M1-03d4b.

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

The campaign adds only `claim_evidence.verification_method`, a non-null text
column defaulting to `legacy_unknown`. Existing rows are not scientifically
reclassified. The migration is idempotent; old named-column inserts receive the
default. Existing public-store migration coverage is in
`app/tests/test_claim_verification_provenance.py`. The synthetic local WAL drill
in `baseline/backup-readiness-cycle58.json` is preparation, not production proof.

Before merging to the auto-deployed production branch, create a consistent
backup using SQLite's online backup API from a separate read-only connection;
do not copy just the main DB file while WAL is active. Use the existing approved
storage location only after checking available capacity, and never emit private
rows into logs or campaign artifacts. Verify the completed backup with
`PRAGMA quick_check`, record its timestamp, size, hash and secure location, and
retain the pre-migration schema identity. Do not run VACUUM or a forced checkpoint
in the serving process. If consistent backup verification fails, keep release open.

The additive column normally remains during application rollback; do not drop it
or restore an older data snapshot merely to roll back code. Restoring data would
lose writes made after the backup and requires a separately justified recovery.
Before release, identify an audited zero-cost recovery code/configuration target;
the pre-campaign production commit is not automatically such a target. Actual
backup, deployed migration, recovery configuration and smoke evidence remain pending.
