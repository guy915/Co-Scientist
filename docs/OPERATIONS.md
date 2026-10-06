# Operational invariants and incident rationale

Read the relevant entry before changing persistence, startup, workers, provider
bounds, or scientific gates. These incident descriptions preserve the rationale
for the safeguards. Model names and measurements are dated observations; current
model defaults are declared in `app/app/config.py`.

See [deployment](DEPLOYMENT.md) for hosting and [launch readiness](LAUNCH.md)
for release validation.

## Provider escalation bounds

Tool turns use the standard bounded policy with at most three physical
attempts per turn. Throttles and temporary outages use jittered backoff;
platform quotas park the durable task, and retries are metered in telemetry.
Use a longer wait schedule for outages: throttle delays can exhaust every
attempt before a multi-minute provider outage clears.
Timeouts, call-budget exhaustion, oversized prompts and failed free admission
remain terminal. Retries stop before tool execution and never replay tools
from completed turns. The mandatory-reasoning rung retains the tool request's
raised-budget shape rather than switching to minimal effort. See
[the provider policy decision](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-provider-policies.md).

The separate `AttemptPlan.escalation_only` contract has no numeric attempt
budget, but visits each distinct rung at most once per call, including its
initial rung. It therefore permits at most four physical attempts and raises
the current failure before revisiting a rung, even when reasoning failures
alternate. Failures no rung answers propagate without backoff, parking or
retry telemetry. Production entry points, including tool turns, use bounded
plans; their configured attempt budgets allow revisiting rungs.

An offline regression on 2 October 2026 alternated reasoning-only responses
and mandatory-reasoning refusals. The old loop revisited disabled and mandatory
reasoning states indefinitely; a finite success sentinel was reached only after
21 requests. The call-local visited-rung guard now raises the current failure
before a repeated state (three attempts for that sequence) under escalation-only
plans. Current tool turns terminate the same sequence within their three-attempt
allowance. The outer tool-turn limit cannot replace either physical-attempt
bound: it counts turns after each provider response, not the recovery attempts
inside a turn. The attempt boundary remains below tool execution so recovery
never reruns tools from an earlier completed turn.

## Offline provider isolation

App-side claim assessors bypass the engine router, so they must enforce offline
mode even when a credential is present. A past leak billed one call per claim
group while tests appeared offline; silent provider-error fallback hid it.

## Title validation

JSON-object downgrades do not enforce schema length bounds, so validate titles
again before persistence. Mechanistic titles with gene/receptor names can exceed
100 characters; the 120-character cap accommodates that domain vocabulary.

## Gotchas

Each of these was a production outage or a silent data-correctness failure. The comments in the code record the incident; do not re-litigate them from first principles.

