# Production cuts

Remove the features, modes and dev tooling the owner chose to give up on
6 October 2026. This plan only deletes. Condensing what stays is a separate,
later plan that starts from the size this one leaves.

**Status:** not started. It starts when the test campaign in `PLAN.md`
finishes, and then replaces `PLAN.md`.

## Scope

Production is about 114.5k lines by `evaluations/tests/test_code_size_ratchet.py`.
The cuts below remove an estimated 18–19k, leaving about 96k. Estimates are not
targets: a cut is done when its feature is gone, not when a number is hit.

Every decision was made with the owner. Research and user features stay. Unused
code and dev-only features go. Nothing outside this list is cut under this plan.

## What goes

### Dev and evaluation tooling

| Cut | Where |
|---|---|
| Evaluation experiment scripts. Keep only what `make eval-smoke` and `evaluations/tests` need: `smoke.py`, `citation_eval.py`, `safety_eval.py` and their datasets | `evaluations/*.py` (ablation, scaling, golden run, Elo concordance, expert review, specific aims, panel, replay, citation usefulness, claim support, MCP live smoke, prod smoke, release gate, `_run_driver`, `_artifacts`, `_identity`, `_live_config`, `_usage_evidence`, `metrics`) |
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
| Domain tool configs (`TOOLS_CONFIG`, INDRA cancer and HFpEF examples). Drop the docker-compose `TOOLS_CONFIG` default | `engine/src/co_scientist/config/` loader and `examples/`, `tools_config` |
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

## Order

One theme per PR, in this order, so later PRs delete code earlier ones made
unreachable:

1. Dev and evaluation tooling.
2. Features with no UI.
3. Campaign mode, access page and required auth.
4. The remaining modes and switches.
5. Logs panel shrink.
6. Demo snapshot.
7. Legacy data: the migration PR, then the deletion PR after the owner runs it.

## Rules

- **Kept behavior stays identical.** A cut changes only what its row names.
- **Tests follow the code.** Delete tests that only cover deleted code; update
  tests that touched it. When a cut removes a module the coverage guard
  protects, remove it from the protected list in the same PR and say so in the
  PR body. The 80% floor holds for everything that stays.
- **The ratchet moves one way.** Lower the production and test ceilings in
  `evaluations/tests/test_code_size_ratchet.py` in the same PR. Never raise them.
- **Delete, don't move.** No logic moves into files the ratchet skips (JSON,
  YAML, Markdown templates). A data snapshot is data, not logic.
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
