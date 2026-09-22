# M1 campaign deployment decision

Decision date: 2026-09-22. This is the implementation plan; no frozen source,
inference, UI, deployment, or public mode changes were made.

## Decision

Keep the existing frontend, API/embedded worker, SQLite store, and MCP service.
Run both policies in those processes with the legacy global campaign flag off.
Add a monotone request/task `ContextVar` policy whose value is true when either
the persisted object is `campaign` or the legacy environment flag is true.
Ordinary runs therefore retain every current BYOK behavior, including their
configured/custom and metered tools; campaign calls retain the existing free
model, cache, workspace, skill-credential, and MCP restrictions.

Campaign ownership is server-configured. Add a validated
`campaign_researcher_ids` setting in `app/app/config.py`; only a subject in that
set with `Principal.method == "bearer"` (`app/app/auth.py`) may originate a
campaign object. Compatibility `X-Client-ID` is unsigned and never qualifies.
Clients cannot submit or mutate an execution policy.

Persist `execution_policy TEXT NOT NULL DEFAULT 'standard'` on both `runs` and
`interviews` in `app/app/store/schema.py`, `schema_interviews.py`, and
`db_migrations.py`; thread it through `store/models.py`, `store/runs.py`, and
`store/interviews.py` without adding UI fields. `app/app/runs_crud.py` derives
the marker from the verified principal or a linked campaign interview before
BYOK validation, then stores it. An existing campaign marker always wins over
current configuration, so removal from the identity list cannot downgrade
retries or recovery.

Add the monotone scope in `engine/src/co_scientist/llm_free_policy.py` and a
small app resolver/context helper. Enter it explicitly for interview creation,
turns, retry/edit streams (`interviews.py`, `interviews_stream.py`,
`interviews_revision.py`); run creation and BYOK probe, title/restatement
background work (`runs_crud.py`, `runs_crud_resolve.py`); run-bound Q&A,
announcement and direct safety/contribution calls (`runs_chat.py`, `qa.py`,
`run_start_announcement.py`, `runs_contrib.py`); and the whole durable dispatch
in `engine_tasks.execute_engine_task`. Each detached/background generator loads
the persisted marker itself. Existing `async_bridge.py` context replay then
covers claim/safety off-loop work. Startup resume, manual resume, and expired
lease reclaim need no special flag: every claimed task reloads its run row.

## MCP coexistence

Use the existing shared secret to authenticate a request header such as
`X-CoScientist-Campaign: 1`. In `engine/mcp_server/auth_middleware.py`, accept
that header only with a configured, matching `X-MCP-Shared-Secret`; bind and
reset a server campaign `ContextVar` around each ASGI request. Keep `/` open for
plain health checks, but a policy-bearing root request must authenticate.
`engine/mcp_server/campaign.py` resolves environment OR request scope, so the
existing `tool_logging.py` wrappers and provider/OpenAlex guards enforce each
call. Deploy `server.py` with the global flag off so it registers the ordinary
tool surface; request policy performs the filtering and enforcement.

`engine/src/co_scientist/mcp_campaign.py` sends both headers for its root policy
probe and transport through `mcp_client_helpers.py`. Replace `mcp_client.py`'s
single `_global_client` with separate clients keyed by resolved server
configuration and campaign boolean.
Never mutate headers on an initialized client: its cached tool objects own the
session. Campaign discovery stays public-tool filtered; ordinary discovery and
tools stay unchanged. This prevents a standard cached session/tool from leaking
into a concurrent campaign task, or the reverse.

## Test boundaries

- `app/tests/test_auth.py`, `test_interviews.py`, `test_runs.py`: bearer
  allowlist derives/persists campaign; spoofed compatibility/body values fail;
  linked interviews cannot downgrade it; paid BYOK is rejected before transport.
- `app/tests/test_free_model_requests.py`, `test_durable_free_admission.py`,
  `test_async_bridge.py`: concurrent campaign and paid-BYOK streams/tasks keep
  models, keys, caches and contexts separate; title, restatement, Q&A, safety,
  claim bridge, restart/resume and reclaimed lease preserve policy; contexts
  are empty afterward.
- `engine/tests/test_mcp_campaign_admission.py`,
  `test_mcp_client_reconfigure.py`, and MCP server auth/tool-policy tests:
  missing/forged policy headers fail, authenticated root reports campaign,
  concurrent request contexts reset, both client caches remain isolated, and
  direct plus model-driven campaign calls cannot invoke metered/custom tools
  while ordinary BYOK still can.

No architectural blocker remains.