- **Never VACUUM from the serving process.** VACUUM and truncating WAL checkpoints need exclusive access, and a SQLite writer waiting for one blocks every writer queued behind it. This process can never grant that: the log-capture thread writes a row for every record the app emits, so the VACUUM waits for a quiet moment that never comes. The symptom is unmistakable and misleading — an idle database, no writes for minutes, every run creation failing with "database is locked" despite the 30s busy timeout. Production wedged this way from both sides of the lifespan. `_reclaim_disk_space()` in `app/app/main.py` therefore prunes superseded checkpoints and stops there; the file keeps its high-water mark, which is the accepted cost. `store.compact_database()` was **removed entirely** so nothing could reintroduce a serving-process VACUUM (`app/tests/test_diagnostics.py` documents the removal); offline compaction means running VACUUM by hand against a stopped database.
- **Never hold the SQLite write lock across network I/O, and never write on a poll tick.** There is one writer and no fair queuing, so a transaction spanning an LLM call freezes every other writer for its duration, and a per-tick write stream starves waiters indefinitely. Both look identical from outside: an idle-looking database while ordinary API writes exhaust their busy timeout. Hence the shape of the code — `claims/grounding.py` splits `assess_hypothesis_claims` (provider work, no DB) from `persist_grounding` (writes only) so `engine_adapter/drain/final_state.py` assesses *between* two transactions; `store/tasks.py::_has_claimable_task` probes read-only before `claim_task` opens `BEGIN IMMEDIATE`; and `task_worker/`'s heartbeat wakes each second to check cancellation in memory but renews its 300s lease only on the lease's own schedule. That heartbeat is a coroutine on the durable task's own event loop, so a wave of assessment calls run synchronously on that loop starves it just as surely as a write does — finalize's grounding wave learned this the hard way (run b82f9162, 2026-09-06: the wave ran ~230s+ synchronously, the heartbeat never got to tick, and a healthy task lost its lease and its retry budget), so `engine_adapter/drain/final_state.py::_assess_claims` now runs its wave off the loop (`async_bridge.run_off_loop`) and awaits it, the same way the pre-ranking gate (`engine_tasks/gate.py::_assess_gate_claims`) already did. When a lock symptom appears with an idle database, run `py-spy dump` first.
- **Startup work runs before uvicorn binds a port — keep it cheap and never fatal.** Two rules pull in opposite directions, both learned in production (`main.py` lifespan). Run recovery does not schedule interrupted runs, it *executes* them, so awaiting it put provider calls ahead of the port and blew the deploy healthcheck — and a failed healthcheck kills the container mid-run, leaving one more interrupted run for the next boot, so each attempt started further behind. It is now `asyncio.create_task` alongside startup with its cohorts on `asyncio.to_thread` (their SQLite writes are synchronous and would starve the loop). The checkpoint sweep, by contrast, must stay **inline**: it needs the reader-free window startup uniquely provides, since alongside a serving process a long-lived SSE reader blocks it forever. It catches `sqlite3.Error` and continues, because a full volume is exactly the state in which the DELETE that relieves it cannot get its journal written. Serving with a bloated table beats not serving.
- **Only `UnsupportedTaskError` and `LLMCallBudgetExceededError` are permanent task failures** (`app/app/task_worker/__init__.py`). The second was added after a single incomplete production run spent $4.70 over ~1,000 provider requests, ~613 of them the pre-ranking claim gate's own entailment calls (`app/app/claims/verifier.py`), against a 2500-call ceiling that could not see them: the gate called `litellm.completion` directly rather than through the engine's `call_llm`, so `co_scientist.llm.admission.call_budget.record_provider_request` never fired for them. The gate now routes every entailment call through `co_scientist.llm.call_llm_json` (`app.async_bridge.run_coroutine_sync` bridges the synchronous `Assessor` protocol to that async seam), so the ceiling sees them like any other engine call: retrying a run that has already exhausted its spend ceiling only spends more, so it terminates the run rather than consuming its retry budget (see `co_scientist.llm.admission.call_budget`). A later ultra run (b82f9162) measured 218 of those calls in a single pass across 13 hypotheses — one call per atomic claim, repeated before every ranking wave; `claims.assess_claims_batch` now judges a whole hypothesis's claims in one call instead of one call per claim, so the same pass costs 13 (or up to 26 if a hypothesis's claim count forces a split). A free reasoning model then spent that batched call's whole budget on chain-of-thought and answered nothing on both the original and raised-budget rungs (run b82f9162, 2026-09-06: 21054 and 26332 reasoning tokens against 18000- and 24000-token budgets) — entailment is a classification judgment, not a task reasoning earns its keep on, so `claims/verifier.py` and `claims/verifier.py` now run both the per-claim and batched entailment calls *requesting* thinking disabled from the first attempt (`LLMCallOptions(enable_thinking=False)`), with `max_attempts=3` so a schema/parse failure still gets a plain re-ask. That request is not always honored: this chain's free OpenRouter variants reject a disabled-reasoning request outright rather than degrading — `minimax/minimax-m3:free` (the deployed primary) 400'd every batched call on both attempts of one recovered finalize with `"Reasoning is mandatory for this endpoint and cannot be disabled"` (run b82f9162, 2026-09-06 04:39:30 UTC), so every hypothesis fell back to the deterministic lexical-overlap assessor for the rest of that pass. `co_scientist.llm.request.thinking` now decides what actually reaches the wire, not the call site: a model declared unable to honor a disable (`ModelProfile.reasoning_can_disable`, default False for every declared free-chain entry — none has evidence otherwise) is sent the smallest reasoning tier the gateway exposes instead of a bare `enabled: False`, funded by the same `THINKING_FLOOR_MAX_TOKENS` floor a normal thinking call gets (`effective_thinking_enabled`) so the redirect cannot itself reproduce an answerless completion. The retry ladder carries the same fix for a model the table gets wrong: `llm.attempts.escalation.escalation_for_error` recognizes this exact 400 message and escalates to a dedicated `MINIMAL_REASONING_REQUIRED` rung — reasoning forced back on at minimal effort and a raised budget, applied via a scoped context var (`llm.request.gateway_body.scoped_minimal_reasoning`) rather than resending the identical rejected request or giving up — terminal after one recovery attempt so a provider that rejects minimal reasoning too still exhausts its attempt budget instead of looping. Every other exception keeps its retry budget (`max_attempts` defaults to 3), so widening that branch strands runs — the reported shape is bursts of progress separated by silence, tasks sitting at attempt 1/3 with retries unused. Nothing *automatic* recovers a `failed` task: `resume_run_tasks` only requeues `paused`, and the expired-lease rescue skips tasks whose attempts are spent. Recovery is explicit — a Supervisor `retry` action or a resume, which must call `revive_task_for_retry` **before** enqueueing, since the idempotency key cannot change while the run makes no progress and `ON CONFLICT DO NOTHING` would otherwise create nothing. (Portfolio-enqueued node tasks key on `{task_type}:after:{predecessor_task_id}` rather than a checkpoint sequence, so that a lookahead row and the later reactive enqueue for the same logical edge collide onto one row instead of racing as two claimable duplicates; bootstrap, resume and scientist-continuation rows keep the original sequence-anchored form. Both are equally immutable while a run makes no progress, so this rule is unaffected by which one a task carries.) `revive_task_for_retry` rescues a `leased` task only once its lease has expired (its owner is then provably gone); reviving an unexpired lease would run the same boundary twice concurrently. A platform-wide rate-limit cap (`co_scientist.exceptions.LLMRateLimitParkError`, raised by the engine's shared retry classification when a 429's reset is too far off for the ordinary backoff to absorb) is neither: `task_worker.outcomes._park_rate_limited_task` returns the row to `queued` with its attempt undone and an `available_at` not-before the provider's reported reset, so the task waits out the cap and resumes on its own once a claim's due-time check passes, instead of spending retries against a ceiling that has not reset.
- **No process-global asyncio primitives.** Each durable run's worker cohort executes on its own thread with its own event loop (`task_worker.run_run_worker_pool_sync` calls `asyncio.run`), so several loops are live in one process. An asyncio primitive binds to the loop that first waits on it and raises from every other. The ranking judge semaphore is therefore created per running loop and held weakly (`agents/ranking/ranking_debate.py::_get_ranking_semaphore`) — as a module-level singleton it stayed hidden until tournament waves grew large enough to actually contend, then killed a production ranking task with "bound to a different event loop". Bound concurrency per loop, or via the cohort's `worker_pool_size`, never with a shared primitive. Module scope is safe only for primitives touched exclusively from the API loop.
- **Never score a short claim against a long document with Jaccard.** Jaccard divides by the *union*, which the longer side dominates, so the score is capped near `len(claim) / len(document)` however perfectly the document supports the claim. `citations.classify_citation` matched a one-sentence claim against a whole abstract that way: an abstract quoting the claim verbatim scored 0.18 against a 0.35 "verified" threshold, and a relevant paraphrase scored 0.078 against a 0.10 "partial" threshold, so **both upper states were unreachable** and every citation in every real run classified `unsupported` (one production run: `citation_audit verified=0 partial=0 unsupported=47`). It reads as a model or evidence-quality problem, not a metric bug, because the numbers are individually plausible. Use coverage — intersection over the *claim's* tokens — whenever the two texts are asymmetric, and sanity-check any new threshold by feeding it a document that literally contains the claim. Note the fix stops there: a bag-of-words score still cannot tell a claim's subject from its assertion, so an abstract sharing only the topic nouns lands in the same band as one stating half the claim. Sharpening that is the LLM entailment assessor's job (`claims.verifier`, feeding `claim_evidence`), not this deterministic fallback's — do not tune thresholds between two hand-picked examples, which is how the previous test ended up pinning the broken metric in place. That sharpening job can itself fail the same way: production ultra run b82f9162 (2026-09-06, free model, every verdict from the LLM assessor) came back 105 of 183 claim-evidence edges `contradicts`, including a quote about a different molecule/target scored as refuting the claim and a quote that *stated the claim's own mechanism* scored the same way — topically-adjacent and even confirmatory passages labeled as negations, which withheld 32 of 36 hypotheses from one report. The model's own "label" field was trusted verbatim with no check that a cited contradicting quote actually names the claim's own subject or carries a negation at all. Fixed in `app/claims/verifier.py::_reject_unfounded_contradiction` (and its `claims.verifier_batch` twin): a `contradicts` verdict is downgraded to `insufficient` — never promoted to `supports`, which would just invent the opposite mistake — unless at least one cited quote clears both a subject-coverage floor against the claim (reusing `claims.assessor._tokens`, at the same 0.25 bar the deterministic fallback itself requires before accepting a contradiction) and contains an actual negation/contrast cue (`claims.assessor._CONTRADICTION_MARKERS`). The gate's existing contradiction-dominates-support precedence (`claims/gate.py`, pinned by `test_contradiction_dominates_over_support`) was deliberately left alone: a real on-topic negation must still block a hypothesis outright, so the fix runs one layer below precedence, at the point where a contradiction is first believed, not at the point where it is weighed against support.
- **An early gate that never reverses decides the whole run, not just one node.** `agents/reflection/review.py::_apply_initial_review_gate` sets `review_disposition` once, from the *first* review, and nothing revisits it. A blocking value bars the idea from the Elo tournament for the rest of the run (`Hypothesis.is_rankable`), reads as "Disqualified" in the UI, and skips it in comprehensive reflection — and, because `_select_evolution_pool` breeds from the ranked survivors, it also shrinks the gene pool. One production run blocked 20 of 22 ideas, which left a two-idea tournament, an Elo ordering built from four matches, and an evolution pool that kept re-deriving the same drug; the visible symptom was "why is every idea about empagliflozin", not "the review gate is strict". So the thresholds track the rubric the prompt itself hands the model (`NOT_VIABLE_SCORE`/`NEEDS_REVISION_SCORE` in `constants/__init__.py` mirror its 1-2 "not viable" and 3-4 "needs substantial rework" bands) rather than being tuned independently — and note the batch prompt *requires* the model to spread scores across the pool, so a relative low scorer exists on every run whatever the absolute quality. Only the non-viable band blocks; the rework band is `needs_revision`, which ranks and publishes but skips the deep-review cascade. Two related traps: a *missing* score must not read as the worst score (it defaulted to 0 and disqualified the idea, and prod's json_object mode does not enforce the schema); and "excluded from the report" is not one fact — `duplicate` (proximity archived it) and `rejected` (it failed review) share `EXCLUDED_HYPOTHESIS_STATUSES` but must reach the reader as different words. Since 2026-09-07 the gate is no longer terminal, because no published listing grants it that authority: `review_gate.derive_review_disposition` derives the value from *every* review the hypothesis holds — the most recent review scoring a gated axis, then the mature cascade's deeper verdict, which wins except over `unsafe`, an axis that cascade is never asked about — and `refresh_review_dispositions` re-derives the pool wherever the record can have grown, at zero LLM cost. That only helps if a later verdict can arrive, and for a blocked idea none could (the mature cascade selects on `viable`), so `agents/reflection/review_gate.py` gives each blocked idea **exactly one** recurrent review per run, marked on the hypothesis with the `review_recheck_issued` enrichment — checkpointed, so a resume cannot re-fire the wave — and capped run-wide at `MAX_RECHECKS_PER_RUN = 24`. The cost is one call per blocked idea, once (about +20 on the incident run, ~1.6% of the express tier's ceiling), never a per-cycle multiplier; re-reviewing every blocked idea every cycle is the trap that was rejected, since blocked ideas are exactly the population that grows when the gate misfires.
- **The near-duplicate guard has to see everything it is guarding against.** `evolve.py` passes `other_hypotheses_texts` to `_apply_evolution_result`, which discards a child too similar to any of them. Sampling those from the round's `top_k` instead of `state["hypotheses"]` left the guard blind to every idea outside the current round, so duplicates passed and proximity archived them afterwards — the run still ends up with the near-identical ideas, just labelled later. The 15-item cap plus `sample_context_hypotheses`'s top-5-by-Elo-plus-random sampling is what bounds the token cost; against `top_k` that sampling never even ran.
- **Counts named for different things must be computed differently.** The report payload carries `idea_count` (everything explored), `hypothesis_count` (released by the safety/contradiction gates), and `verified_count` (released *and* carrying a `supports`/`partial` claim edge). Reading one where another is meant produces a report that contradicts its own tabs and looks like a data-loss bug: the lead stat read `hypothesis_count` and announced "A total of 2 ideas were explored" above a list of 22, and the "Verified ideas" tile was handed the High Potential count, so a run claimed two verified ideas while badging every idea "Unverified". `verified_count` is derived by `report.gates._verified_hypothesis_count`, the exact complement of `unverified_hypothesis_ids` over the released set, because the tile and the per-idea badge are one fact shown twice. For the same reason `idea_buckets` must partition — `non_viable` is defined as everything not in `high_potential`, so capping either half silently stops the pair summing to the run's idea count.
- **Structured-output schemas must not echo input back.** When a node's JSON schema names items from a pool, identify them by the positional index the prompt assigns, never by repeating their text — an echoing schema makes output length scale with the pool, so a large run overruns the token budget (46 hypotheses at ~1250 chars needed ~14k output tokens against 10k), truncates the JSON identically on *every* retry, and degrades silently. That is exactly how proximity clustering stopped deduplicating; `agents/proximity/proximity_dedup.py::_match_cluster_member` keeps text-prefix matching only as a fallback. **Trim the schema, never the input.** Proximity is the one node that sends the whole pool in a single prompt, which makes it the obvious place to economise by truncating hypothesis text — and the wrong one: it is being asked to find differences, three of its six similarity dimensions are argued in a hypothesis's tail, and its verdict *deletes* work, so a false "high" drops a distinct hypothesis silently. The saving is illusory anyway (a few thousand input tokens on a call whose spend is reasoning output). This was tried and reverted; `test_proximity.py::test_long_hypotheses_are_sent_whole` pins it out. If the prompt is genuinely too large, chunk the pool.
- **`max_tokens` funds the chain of thought too, not just the answer.** Reasoning is billed and counted against the same allowance even though it comes back in a separate `reasoning_content` field, so a budget sized for the answer lets a long chain of thought consume all of it: `finish_reason="length"`, empty `content`, paid for in full, then retried four more times by `call_llm_json`. Switching thinking on for a call site without revisiting its `max_tokens` in the same edit is what produces this; it did, on thirteen engine nodes and two app call sites at once. Both codebases therefore apply a floor rather than trusting per-site budgets — `co_scientist.constants.THINKING_FLOOR_MAX_TOKENS` via `_apply_thinking_args`, and `app.config.thinking_safe_max_tokens` by delegating to the engine's `effective_max_tokens` at app streaming call sites (streaming: `interviews/model.py`, `qa/__init__.py`, `run_start_announcement.py`; `claims/verifier.py` and `safety/semantic.py` are no longer on this list, both since routed through `call_llm_json`, which now applies the engine's own floor instead). The symptom is quiet: a run degrades a node at a time, and for the claim verifier it used to read as "the LLM assessor is configured but never wins" rather than as an error. Note that *omitting* `max_tokens` is not the safe option — it takes the provider's own default, which is small enough for thinking to exhaust; `safety/semantic.py` used to send no budget at all and every screened item was heading for `hold` + `requires_review`, i.e. runs parked for human adjudication on a truncation rather than on their content. A different failure of the same direct-litellm shape hit `safety/semantic.py` again in production on 2026-09-05: a json_object-mode model (`minimax/minimax-m3:free`, the free fallback chain's first rung) answered with the JSON wrapped in a Markdown fence, and a bare `json.loads` raised on it, holding every run at intake. Routing the call through `call_llm_json` fixed both failure modes at once, and establishes the standing rule: **an app-side call that parses JSON from a one-shot completion must go through `call_llm_json`, not a direct `litellm.acompletion`; app streaming/plain-text calls (`interviews/model.py`, `qa/__init__.py`, `run_start_announcement.py`, `goal_text.py`, credential probes) go through `llm_request.acompletion` and the shared `co_scientist.llm.complete_request` transport. They preserve streaming and caller deadlines, but have an independent operation budget/telemetry scope (`APP_LLM_MAX_CALLS`, default 4) rather than consuming a scientific run's allowance. One physical attempt is counted only after free admission; usage is summarized once per operation, never persisted per chunk/call. Streaming requests ask for final usage and keep missing usage unknown. See [the provider policy decision](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-provider-policies.md).**
- **A floor is not a guarantee, so the retry has to change the request.** A chain of thought fills whatever it is given: production calls came back with `reasoning_tokens` sitting exactly on `THINKING_FLOOR_MAX_TOKENS` and `content` empty, and then did it four more times, because `call_llm_json` re-sent the identical request each attempt. Retrying a budget failure unchanged is not a retry — it is the same doomed call billed five times. `llm.request.response._extract_completion_content` therefore splits the empty response by `finish_reason`: `"length"` raises `LLMBudgetExhaustedError` (a `ValueError` subclass, so callers written against the old contract still catch it) and anything else stays a plain `ValueError`, because only the ceiling case is answerable by a different budget — an empty answer at `finish_reason="stop"` is what a plain retry already recovers. `llm.attempts.escalation.BudgetEscalation` is the ladder the loop climbs on that error — climbed by the one attempt loop, `llm.attempts.retry.run_attempts`, which `call_llm_json`, plain `call_llm` and the tool turn all run on, so the three cannot drift apart (a direct `call_llm` caller such as literature-review synthesis used to get exactly one attempt and no way to recover from either shape): attempt N+1 raises the call's own budget by half again (floored at `BUDGET_ESCALATION_MAX_TOKENS`, capped by `BUDGET_ESCALATION_MAX_INCREMENT` so an already-huge caller can't escalate into an absurd request), attempt N+2 with thinking off — a flat `max(max_tokens, BUDGET_ESCALATION_MAX_TOKENS)` was tried first and silently no-ops for any caller already sized at that constant, which is exactly what `RESEARCH_OVERVIEW_MAX_TOKENS` was: the rung meant to change the request re-sent the identical one, spending the `RAISED_BUDGET` attempt for nothing before the ladder's own next rung (thinking off) moved on. The last rung is what makes it terminate — reasoning that ends at the ceiling has no observed natural length, so no finite budget is provably enough and "escalate further" alone could burn the whole attempt budget on ever-larger walls. Two shapes enter that ladder, at different rungs. `finish_reason="length"` climbs one rung, since a chain of thought cut off at the ceiling may have been close to finishing. A completion that *stopped normally* having spent reasoning tokens and written zero answer tokens raises `LLMThinkingOnlyError` and jumps straight to the top rung: the model chose to stop, so it never wanted for room -- production spent 1149 tokens of an 18000 budget that way and then failed identically on attempts 2 and 3, which is also why "a plain retry recovers it" is wrong. An empty response with *no* reasoning at all stays a plain `ValueError` and a plain retry. A schema or parse failure keeps the current rung, since more tokens do not fix a wrong answer — a failure kind only `call_llm_json` can raise (its schema validation and JSON parsing have no counterpart in a plain-text call), which is why its default attempt count stays higher than `call_llm`'s own: `call_llm_json` keeps 5, leaving headroom for a schema or parse failure to be answered by asking again, while `call_llm` defaults to 3 — exactly the number of attempts that walks every rung of the ladder above (original, raised budget, thinking off), since a fourth or fifth attempt with neither failure kind available would only resend the identical top-rung request. And when this happens, read the log line, not the call site: the failure log reports the *effective* budget via `llm.request.thinking.effective_max_tokens` because it used to print the pre-floor number, so a call carrying 18000 logged "max_tokens: 8000" beside "reasoning_tokens=18001" and read as a provider fault. A model that cannot disable reasoning at all overruns even the ordinary floor, and paying for that first, guaranteed-fail rung on every call is its own waste: production express run 323ff72c (2026-09-06 06:57 UTC) measured two batched entailment calls to `openrouter/minimax/minimax-m3:free` (`reasoning_can_disable=False`, redirected to minimal-effort reasoning per commit 7aaf3682) each spend roughly 20-21k reasoning tokens (20840, then 19761) against the 18000-token `THINKING_FLOOR_MAX_TOKENS` — so the redirect stopped the 400 but not the overrun, and every entailment call still paid for a doomed first attempt before the escalation ladder's `RAISED_BUDGET` rung (24000) answered it. `co_scientist.constants.MANDATORY_REASONING_FLOOR_MAX_TOKENS` (`llm.request.thinking.effective_max_tokens`, keyed on `_reasoning_forced_despite_disable`) now funds exactly that case — a call that asked `enable_thinking=False` but is going out reasoning anyway — at the same 24000 the ladder would have escalated to regardless, so the first attempt is the one that answers instead of the one that is guaranteed not to. The ordinary `THINKING_FLOOR_MAX_TOKENS` is unchanged for every call that actually asked for thinking; only the forced-despite-disable case gets the higher floor, keeping the redirect (which model, what tier) and its funding (how much room) one decision at one call site rather than two that can drift apart.
- **The token budget and the wall clock are one setting in two places.** Funding a chain of thought without extending the deadline only moves the failure — the call is abandoned mid-reasoning instead of returning empty — and both land in the same silent fallback, so the fix looks like it did nothing. `app.config.thinking_safe_timeout` mirrors `thinking_safe_max_tokens` and raises the deadline the same way, and `test_configuration.py` pins the floor against the token floor so a later tightening cannot re-break what raising the budget fixed. **On a streaming call, bound silence, not duration** (`app/app/llm_scope.py::stream_chunks`): a stream delivering tokens is healthy however long it runs, and on a thinking model the long-but-alive case is the normal one, so any total tight enough to catch a hung provider also kills a good turn. The interview and Q&A streams relay reasoning to the reader as it arrives, which is why a generous deadline there is visible progress rather than a blank wait — do not copy those numbers to a blocking call that shows the caller nothing. Silence is not the only shape a dead-looking stream takes: it can also end clean having spent every reasoning token and written no answer at all (production, 2026-09-06 — an interview turn relayed ~68k characters of chain of thought, then nothing, and "Interview Agent returned no message" was the only trace). Not a provider failure, so `interviews/model.py`'s streaming path retries the turn once with thinking off (`app.config.thinking_off_kwargs`) rather than surfacing an error, mirroring the engine's own non-streaming `LLMThinkingOnlyError` rung without importing that ladder — `goal_text.py` and `run_start_announcement.py` carry the same one-retry shape for the same reason.
- **A per-item LLM pass belongs to the caller that runs once, not to the one that runs per hypothesis.** Literature search carries a model-judged relevance pass costing one call per candidate (`relevance.apply_semantic_relevance`, up to `papers_to_read_count * 3`). The literature-review node spends that once per run to choose the evidence every later agent reads — proportionate. Then three agents started calling the same search path *per hypothesis, per cycle*: deep verification, comprehensive reflection (`full` mode) and evolution grounding, all through `deep_verification_evidence._retrieve_probe_evidence`. The product is what shipped: a `full` reflection item cost 20 LLM calls where the review inside it costs 2, deep verification the same 20 (18 judgments + 2 verification calls), and an express run configured for four ideas spent 299 calls against the 86 an older standard run spent for fifteen. Nothing errored and no single number looked wrong — the cost is a product of two independently reasonable choices, and it multiplies by pool size and iteration, so it reads as "the deep tiers are slow" rather than as a defect. `SearchConfig.semantic_relevance_enabled` is the opt-out and probe retrieval sets it, at the one seam all three callers share rather than in each agent. Two rules follow. Before adding a per-candidate or per-item LLM pass to a shared helper, check every caller's *multiplicity*, not just its correctness. And when a phase's cost jumps, read per-item telemetry (`scientific_tasks.result_json` carries each fan-out item's `model_usage`) before reading code: the 20-vs-2 split between two items of the same task type is what located this, and no amount of reasoning about the call graph would have.
- **A tool's `parameter_mapping` is written in its *caller's* vocabulary, and an unmapped name is passed through, not dropped.** Two canonical vocabularies reach `ToolConfig.map_parameters`: the search paths send `query/slug/max_papers/recency_years/run_id` (`evidence/search_query.py`, `literature_tools/validate_search.py`) and context enrichment sends `entity_name/limit` (`literature_review/enrichment.py`). A mapping written for the wrong one does not degrade quietly — every unmapped canonical name arrives at the MCP tool under its own spelling, the server's pydantic validation rejects the whole call, and the client then fails to JSON-decode that error body, so the log says `JSONDecodeError: Extra data` and `_call_search_tool` retries a permanently doomed call four times. `europepmc_search` and `preprint_search` shipped with the enrichment vocabulary while both are called from the search paths: Europe PMC returned nothing to any run from the day it was added (`3438c33c`, 2026-08-23) until this was fixed, and a run's log carried ~44 retry warnings for it. Two neighbours of the same shape: a tool that takes an id rather than a query must not be `category: "search"`, or the validation path resolves to it and hands it a query; and a tool list that mixes kinds must be filtered by what the *caller* can actually send, which is why `reflection_helpers.get_kg_tools_for_workflow` selects on `source_type: knowledge_graph` rather than on list position — it was calling PubMed with INDRA's `agent=` argument on every hypothesis, swallowed at debug level. `tests/test_tool_param_contract.py` is the guard: it parses the real signatures out of `engine/mcp_server` and drives every wired (canonical dict x configured tool list) pair through them, because nothing else binds the two packages.
- **Under the json_object downgrade, reshape the answer to the schema — in both directions.** A model without server-side schema enforcement omits required fields *and* invents extra ones, and every object node in `schemas/builders.obj` is closed (`additionalProperties: False`), so one invented key fails the whole response. Feeding the validation error back does not help: a production `research_overview` call answered with the same three invented sections (`knowledge_base`, `nih_specific_aims`, `research_contacts`) on all five attempts — five full paid calls on a large prompt, fourteen minutes, then the empty fallback. `llm.structured.validate.reshape_json_output` removes undeclared closed-object keys, fills required fields and caps oversized arrays and strings in one traversal. It runs under the downgrade condition (`llm.attempts.json_attempt._backfill_and_validate`), keyed on `_supports_json_schema_response_format`, so where the provider does enforce the schema an extra field stays a real validation failure. The reshaper also trims what the provider over-produces: over-long `maxItems` arrays and `maxLength` strings (cut at a word boundary near the limit where one exists) — added after production run b82f9162 failed generation/validation calls on a hypothesis `title` a handful of characters over its cap, on a free gateway model whose 100-requests/day cap made every such retry cost 1% of the day's budget.
- **Two independent wall-clock ceilings on outbound calls**, and they expire differently. `COSCIENTIST_LLM_TIMEOUT_SECONDS` (default 600s) bounds `litellm.acompletion` only; MCP tool calls are bounded by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). Set either to `0` to disable. The two MCP call sites diverge deliberately: `call_tool` raises `MCPToolTimeoutError` (callers degrade per-source), while `execute_tool_call` returns the timeout as the tool's *result*, because it runs under an `asyncio.gather` without `return_exceptions` where raising would kill every sibling call.

