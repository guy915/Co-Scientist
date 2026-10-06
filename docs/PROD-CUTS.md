# Production cuts

Remove the features, modes and dev tooling the owner chose to give up on
6 October 2026. This plan only deletes. Condensing what stays is a separate,
later plan that starts from the size this one leaves.

**Status:** in progress since 6 October 2026 (day 1 of `docs/CAMPAIGNS.md`),
in parallel streams (see Streams). Progress, open PRs and blockers are on the
`Campaign board: cuts` issue.

## Scope

Production is about 115k lines of first-party Python, TypeScript and CSS.
The cuts below remove an estimated 18–19k, leaving about 96k. Estimates are not
targets: a cut is done when its feature is gone, not when a number is hit.

Every decision was made with the owner. Research and user features stay. Unused
code and dev-only features go. Nothing outside this list is cut under this plan.

## What goes

### Dev and evaluation tooling

| Cut | Where |
|---|---|
| Evaluation experiment scripts. Keep what `make eval-smoke` and `evaluations/tests` need (`smoke.py`, `citation_eval.py`, `safety_eval.py`) and the quality benchmark `docs/OPTIMIZATION.md` uses (`claim_support_eval.py`, `citation_usefulness_eval.py`), with the helpers they import (`_run_driver.py`, `_artifacts.py`, `_identity.py`, `_live_config.py`, `_usage_evidence.py`) and their datasets | `evaluations/*.py` (ablation, scaling, Elo concordance, expert review, specific aims, panel, replay, MCP live smoke, prod smoke, release gate, `metrics`) |
| Stage-timing scripts. Keep `backup_db.py` and `refresh_retractions.py` | `app/dev/stage_latency.py`, `app/dev/stage_latency_analysis.py` |
| PubMed study code (pilot trace, Study 4 recovery, metadata batching, `COSCIENTIST_PUBMED_*` flags). Normal PubMed search stays | `engine/mcp_server/pubmed_pilot_trace.py`, `pubmed_metadata_batch.py` and their callers |

### Features with no UI

| Cut | Where |
|---|---|
| Pause and resume endpoints. Cancel and the internal safety hold stay | `app/app/runs/lifecycle.py` |
| Human-added ideas and reviews, and attachment keyword search | `app/app/runs/contrib.py` (POST hypotheses/reviews, `attachments/search`), `app/app/human_input.py` |
| Read endpoints the app never calls: `knowledge-facts`, `/tasks`, `/proximity`, run `/metrics` | `app/app/runs/collections.py` |
| Operator pages: `/metrics`, `/config`, `/docs`, `/redoc`, account export, feedback admin | `app/app/diagnostics_api.py`, `ops_metrics.py`, `account_export.py`, `feedback_api.py`, `main.py` |
| Share-by-link: page, endpoints and table | `app/app/shares.py`, `app/frontend/src/workbench/pages/shared_goal_report.tsx`, the `/shared/:token` route |

### Modes and switches nobody uses

| Cut | Where |
|---|---|
| Campaign mode: funded researcher runs, forced free model, separate MCP URL | `app/app/execution_policy.py`, `engine/mcp_server/campaign.py` and every `campaign` branch |
| Researcher access page, access-code login and the required-auth mode. Anonymous per-browser ownership stays | `app/app/auth.py` (exchange), `app/frontend/src/workbench/pages/researcher_access.tsx`, `auth_mode` |
| Separate worker process mode. The worker always runs inside the API | `app/app/task_worker/__main__.py`, `coscientist_embedded_worker` |
| LLM response cache | `engine/src/co_scientist/cache/` and its hooks |
| bwrap sandbox backend. Landlock (Linux) and Seatbelt (macOS) stay | `engine/src/co_scientist/sandbox/bwrap.py` |
| Domain tool configs (`TOOLS_CONFIG`, INDRA cancer and HFpEF examples), with `golden_run.py`, the INDRA acceptance run. Drop the docker-compose `TOOLS_CONFIG` default | `engine/src/co_scientist/config/` loader and `examples/`, `tools_config`, `evaluations/golden_run.py` |
| Strict safety mode. Standard safety is unchanged | `app/app/safety/` |
| `GEMINI_API_KEY` special case, claim-checker switch, `COSCIENTIST_DEBUG`, `COSCIENTIST_FORCE_MOCK` alias | `app/app/config.py`, `main.py`, `process_mode.py`, `claims/grounding.py` |
| Text log format and `LOG_FORMAT`. JSON is the only format, local and prod | `app/app/logging_setup.py` |
| Log-report email | `/api/logs/report` in `app/app/logs_api.py` |

