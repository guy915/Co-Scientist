# Operational invariants and incident rationale

Read the relevant entry before changing persistence, startup, workers, provider
bounds, or scientific gates. Each entry states the rule, the code that enforces
it and why. Current model defaults are declared in
`engine/src/co_scientist/core/config.py`.

See [deployment](DEPLOYMENT.md) for hosting and [launch readiness](LAUNCH.md)
for release validation.

## Provider escalation bounds

Tool turns use the bounded policy with at most three physical attempts per turn
(`platform/llm/tools/loop.py`). Throttles and temporary outages use jittered
backoff, with a longer schedule for outages (`provider_outage_backoff_seconds`)
because throttle delays can exhaust every attempt before a multi-minute outage
clears. Platform quotas park the durable task; retries are metered in telemetry.
Timeouts, call-budget exhaustion, oversized prompts and failed free admission
stay terminal (`_NEVER_RETRIED` in `platform/llm/attempts/retry.py`). Retries
stop before tool execution and never replay tools from completed turns. The
mandatory-reasoning rung keeps the tool request's raised-budget shape rather
than switching to minimal effort.

`AttemptPlan.escalation_only` has no numeric attempt budget but visits each
distinct rung at most once per call, including the initial rung, so it permits
at most four physical attempts and raises the current failure before revisiting
a rung. Failures no rung answers propagate without backoff, parking or retry
telemetry. Production entry points, including tool turns, use bounded plans
whose configured budgets allow revisiting rungs.

The visited-rung guard exists because alternating reasoning-only responses and
mandatory-reasoning refusals once looped through the disabled and mandatory
states indefinitely. The outer tool-turn limit cannot replace either
physical-attempt bound: it counts turns after each provider response, not the
recovery attempts inside a turn. The attempt boundary stays below tool
execution so recovery never reruns tools from an earlier completed turn.

## Offline provider isolation

App-side claim assessors bypass the engine router, so they must enforce offline
mode themselves even when a credential is present (`offline_mode()` in
`domains/research_state/claims/grounding.py`, on both the batch and individual
paths). A leak once billed one call per claim group while tests appeared offline,
because a silent provider-error fallback hid it.

## Title validation

JSON-object downgrades do not enforce schema length bounds, so titles are
validated again before persistence (`_TITLE_DISPLAY_CAP` in
`domains/research_state/drain/hypotheses.py`). Mechanistic titles with
gene/receptor names can exceed 100 characters; the 120-character cap
(`MAX_TITLE_CHARS`) accommodates that vocabulary.

## Gotchas

Each of these was a production outage or a silent data-correctness failure. The comments in the code carry the detail; do not re-litigate them from first principles.