## Durable state reducers

Derive commit reducers from every accumulating `WorkflowState` channel. A
hand-maintained table omitted `tournament_matchups`, silently replacing prior
cycles of Elo history instead of appending them.

## Durable node names

Graph node keys persist in task types, checkpoints and idempotency keys.
Renaming a node requires a migration even when its implementation is unchanged.

## Contextual safety review

Danger nouns alone do not establish operational intent. Deterministic context
matches cannot clear themselves: only a contextual assessor can clear a held
verdict or strengthen it to a block. Operational hard blocks bypass that assessor;
unavailable or ambiguous review remains held.

Redact both report payload and Markdown: reports, events and public shares
expose them independently. Final-report redaction leaves the separately served
claim-evidence facts unchanged.

## Advisory reachability

Online audits retain every finding from all five locks. Historical findings in
LiteLLM proxy routes, FastMCP Windows/OAuth paths and pickle-backed DiskCache
were outside the deployed execution paths, not permanent waivers. Reassess
reachability when exposing those paths or changing the entry point, host OS or
storage topology; upgrade and validate deliberately rather than suppressing them.

## Credential boundaries

Internet-facing APIs require signed researcher identity; caller-selected client
IDs are development identity only. Keep MCP private with matching shared secrets.
BYOK encryption uses a separate key: rotation requires migrating or removing the
affected stored credentials. Keep database sidecars, caches and outputs out of
commits and image build contexts.