### Shrink

| Cut | Keep |
|---|---|
| Live logs panel, its polling and the verbose view | Server and browser log capture, one "copy logs" button, and an indicator that shows whether any error or warning was logged |
| Demo-run builder code (`app/app/seed/`, `app/app/demo_seed_data/`) | The same demo runs, exported once as a data snapshot and inserted at startup by a loader of about 100 lines |
| Code that reads old data formats (about 136 legacy branches) | Old runs stay viewable: a one-time migration upgrades prod data first (see Rules) |

## What stays

DB backup and retraction refresh scripts, the landing page, settings (theme,
model choice, own keys, free usage), attachment upload, the feedback button,
run-finished email, the header status dot, all 4 run sizes and focuses, dev
mode, data retention, the offline backend, docker-compose, nightly CI, every
research agent, science skills, MCP biomedical tools, and Brave and Tavily web
search.

Not in this plan: the "Download report" button and giving Q&A the Markdown
report instead of structured data. Those are feature changes, done separately.

## Streams

The cuts run as parallel streams from day 1 of `docs/CAMPAIGNS.md`, which also
sets who edits what, the windows and the merge rules:

1. **Engine and MCP server**, first, because the shrink and the model work wait
   on the engine: PubMed study code, the LLM cache, bwrap, domain tool configs,
   the MCP side of campaign mode and the `COSCIENTIST_FORCE_MOCK` alias.
2. **API endpoints and pages:** pause and resume, human-added ideas, unused
   read endpoints, operator pages, share-by-link and the log-report email.
3. **Modes and switches:** campaign mode, the access page and required auth,
   the worker mode, strict safety, the remaining switches and the text log
   format.
4. **Logs and tooling:** the logs panel, the evaluation scripts, the
   stage-timing scripts and the demo snapshot.
5. **Last:** the legacy-data migration PR, then the deletion PR after the owner
   runs the migration.

One theme per PR; bring in `main` before merging.
Shrink work on a folder starts when its cuts are merged (see
`docs/PROD-SHRINK.md`).

## Rules

- **Kept behavior stays identical.** A cut changes only what its row names.
- **Tests follow the code.** Delete tests that only cover deleted code; update
  tests that touched it. Everything that stays keeps its tests.
- **Delete, don't move.** No logic moves into JSON, YAML or Markdown
  templates. A data snapshot is data, not logic.
- **Docs in the same PR.** Update `AGENTS.md`, `app/AGENTS.md`,
  `engine/AGENTS.md`, `docs/` and `.env.example` files that name a cut feature.
- **Railway.** After a merge that retires an env var, list it for the owner to
  delete (e.g. `CAMPAIGN_RESEARCHER_IDS`, `COSCIENTIST_CAMPAIGN_MCP_URL`,
  `RESEARCHER_ACCESS_CODES`, `COSCIENTIST_CACHE_*`). Never change Railway
  variables without the owner's confirmation. If a Dockerfile's `COPY` list
  changes, update that service's Railway watch paths.
- **Deploys.** Every merge that touches deployed code redeploys production.
  After it, check `/health` and the deploy logs; if production is unhealthy,
  fix or revert first.
- **Legacy migration.** Back up the prod DB with `app/dev/backup_db.py`. Run the
  migration on a copy and check that every old run still renders. Then the
  owner runs it on prod. Only after that does the deletion PR merge.
- **Checks.** Before each PR: `make lint`, `make typecheck`, `make test-all`
  and `make e2e`. Run `make e2e-production` for the auth cut.