- **Never VACUUM from the serving process.** VACUUM and truncating WAL checkpoints need exclusive access, and a SQLite writer waiting for one blocks every writer queued behind it; the log-capture thread writes on every record, so the quiet moment never comes. The symptom is an idle-looking database with every write failing "database is locked". `_reclaim_disk_space()` in `main.py` only prunes superseded checkpoints and `compact_database()` no longer exists (`app/tests/test_diagnostics.py` pins this); the file keeps its high-water mark, and offline compaction means running VACUUM by hand against a stopped database. When a lock symptom appears with an idle database, run `py-spy dump` first.
- **Never hold the SQLite write lock across network I/O, and never write on a poll tick.** There is one writer and no fair queuing, so a transaction spanning an LLM call, or a per-tick write stream, starves every other writer. Hence `assess_hypothesis_claims` (provider work, no DB) is split from `persist_grounding` (writes only) in `domains/research_state/claims/grounding.py`, `_has_claimable_task` probes read-only before `claim_task` opens `BEGIN IMMEDIATE`, and the task heartbeat checks cancellation in memory every second but renews its 300s lease only on the lease's own schedule. The heartbeat is a coroutine on the task's own loop, so synchronous provider waves starve it like a write does: `orchestration/drain.py::_assess_claims` and `orchestration/engine_tasks/gate.py::_assess_gate_claims` run their waves through `core.async_bridge.run_off_loop`.
- **Startup work runs before uvicorn binds a port: keep it cheap and never fatal** (`main.py` lifespan). Run recovery executes interrupted runs rather than scheduling them, so it runs as `asyncio.create_task` with its cohorts on `asyncio.to_thread`; awaiting it put provider calls ahead of the port, failed the healthcheck, and left each restart further behind. The checkpoint sweep must stay inline because it needs the reader-free startup window (a long-lived SSE reader blocks it forever), and it catches `sqlite3.Error` and continues because a full volume cannot journal the DELETE that would relieve it. Serving with a bloated table beats not serving.
- **Only `UnsupportedTaskError` and `LLMCallBudgetExceededError` are permanent task failures** (`orchestration/task_worker/outcomes.py`). Retrying a run that has spent its call ceiling only spends more. Every provider call must therefore pass through `call_llm`/`call_llm_json` so `record_provider_request` sees it: the pre-ranking claim gate once called `litellm` directly and ran far past the ceiling unseen, and now reaches `call_llm_json` through `core.async_bridge.run_coroutine_sync` from the synchronous `Assessor` protocol. `assess_claims_batch` judges a hypothesis's claims in one call, not one per claim, because the gate repeats before every ranking wave. Every other exception keeps its retry budget; widening the permanent set strands runs (progress in bursts, tasks parked at attempt 1/3 with retries unused).
- **Nothing automatic recovers a `failed` task.** `resume_run_tasks` requeues only `paused`, and the expired-lease rescue skips tasks whose attempts are spent (`_EXPIRED_LEASE_RESCUABLE`). Explicit recovery is the only path back (checkpoint resume, run start, the supervisor's `retry` action via `retry_task`), and any path that re-enqueues a boundary must call `revive_task_for_retry` **before** enqueueing, because the idempotency key cannot change while the run makes no progress and `ON CONFLICT DO NOTHING` would create nothing. Portfolio node tasks key on `{task_type}:after:{predecessor_task_id}` so a lookahead row and the later reactive enqueue collide on one row; bootstrap, resume and continuation rows stay sequence-anchored. Revival takes a `leased` task only once its lease has expired, since reviving a live lease would run the boundary twice. `LLMRateLimitParkError` (a 429 reset too far off for ordinary backoff) is neither a failure nor a retry: `_park_rate_limited_task` returns the row to `queued` with its attempt undone and `available_at` at the provider's reset plus jitter.
- **No process-global asyncio primitives.** Each durable run's worker cohort runs on its own thread and loop (`run_run_worker_pool_sync` calls `run_in_scoped_loop`), so several loops are live per process, and a primitive binds to the first loop that waits on it. The ranking judge semaphore is therefore created per running loop and held weakly (`science/ranking/ranking_debate.py::_get_ranking_semaphore`); as a singleton it killed a ranking task only once waves grew large enough to contend. Bound concurrency per loop or via the cohort's `worker_pool_size`; module scope is safe only for primitives touched solely from the API loop.
- **Never score a short claim against a long document with Jaccard.** Jaccard divides by the union, which the longer side dominates, so the score is capped near `len(claim) / len(document)` however well the document supports the claim. `platform.retrieval.citations.classify_citation` therefore uses coverage (intersection over the claim's tokens), and a new threshold must be sanity-checked against a document that literally contains the claim (`app/tests/test_citations.py`); with the old metric both upper states were unreachable and every citation classified `unsupported`, which read as an evidence-quality problem. Coverage still cannot tell a claim's subject from its assertion; sharpening that is the LLM entailment assessor's job (`domains/research_state/claims/verifier.py`), not a reason to tune deterministic thresholds between hand-picked examples.
- **A model's `contradicts` label is not trusted on its own.** `guard_contradictions` in `claims/verifier.py` keeps it only when a cited quote covers the claim's subject and carries a negation cue (`_quote_negates_claim`, `_CONTRADICTION_MARKERS`) or a separate opposition-verification call confirms same conditions and mutual exclusivity; otherwise the verdict is downgraded to `insufficient`, never promoted to `supports`. Unguarded, topically adjacent or even confirmatory passages were labelled contradictions and withheld most hypotheses from a report. The gate's contradiction-over-support precedence (`claims/gate.py`) is deliberately unchanged: the fix sits where a contradiction is first believed, not where it is weighed.
- **An early gate that never reverses decides the whole run.** A blocking `review_disposition` bars an idea from the Elo tournament (`Hypothesis.is_rankable`), skips comprehensive reflection, and shrinks the evolution pool (`_select_evolution_pool`); a gate that blocked 20 of 22 ideas left a two-idea tournament and an evolution pool that re-derived one drug. So the thresholds mirror the review prompt's rubric (`NOT_VIABLE_SCORE`/`NEEDS_REVISION_SCORE` in `core/constants`) rather than being tuned alone, and only the non-viable band blocks; the batch prompt forces a spread of scores, so a relative low scorer exists on every run. A missing score must be neutral, not the worst score (json_object mode does not enforce the schema). The gate is not terminal: `review_gate.derive_review_disposition` re-derives from every review the hypothesis holds (the mature cascade wins except over `unsafe`), `refresh_review_dispositions` re-runs it at zero LLM cost, and each blocked idea gets exactly one recurrent review per run (`review_recheck_issued`, checkpointed so a resume cannot re-fire it, capped at `MAX_RECHECKS_PER_RUN = 24`). Re-reviewing every blocked idea every cycle was rejected because blocked ideas are the population that grows when the gate misfires. "Excluded from the report" is also not one fact: `duplicate` and `rejected` share `EXCLUDED_HYPOTHESIS_STATUSES` but must reach the reader as different words.
- **The near-duplicate guard must see everything it guards against.** `evolve.py` passes `other_hypotheses_texts` to `_apply_evolution_result`, which discards too-similar children. They are sampled from the whole pool (`sample_context_hypotheses`: top 5 by Elo plus random, capped at 15, which bounds token cost); sampling from the round's `top_k` left the guard blind to every idea outside the round and proximity archived the duplicates only afterwards.
- **Counts named for different things are computed differently.** The report payload carries `idea_count` (everything explored), `hypothesis_count` (released by the safety/contradiction gates) and `verified_count` (released and carrying a `supports`/`partial` claim edge). `domains.report.gates._verified_hypothesis_count` is the exact complement of `unverified_hypothesis_ids` over the released set, because the tile and the per-idea badge are one fact shown twice. `idea_buckets` must partition: `non_viable` is everything not in `high_potential`, so capping either half stops the pair summing to the idea count.
- **Structured-output schemas must not echo input back.** Identify pool items by the positional index the prompt assigns, never by repeating their text: an echoing schema makes output length scale with the pool, overruns the token budget, truncates the JSON identically on every retry, and degrades silently (this is how proximity clustering stopped deduplicating; `_match_cluster_member` in `science/proximity/proximity_dedup.py` keeps text-prefix matching only as a fallback). Trim the schema, never the input: proximity sends the whole pool in one prompt and must keep full hypothesis text (`_prepare_hypotheses_for_analysis`), because it is asked to find differences that live in a hypothesis's tail and its verdict deletes work. If the prompt is too large, chunk the pool.
- **`max_tokens` funds the chain of thought too.** Reasoning counts against the same allowance, so an answer-sized budget lets thinking consume all of it: `finish_reason="length"`, empty `content`, paid in full. Both codebases apply a floor instead of trusting per-site budgets: `THINKING_FLOOR_MAX_TOKENS` via `_apply_thinking_args`, and `thinking_safe_max_tokens` (delegating to `effective_max_tokens`) at app streaming sites. Omitting `max_tokens` is not safe either: the provider default is small enough for thinking to exhaust, and an unbudgeted safety screen once held every run for human review on a truncation. The standing rule: **an app-side call that parses JSON from a one-shot completion goes through `call_llm_json`, not a direct `litellm.acompletion`** (a bare `json.loads` also failed on a model that fenced its JSON in Markdown, holding every run at intake). App streaming and plain-text calls (`domains/chat/interviews/model.py`, `qa/__init__.py`, `run_start_announcement.py`, `goal_text.py`, credential probes) go through `platform.llm.llm_request.acompletion` and `complete_request`; they keep streaming and caller deadlines but have their own operation budget (`APP_LLM_MAX_CALLS`, default 4) instead of consuming a run's allowance, count one physical attempt only after free admission, and summarize usage once per operation. Streaming requests ask for final usage and keep missing usage unknown.
- **A floor is not a guarantee, so the retry has to change the request.** Retrying a budget failure unchanged is the same doomed call billed again. `_extract_completion_content` (`platform/llm/request/response.py`) splits an empty response by `finish_reason`: `"length"` raises `LLMBudgetExhaustedError` (a `ValueError` subclass); a normal stop that spent reasoning tokens and wrote no answer raises `LLMThinkingOnlyError`, which skips straight to the top rung because the model chose to stop and never wanted for room; an empty response with no reasoning stays a plain `ValueError` and a plain retry. `BudgetEscalation` is the ladder, climbed only by `run_attempts` so `call_llm`, `call_llm_json` and the tool turn cannot drift apart: raise the budget by half again (floored at `BUDGET_ESCALATION_MAX_TOKENS`, increment capped by `BUDGET_ESCALATION_MAX_INCREMENT`; a flat max silently no-ops for callers already at that constant), then thinking off. The last rung makes it terminate, since no finite budget is provably enough. A schema or parse failure keeps the current rung because more tokens do not fix a wrong answer; only `call_llm_json` can raise one, which is why it defaults to 5 attempts and `call_llm` to 3 (exactly the three rungs). The failure log reports the effective budget (`effective_max_tokens`), not the pre-floor number, so it does not read as a provider fault.
- **Classification calls and models that cannot disable reasoning.** Entailment is classification, not reasoning work, so those calls request thinking off from the first attempt (`LLMCallOptions(enable_thinking=False)`, `max_attempts=3`). The wire shape is decided by `platform/llm/request/thinking.py`, not the call site: a model whose `ModelProfile.reasoning_can_disable` is false (the default for every declared free-chain entry) is sent a capped reasoning knob (`MINIMAL_REASONING_MAX_TOKENS`) instead of a bare disable, funded by the same floor (`effective_thinking_enabled`), so the redirect cannot reproduce an answerless completion. For a model the table gets wrong, `escalation_for_error` recognizes the "reasoning is mandatory ... cannot be disabled" 400 (or a rejected reasoning cap) and escalates once to `MINIMAL_REASONING_REQUIRED`, forcing reasoning on at low effort via `scoped_minimal_reasoning`; one recovery attempt only, so a provider that rejects that too still exhausts its budget. Without this, every hypothesis fell back to the deterministic lexical assessor.
- **The token budget and the wall clock are one setting in two places.** Funding a chain of thought without extending the deadline only moves the failure to a mid-reasoning abandonment, and both land in the same silent fallback. `thinking_safe_timeout` raises the deadline like `thinking_safe_max_tokens` raises the budget (`THINKING_FLOOR_TIMEOUT_SECONDS` derives from the token floor). **On a streaming call, bound silence, not duration** (`platform/llm/llm_scope.py::stream_chunks`): a stream delivering tokens is healthy however long it runs, and on a thinking model long-but-alive is normal. Interview and Q&A streams relay reasoning as it arrives, so a generous deadline there is visible progress; do not copy those numbers to a blocking call that shows nothing. A stream can also end clean having spent every reasoning token and written no answer, which is not a provider failure: the interview path retries once with thinking off (`thinking_off_kwargs`), as do `domains/chat/goal_text.py` and `run_start_announcement.py`, without importing the engine's ladder.
- **A per-item LLM pass belongs to the caller that runs once, not per hypothesis.** The model-judged relevance pass (`apply_semantic_relevance`) costs one call per candidate; the literature-review node spends it once per run, but deep verification, comprehensive reflection (`full`) and evolution grounding all reach search through `evidence_context._retrieve_probe_evidence`, per hypothesis per cycle, multiplying cost by pool size and iteration with no error. `SearchConfig.semantic_relevance_enabled` is the opt-out, set to false at that one shared seam. Before adding a per-item LLM pass to a shared helper, check every caller's multiplicity; when a phase's cost jumps, read per-item telemetry (`scientific_tasks.result_json` carries each fan-out item's `model_usage`) before reading code.
- **A tool's `parameter_mapping` is written in its caller's vocabulary, and an unmapped name is passed through, not dropped** (`ToolConfig.map_parameters`). Two vocabularies reach it: the search paths send `query/slug/max_papers/recency_years/run_id` and context enrichment sends `entity_name/limit`. A mapping written for the wrong one makes the MCP server reject the whole call on validation (Europe PMC and preprint search returned nothing to any run until fixed). A tool that takes an id rather than a query must not be `category: "search"`, since novelty validation calls the first search-category tool of its workflow; workflow tool lists contain only tools whose input that caller can send. No test binds configured mappings to the real `engine/mcp_server` signatures, so check both sides when either changes.
- **Under the json_object downgrade, reshape the answer to the schema in both directions.** A model without server-side schema enforcement omits required fields and invents extra ones, and every object node from `core/json_schema.obj` is closed (`additionalProperties: False`), so one invented key fails the whole response; feeding the validation error back did not help across five paid attempts. `reshape_json_output` (`platform/llm/structured/validate.py`) removes undeclared keys, fills required fields and cuts over-long `maxItems` arrays and `maxLength` strings (at a word boundary where possible). It runs only when `_supports_json_schema_response_format` is false (`json_attempt._backfill_and_validate`), so where the provider enforces the schema an extra field stays a real validation failure.
- **Two independent wall-clock ceilings on outbound calls.** `COSCIENTIST_LLM_TIMEOUT_SECONDS` (default 600s) bounds `litellm.acompletion` only; MCP tool calls are bounded by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). Setting either to `0` disables it. The two MCP call sites diverge deliberately: `call_tool` raises `MCPToolTimeoutError` (callers degrade per source), while `execute_tool_call` returns the timeout as the tool's result, because it runs under an `asyncio.gather` without `return_exceptions` where raising would kill every sibling call.

## Durable state reducers

Derive commit reducers from every accumulating `WorkflowState` channel
(`channel_reducers` in `orchestration/task_runtime.py` reads the `Annotated`
hints). A hand-maintained table once omitted `tournament_matchups`, silently
replacing prior cycles of Elo history instead of appending them.

## Durable node names

Graph node keys persist in task types, checkpoints and idempotency keys.
Renaming a node requires a migration even when its implementation is unchanged.

## Contextual safety review

Danger nouns alone do not establish operational intent. Deterministic context
matches cannot clear themselves: only a contextual assessor can clear a held
verdict or strengthen it to a block. Operational hard blocks bypass that assessor;
unavailable or ambiguous review remains held.

Redact both report payload and Markdown: reports and events
expose them independently. Final-report redaction leaves the separately served
claim-evidence facts unchanged.

## Advisory reachability

Online audits (`make audit-deps`) retain every finding from all five locks (three
Python, two Bun). Findings in LiteLLM proxy routes, FastMCP Windows/OAuth paths
and pickle-backed DiskCache were outside the deployed execution paths, not
permanent waivers. Reassess reachability when exposing those paths or changing
the entry point, host OS or storage topology; upgrade and validate deliberately
rather than suppressing them.

## Credential boundaries

Run ownership is a caller-selected per-browser client ID, not verified
identity; it keeps one browser's work apart from another's but does not
authenticate a person. Keep MCP private with matching shared secrets.
BYOK encryption uses a separate key: rotation requires migrating or removing the
affected stored credentials. Keep database sidecars, caches and outputs out of
commits and image build contexts.

Use one provider-credential map for offline selection and semantic safety:
separate maps mistook credentialed Azure/Google deployments for keyless ones
and silently skipped provider work or contextual review.

Resolve every staged-document ID against its owner before committing a run or
interview; partial attachment silently changes the requested evidence. Deleting
a staging record leaves text already copied into a run as that run’s evidence.

## Known limitations

- **Remote images in model-written Markdown.** The Markdown renderer
  (`app/frontend/src/shared/ui/markdown_message_renderer.tsx`) has no `img`
  override and neither `app/frontend/public/_headers` nor `vercel.json` sets a
  Content-Security-Policy, so Markdown a model
  writes can load remote images. Raw HTML stays escaped; never enable `rehype-raw`
  for model output.
- **The reference MCP server is open when its secret is unset.**
  `SharedSecretAuthMiddleware` (`engine/mcp_server/auth_middleware.py`) accepts
  every request unless `COSCIENTIST_MCP_SHARED_SECRET` is set (only `GET /` is
  exempt when it is), so production must set the same secret on both the mcp and
  api services.
- **Ownership is not authority.** A client ID must never confer safety-review
  power: adjudication requires the operator token (`LOGS_ADMIN_TOKEN`, sent as
  `X-Logs-Token`; `has_admin_token` in `api/operator_access.py`), checked in
  `adjudicate_safety` and honoured by the ownership middleware for any run.
- **Engine calls spend the shared quota.** Every deployment-funded provider call,
  including engine calls, reserves global durable quota (see Provider admission).

## Claim adjudication

A contradiction requires a verbatim, on-topic negating quote. Off-target or
confirmatory passages cannot block a hypothesis, including deterministic fallback
under LLM provenance. Tolerating passage numbers or legacy evidence IDs never
bypasses the requirement that the quote occur in evidence actually shown.
Ground passage-sized chunks before variable claims to preserve cache reuse.

## Classification and held tasks

Classification calls disable reasoning or use the smallest capped mandatory
reasoning budget; raising output floors can fund more reasoning rather than an
answer. A configured but unreachable safety assessor refuses; offline mode must
be deliberate. Safety holds park claimable tasks without spending retry attempts,
and re-enqueuing an already-succeeded idempotency key cannot revive the task.

## Cost accounting

Cost accounting uses measured provider cache-read rates.

## Queued work and log cursors

Future-due queued tasks keep their worker cohort alive until they become claimable.
Retention and scoped log clears leave ID gaps: count matching rows after a cursor,
rather than subtracting cursor IDs.

## Retention

Staged documents default to 30 days (`COSCIENTIST_DOCUMENT_RETENTION_DAYS`),
terminal runs to 90 (`COSCIENTIST_RUN_RETENTION_DAYS`) and drafts to 7
(`COSCIENTIST_DRAFT_RETENTION_DAYS`); `0` disables that expiry
(`domains/access/retention.py`). Nothing schedules the sweep: `sweep_all` runs
only when someone invokes the module (`python -m co_scientist.domains.access.retention`),
and no startup hook, worker or Makefile target calls it. A separate Railway cron
service cannot reach the api's mounted volume, so any schedule must run inside
the API process, with short per-run transactions and never a long writer hold.

## Gateway routing and privacy

OpenRouter accepts at most three entries in a models array; free allowances belong
to individual models. Preserve upstream preference for cache locality rather than
round-robin hosts. `require_parameters` binds support to the selected host, and
privacy admission requires verified zero-retention hosts.

## Ranking and steering

Repeatedly judging the sole pair in a two-idea pool adds no evidence and inflates
Elo. Steering is consumed on observation, so it buys one cycle beyond an exhausted
ceiling to incorporate the input before marking it applied.

## Durable fan-out recovery

Propagate budget and rate-park exception types through gathered work so the
worker can terminate or park it correctly. Permanent failure or plan divergence
cancels dependent portfolio tasks in one transaction. An unknown provider outcome
permanently fails a fanout item without replaying it or cancelling siblings;
aggregates admit failed items and preserve an explicit unreviewed verdict.
Unknown outcomes on coordinator tasks still stop the run. Lost leases may retry
only under persisted zero-price admission, without caller keys: the
`zero_cost_admission` stamp a free run on all-free routes gets at creation,
which binds its engine tasks to zero-price-only requests. Unstamped runs fail closed.

Verification issuance markers survive failed attempts and checkpoint restore;
otherwise recovery funds the same evidence pass again. Periodic companion nodes
(meta-review and research overview) run serially and retain their list on
restore to prevent checkpoint forks (`stack_companions`: parallel successors fork
the checkpoint chain). Likewise, running proximity beside the research overview
would give one run two concurrent checkpoint writers, which the single-writer
checkpoint invariant forbids. Successful simulation is not reissued because
full review failed, and a failed simulation is not retried after full review
succeeds.

## Usage and failure attribution

Price the served model while retaining its gateway prefix: unprefixed names can
turn paid calls into apparent zero-cost usage. Lower layers log failures at
debug; the retry boundary emits one reader-facing record per attempt with the
actual sent budget and call identity.

## Tool transcript recovery

Age tool results before deduplication: an aged note must not erase a newly
retrieved body. Keep positional call/result pairing and prior reasoning while
eliding superseded writes; later patches do not supersede earlier relative edits.
Interrupted commands may already have side effects, so aborted output must not
claim the command never ran.

Workspace spill writes run outside confinement and must resist symlinked or
missing metadata paths. Redact stdout before model transcripts and drop the
output if a secret still survives.

## Settlement and structured answers

Use the same match-debt quantity to size, open and close a settlement episode.
Do not refill while debt persists; bound the episode by distinct pairs.
Place the answer-deliverable instruction before an injected response schema;
placing the same instruction afterward did not prevent empty thinking replies.

## Search widening and scroll timing

Keep PubMed automatic term mapping on exact/recency rungs; broader field-tagged
queries retain leading subject anchors. Fully ORing a starved query can return
huge unrelated corpora. Strip wildcard syntax on ordinary OpenAlex search
(API 400s), and distinguish source refusal from successful empty retrieval.

Programmatic scroll anchors do not establish user follow intent. ResizeObserver
callbacks must defer writes to observed text to avoid loop errors; batch geometry
reads and writes to avoid repeated layout flushes. Theme suppression lasts two
animation frames.

DOM growth is not a reader gesture: compare scrollTop with the last applied
bottom scroll before measuring the new gap; asynchronous scroll events can lag
the gesture. Rearm initial landing by conversation identity because chat switches
reuse the workspace rather than remounting it.

## Retrieval scores and scheduling ceilings

Capture lexical retrieval scores before stamping hybrid scores. Reusing the
overwritten score double-weights the semantic term and can collapse rankings.

A tool that cannot answer returns its empty result with an `error` object
(`engine/mcp_server/tools/_results.py`); it never raises or returns a bare
empty result for an upstream failure. The engine reads that field
(`reported_failure`) and treats it as a permanent query failure, and its MCP
client raises `ToolException` for any execution error rather than accepting
FastMCP's error text as a result. Transient transport failures use bounded,
jittered retries (`call_search_tool`); distinguish failed queries from
successful zero-hit responses.

Owed review cannot override the provider-call ceiling: scheduler and transport
use the same counter, so its first call would turn budget termination into a
permanent task failure. Spend its bounded per-hypothesis marker at issuance,
regardless of success; settlement coverage retains its separate scheduling policy.

## Run capacity, interview completion and safety decisions

Count concurrent runs across all tiers; per-tier counting multiplies the
advertised allowance. Provider spend belongs to each tier's call budget.

Model-confirmed completion requires challenge/focus and accepts explicit no
constraints; fallback completion must collect a preferences answer first.

Hypothesis-stage adjudication concerns an already-excluded idea and leaves the
whole-run lifecycle untouched. Intake/final decisions govern the run's hold.

## Checkpoint successors and terminal synthesis

Persist each checkpoint's exact resume successor; recovery rebuilds the same
predecessor-based idempotency key. Bootstrap must reach supervisor guidance before
orchestration; defaulting to the orchestrator can resume an unplanned run.

Only exhausted durable retries may degrade optional terminal synthesis to an
empty section, allowing finalization to publish completed work. Budget, parking
and cancellation control-flow errors still propagate to the worker.

Batch tournament progress to expose liveness without flooding the bounded
event feed with per-match events.

Bound both per-source content and total corpus size: neither cap substitutes
for the other. The 130-source cap (`RESEARCH_OVERVIEW_MAX_SOURCES`) targets about
52,000 evidence tokens; adding full texts requires selecting passages rather than
lifting those caps.

Fit synthesis to the provider clock as well as its output allowance: at tens of
tokens per second a 42,000-token request cannot fit the 600-second default
deadline. Outline once and write bounded parts, preserving successful siblings
and grounded draft fallbacks when a part fails.

## Safety deferral and proximity storage

Unsafe-content stops never defer to owed review or tournament coverage.
Cleanup may exceed ordinary work ceilings only within its settlement allowance
or permanent issuance markers; provider admission still caps new requests.

The proximity edge floor (`PROXIMITY_EDGE_FLOOR`) bounds checkpoint size and the
SQLite writer's insert workload, while every pair is still measured. Round before
admission so the persisted similarity is the value compared against the floor.

Size idea/match ceilings above each tier's productive steady state. Both match
participants count toward coverage, and limits checked before work can otherwise
terminate healthy runs after their first tournament.

Empirical outcomes and their targeted refinement are retired. Schema initialization
removes `outcome_refinement_actions` and `hypothesis_outcomes`, then settles pending
`engine.outcome.refinement` rows as completed with `{"retired": true}`. The retired
dispatch path also returns that result without model calls. Scientific checkpoints
and ordinary task dependencies remain intact for recovery; no retired call replays.
A run reactivated solely for refinement returns to completed when its published
report survives and no ordinary work is pending.

## Feedback and operational diagnostics

`POST /api/feedback` requires the caller's `X-Client-ID` owner identity and
accepts one of five fixed categories, a message (8,000 characters), the session
diagnostic export (100,000), a URL (2,048) and an optional run ID (128). The run
ID is context only: it never grants access to that run or its artifacts.

Maintainers read the `feedback` table in the SQLite store; there is no HTTP read
route and no SMTP delivery. The store keeps the newest 200 submissions within a
10 MiB budget and prunes records older than 30 days. Admission allows 5 per
owner, 20 per connecting host (hashed, never returned) and 100 globally per
rolling minute, retained across restarts and row eviction; excess requests get
HTTP 429 with `Retry-After: 60`.

The attached export keeps the newest loaded records within the limit; a failed
log fetch becomes an explicit diagnostic-unavailable record so the message can
still be sent. Failed fetches are recorded as method, path and status without
query strings or payloads.

## Provider admission

Provider admission is separate from research-run budgets. Every operator-funded
physical completion, engine or app, atomically reserves one call and a token
allowance in SQLite before dispatch (`platform/db/admission.py::reserve_provider`).
The allowance is conservative: prompt bytes plus 1,024 plus the request's whole
output cap (`_token_reservation` in `platform/llm/admission/service.py`).
A successful call with reported usage then settles to its real prompt plus
completion tokens (`settle_provider`, refunding the difference in one
transaction, at most once per receipt). Failed calls, missing usage and
interrupted streams keep the full reservation because billing may be
uncertain. UTC-day quotas survive restarts and run/chat deletion.

Scopes and defaults: global `APP_LLM_GLOBAL_CALLS_PER_DAY` /
`APP_LLM_GLOBAL_TOKENS_PER_DAY` (1,024 calls, 32M tokens; also covers rotated
client IDs and every funded engine call), per client
`PROVIDER_CLIENT_CALLS_PER_DAY` / `PROVIDER_CLIENT_TOKENS_PER_DAY` (512, 16M) and
per host `PROVIDER_HOST_*` (512, 16M), plus per-client app-chat
`APP_LLM_CLIENT_CALLS_PER_DAY` / `APP_LLM_CLIENT_TOKENS_PER_DAY` (64, 2M). All
must be positive. `APP_LLM_MAX_OUTPUT_TOKENS` (32,768) and
`APP_LLM_MAX_INPUT_BYTES` (256,000) bound one app request; engine requests use
`PROVIDER_MAX_OUTPUT_TOKENS` (131,072) and `PROVIDER_MAX_INPUT_BYTES`
(1,000,000). These are usage limits, not a price quote; model selection sets the
cost per token. BYOK calls skip the reservation, keep the operation cap and use
the caller's funding. Session-start announcements are claimed once per run;
repeats replay the stored reply, or a deterministic confirmation if the original
stream was interrupted.

**Reservation ceiling.** Without settlement, reserving the whole output cap
per call ran about four times a run's real use, so a Standard run exhausted the
default 16M `PROVIDER_CLIENT_TOKENS_PER_DAY`. Keep settlement rather than
raising the ceilings or shrinking the reservation: the reservation must cover
a call whose usage never arrives.

## Decision-provider admission

The optional Liquid decision client retains the shared physical-call/token
ceilings and reserves its own daily allowance before HTTP. Failed attempts are
not refunded. Never hold a DB writer over a provider request or replace an
exhausted free decision route with a paid model. Configuration and the manual
evaluation workflow are in [decision-model.md](decision-model.md).