Use one provider-credential map for offline selection and semantic safety:
separate maps mistook credentialed Azure/Google deployments for keyless ones
and silently skipped provider work or contextual review.

Resolve every staged-document ID against its owner before committing a run or
interview; partial attachment silently changes the requested evidence. Deleting
a staging record leaves text already copied into a run as that run’s evidence.

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

## Per-run cache isolation

Per-run cache enablement must not mutate process environment or singleton defaults:
an offline demo once disabled caching for later real runs. Cost accounting uses
measured cache-read rates, and alternative offline-generator comparisons need
cold caches rather than responses cached by the first generator.

## Queued work and log cursors

Future-due queued tasks keep their worker cohort alive until they become claimable.
Retention and scoped log clears leave ID gaps: count matching rows after a cursor,
rather than subtracting cursor IDs.

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
only under persisted zero-price admission, without caller keys: campaign policy,
or the `zero_cost_admission` stamp a free run on all-free routes gets at creation,
which binds its engine tasks to zero-price-only requests. Unstamped runs fail closed.

Verification issuance markers survive failed attempts and checkpoint restore;
otherwise recovery funds the same evidence pass again. Periodic companion nodes
run serially and retain their list on restore to prevent checkpoint forks.
Successful simulation is not reissued because full review failed, and a failed
simulation is not retried after full review succeeds.

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
missing metadata paths; bubblewrap skips absent `--ro-bind-try` paths. Redact
stdout before model transcripts and drop the output if a secret still survives.

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

