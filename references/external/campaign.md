# Campaign procedures

## Current execution state

M1 is establishing the baseline. No live inference or campaign research run has
been performed. No free model has been selected or qualified. Existing model
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
admission boundary. It does not yet cover direct app completions, retrieval,
node caches, tools, embeddings or evaluation-runner configuration; M1-03b–d
must close those paths before a live research experiment.

Outside campaign mode, system `:free` requests still use current-price admission;
explicit/scoped user BYOK remains separate. Catalog evidence expires after 60
seconds and cannot be reused on failed refresh. A catalog fetch is not inference
and can be used to assess availability without spending model credits. A
`FreeModelEligibilityError` is terminal for that LLM request: change/qualify the
configuration or wait for metadata availability, never substitute a paid model.
