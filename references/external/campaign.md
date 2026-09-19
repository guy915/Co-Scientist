# Campaign procedures

## Current execution state

M1 is establishing the baseline. Guarded anonymous retrieval was verified
locally; see [retained evidence](baseline/retrieval-2026-09-19/README.md).
No live inference or campaign research run has been performed. No free model has been selected or qualified. Existing model
names are observations, not proof of current price or availability.

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