FastMCP may return an execution error as ordinary result text. Treat its error
envelope and campaign-policy refusals as permanent query failures. Transient
transport failures use bounded, jittered retries; distinguish failed queries
from successful zero-hit responses.

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
for the other. The 130-source cap targets about 52,000 evidence tokens;
adding full texts requires selecting passages rather than lifting those caps.

Fit synthesis to the provider clock as well as its output allowance: an observed
42,000-token request at 27–37 tokens/second could not fit a 600-second deadline.
Outline once and write bounded parts, preserving successful siblings and grounded
draft fallbacks when a part fails.

## Safety deferral and proximity storage

Unsafe-content stops never defer to owed review or tournament coverage.
Cleanup may exceed ordinary work ceilings only within its settlement allowance
or permanent issuance markers; provider admission still caps new requests.

The proximity edge floor bounds checkpoint size and the SQLite writer's insert
workload, while every pair is still measured. Round before admission so the
persisted similarity is the value compared against the floor.

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

`POST /api/feedback` requires the caller's usual owner identity (a researcher
session in required auth mode). It accepts the five fixed categories, a trimmed
message (8,000 characters), session diagnostic export (100,000 characters), URL
(2,048 characters) and optional reported run ID (128 characters). The run ID is
context only: it never grants access to that run or fetches its artifacts.

Maintainers read submissions from the `feedback` table in the SQLite store; there
is no HTTP read route and no SMTP delivery.

The SQLite store keeps the newest 200 submissions within a 10 MiB UTF-8 payload
budget. Submissions prune records older than 30 days.
Admission limits are 5 per owner, 20 per connecting host and 100 globally per
rolling minute, retained independently of row eviction and process restarts.
Excess requests receive HTTP 429 with `Retry-After: 60`. The connecting host is
hashed for admission checks and is not returned with submissions.

Feedback silently uses the existing tab-session anchor and diagnostic exporter
(preamble, session details, statistics and records), including operational INFO
records hidden by the Logs panel's default noise filter. It keeps the newest
loaded records within the attachment limit; a failed log fetch produces an
explicit diagnostic-unavailable record so the message can still be submitted.
The Logs pill, panel and default filtering stay unchanged.

New metadata captures chat roles, character counts and response durations, tool
names and execution durations/outcomes, failed-fetch method/path/status (without
query strings or payloads), modal opens, and engine-stage execution spans
(including failure and cancellation). Provider retries are INFO and escalations
retain their existing WARNING level. Chat text and tool arguments/results are
not added to these metadata records. Existing ten-minute duplicate suppression
and the WARNING floor for per-call HTTP dependency chatter still apply.
