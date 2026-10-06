# Engine — `co-scientist-engine`

Internal multi-agent hypothesis-generation engine. Repo-wide conventions, cross-cutting Gotchas, and required environment live in the [root AGENTS.md](../AGENTS.md) — read that too.

Package name: `co-scientist-engine`. Source under `src/co_scientist/`.

**Commands** (run from `engine/`):
```bash
pip install -e '.[dev]'          # install with dev deps
pytest                            # unit tests (testpaths = ["tests"])
ruff format .                     # format (100 cols)
ruff check .                      # lint
mypy .                            # typecheck
```

Use the offline unit suites to exercise individual agents.

**Architecture**

`HypothesisGenerator` (`generator/core.py`) prepares capabilities, registry and
initial state for the app's durable tasks. Nodes live in `agents/`: Supervisor,
six specialists and Safety. `agents.NODE_TO_AGENT` maps persisted node keys to
agents; `task_runtime.execute_task_node` commits one node at a time.

| Node | File |
|---|---|
| Supervisor (planning) | `agents/supervisor/supervisor.py` |
| Orchestrator (per-cycle routing) | `agents/supervisor/orchestrator.py` |
| Literature Review (MCP-gated) | `agents/generation/literature_review/` (agent planning, analysis and synthesis); shared retrieval in `evidence/` |
| Generate | `agents/generation/generate.py` (+ `operations.py`, `debate.py`, `reviews.py`, `literature_tools/`) |
| Reflection | `agents/reflection/reflection.py`, `reflection_helpers.py` |
| Review | `agents/reflection/review.py` |
| Comprehensive Reflection | `agents/reflection/comprehensive_reflection.py` |
| Deep Verification (probing questions) | `agents/reflection/deep_verification.py` |
| Ranking + Tournament (Elo pairwise) | `agents/ranking/` (`review.py`, `ranking_debate.py`, `ranking_matchmaking.py`, ...) |
| Meta-Review | `agents/meta_review/meta_review.py` |
| Research Overview (synthesis/roadmap) | `agents/meta_review/research_overview.py` |
| Evolve | `agents/evolution/evolve.py` |
| Proximity (dedup) | `agents/proximity/proximity.py` |
| Safety screen (cross-cutting) | `agents/safety.py` |

Node keys persist in task types (`engine.node.<key>`), checkpoints and
idempotency keys. Never rename them without a migration for persisted runs.

**Generation planning and finalization have a public operation boundary.**
`co_scientist.agents.generation` exports `GenerationPlan`, `GenerationCounts`,
`GenerationResults`, `prepare_generation` and `finalize_generation`; their
implementation lives in `generation/operations.py`. The coordinator owns node-level
strategy execution and expansion research; the app owns durable scheduling,
lease guards and checkpoint commits. Finalization may call enrichment tools, so
run it outside store transactions. Preserve the characterized node-level/durable
assumptions-context and expansion differences when changing strategy dispatch.

Ranking, Reflection and Evolution also expose supported operations from their
agent packages. Ranking owns immutable prompt/median snapshots, per-match
judging/Elo and round lifecycle; node-level and durable callers retain their existing
pair-selection order and prompt inputs. Reflection owns single-item context and
evidence assembly; durable callers own issuance markers, aggregation and retry
conversion. Evolution owns `EvolutionContext`, its round builder and the
selected-parent outcome projection below prompt and task modules. Keep app
production consumers on public exports; `app/tests/test_architecture.py`
rejects private engine imports and engine-to-app dependencies.

Evidence helpers are imported from their defining modules in `evidence/`.
The internal `evidence.helpers` facade is removed; test/patch the module that
actually consumes a collaborator rather than relying on unused re-exports.

**Generator configuration and execution live in one concrete class.**
`generator/core.py` owns MCP availability and capability/state preparation;
`prepare_task_state` supplies initial state for durable execution. Evolution prompt rendering lives in
`evolution/evolve_prompt.py`, and novelty-validation stage orchestration lives
beside its LLM calls in `generation/literature_tools/validate.py`. Private helpers
are imported and tested from their defining modules; compatibility re-exports
are not a supported boundary. Ranking constructs each `RankingSide` directly
from its hypothesis's review, reflection and verification evidence.

**The topology is declared once.** `workflow_topology.WORKFLOW_ROUTES` names
each node's fixed, literature-gated or state-resolved successor.
`task_runtime.next_task_type` uses committed state, stops on `safety_blocked`
and returns `None` at termination. The app seeds fresh tasks and resumes its
persisted queue. `plan_portfolio` and `FANNING_NODES` layer durable scheduling
policy over those routes.

**The simulation review can run what it simulates.** Reflection's
`simulation` review asks the model to step through a hypothesis's mechanism
and find where it breaks; its prompt used to say *mentally, in your mind's
eye*. `agents/reflection/simulation_execution.py` gives it a confined
workspace and a bounded tool loop (`MAX_SIMULATION_TURNS`) first, and hands
what it observed to the same schema-constrained review call as before -- so
the verdict vocabulary and every downstream consumer are untouched, and a run
that cannot execute produces exactly the review it always did. This is the
first production caller of the **workspace** tool surface -- `call_llm_with_tools`
itself has driven the literature tools on these tiers for some time. Gated three ways,
all of which must hold: the app asks by **tier** on `extended`/`ultra` only
(`opts._apply_capability_opts` -- a tool loop per hypothesis is
a cost that multiplies by pool size; measured below), the engine refuses it for the offline
backend (`run_setup._resolve_simulation_execution`), and the review itself
falls back to mental simulation where no sandbox backend can confine a
command. Measured cost, four mechanisms through the real path concurrently
(`deepseek-v4-flash`, 2026-08-20): **231s wall clock for all four**, against
824s if they had run one after another -- so the pool multiplies *tokens*,
not wall clock, as long as the review fan-out actually runs concurrently.

What a simulation costs is decided by two things, and neither is the
turn count. **A tool loop re-sends its whole transcript every turn**, so
what accumulates in that transcript is re-bought by every turn after it;
the model writes its program by rewriting the file whole, and a
transcript traced turn by turn (2026-08-22) was **59% versions of one
program that no longer existed**, five rewrites of ~8k characters each.
`llm.tools.transcript.elide_superseded_writes` drops the text of a write a
later write to the same path replaced -- the file on disk still holds it
-- which cut that loop's total prompt spend by 37%, a fraction that grows
with the turn count. **And reaching a ceiling used to return nothing**: a
loop that had written a model, run it and read its numbers raised, and
the review fell back to imagining the mechanism it had just measured. It
now buys one closing turn with the tools withheld
(`llm.tools.loop_run._harvest_partial_answer`), so the ceiling degrades the
observation instead of deleting it.

With both in place `SIMULATION_TOKEN_BUDGET` could be **measured rather
than guessed**, and it moved from 150k to 45k. Seven budgets from 15k to
150k over four mechanisms, each observation scored by checking its
numbers against the tool output meant to have produced them, found
nothing above 45k worth paying for: ten more turns and three times the
cost bought no more grounded numbers and no longer an observation, and
the 150k arm scored *lowest* on grounding. The useful work is done in
six to eight turns. Note the constant is denominated in
`transcript_tokens`, a character-count estimate blind to the tool
schemas resent every turn, so it bills around 2.5x its face value.

Each review gets its **own** workspace
(`open_review_workspace(run_id, hypothesis_id)`) because review items fan out
as concurrent leased tasks. Whether it ran is stamped on the result by the
caller (`executed`), never asked of the model.

**The literature review can go back for what it did not answer.** Phases 1-5
search once, from the research goal, and synthesize what came back.
`src/co_scientist/research/` is a standalone capability that reads a result,
takes what it leaves open, and searches again -- a budgeted descent whose
breadth halves per level with a floor, so the whole cost is arithmetic before
the first call (`8 + 4 + 2` threads, never `8 x 4 x 2`). It imports nothing
else in this repo and states its needs as two protocols;
`src/co_scientist/research_adapter/` is the implementation of those for this
engine (MCP search and full text over the run's configured sources, the five
model judgements over `call_llm_json`, and the tier-to-ceilings tables), and
`literature_review/research_phase.py` is where Generation calls it. Assigning
the same loop to another agent is a budget and a seed-question policy, not a
second implementation -- which is exactly what Reflection is (below).

Seeded from the gaps Phase 3's per-paper analysis already recorded, so the
first level asks what the reading raised rather than what the goal suggests.
What it finds merges back into the review's own paper pool and its synthesis --
a finding that lived only in a ledger would be recorded and never used. Gated
the same three ways as the executed simulation: the app passes its tier
verbatim (`engine_adapter/opts.py`) and `research_adapter.budget` alone decides
which tiers buy it -- `extended` and `ultra` -- so the two sides cannot drift;
`run_setup._resolve_research_tier` refuses it where MCP is unavailable, since a
loop whose whole shape is search-read-search has nowhere to go; and a run with
no enabled search source researches nothing. Whether the literature review
*node* runs is deliberately not a gate -- the reviews below resolve the run's
sources from its tool registry themselves.
Unlike the tool loops, the offline backend is *not* a refusal -- these are
ordinary schema-constrained completions it answers deterministically, which is
what makes the whole path testable without a key.

Everything the phase did leaves the node in `research_ledgers` on the state
(plain data, because a checkpoint carries JSON only -- see
`research/serialization.py`), and each researched paper carries the id of the
search that surfaced it. The app writes both: `retrieval_calls` rows and the
`evidence.retrieval_call_id` that resolves to them, so a run can say which
query found a piece of evidence and which question that query was serving.
Note the channel is a *list* with an accumulating reducer
(`state.reducers.accumulate_research_ledgers`; the durable path reads it
off the same annotation through `task_runtime.channel_reducers`, so an
annotated channel cannot fall through to last-write-wins there). Research has two
owners, and under a single-ledger channel whichever ran last was the only one
on record.

**The deep reviews go back too, and their cost is a product.** The full and
simulation reviews already retrieve once per hypothesis;
`reflection/research_evidence.py` gives them the same loop as a second round,
sharing one gathering between both modes (`reflection/review_evidence.py`).
The policy is what differs from Generation's, and it has to be: the literature
review researches once per *run*, a review once per *hypothesis*, so a
per-hypothesis budget alone bounds nothing. Both factors are capped in
`research_adapter/__init__.py` -- what one hypothesis may buy
(`review_budget_for_tier`: 4 threads on extended, 5 on ultra) and how many
hypotheses buy anything (`reviewed_hypothesis_limit`: the 3 or 5 best of the
pool, ordered by the canonical `rank_by_elo` and selected from the whole pool
so the in-process node and a per-hypothesis durable task choose identically).
Note *which* half of that key decides: this node runs before ranking, so on the
first cycle -- where every hypothesis gets its one full review -- every Elo is
still the default and the tie breaks on the initial review's score, written by
the node immediately upstream. The product of the two caps is a per-*cycle*
ceiling of 12 threads on extended and 25 on ultra -- **not per run**: comprehensive
reflection runs once per cycle over a fresh top-3, and evolution rewriting a
hypothesis makes it need its full review, and so its research, again. A live
extended run (3 iterations) bought 9 gatherings and 28 review threads against the
12 this was previously quoted as bounding, so multiply by `max_iterations` for a
run-level number. That quote also depends on
the two review modes sharing one gathering per hypothesis: they are separate
leased tasks, and it is the run cohort executing them on one thread's loop
that lets the second reuse the first's in-flight retrieval. A lease lost
mid-task re-pays one gathering, as the probe round already did. Seeds are the
doubts this run already recorded about *this* claim: assumptions a previous
cycle's full review marked
uncertain or likely false, and its simulation's failure points. Research that
fails degrades to the probe round rather than failing the review, and the
ledger travels beside the review rather than inside it -- through the item
result and the fan-out aggregate -- so a provenance record does not ride into
every later checkpoint through `enrichments`.

**Deep verification is a third owner of that same gathering and costs
nothing extra.** It runs immediately after comprehensive reflection (and
the safety screen), on the same cohort's loop and over the same pool, so
`review_evidence.researched_articles_for` finds the gathering already in the
flight cache and merges those papers into its probe round
(`deep_verification._with_researched`). It deliberately *reads* and never
starts one: a gathering begun there would be a third per-hypothesis
retrieval multiplying by pool size and iteration, which is the exact shape
of the 299-call incident. An idea the reviews did not fund is verified
against its probes alone, as it always was. Its seeding needs no new policy
either -- research is seeded from assumptions a previous cycle marked
uncertain or likely false, and those assumptions are deep verification's own
output, so the loop it now reads from was already being pointed by it.

**And it precedes tournament entry**, mirroring `03-reflection.md`, whose
`ReviewHypothesis` performs the deep verification and only then creates
that hypothesis's `AddToTournament` task -- so no idea is ranked or bred
from before its core assumptions are probed. Blanket over the pool, which
is affordable only because it is incremental: `agents/reflection/deep_verification.py`
marks each idea with a checkpointed `deep_verification_issued` enrichment
when its attempt is *issued*, so the initial pool is verified once and
each cycle's new children once, never pool x cycles. Ideas the review gate
barred are skipped -- an idea that cannot enter a tournament has nothing
here to guard.

`workspace/` and `sandbox/` confine every command a node runs -- including
ones that outlive the call that started them
(`workspace/session.py`: `run_command` hands back a session id
rather than killing a command at its deadline, `poll_command` continues
it from a cursor, and `llm.tools.transcript.normalize_tool_transcript`
turns a turn cut off mid-call into an explicit aborted result instead of
a conversation the provider rejects). Reflection's simulation review and
the drafting skills are what run inside them.

Shared state flows through `WorkflowState` in `state/__init__.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/co_scientist/prompts/templates/` (also bundled via `package-data`), loaded by the `prompts/` package. YAML tool/domain configs live in `src/co_scientist/config/` with examples per domain (biomed/cyber/web-research/etc.).

Key supporting modules: `models/` (dataclasses: `Hypothesis`, `HypothesisReview`, `ExecutionMetrics`, `Article`; ID minting beside `Hypothesis`), `schemas/` (JSON-schema package for structured LLM output — prompt families in submodules, name lookup in `__init__.py`), `constants/` (Elo params, token limits, temperatures), `state/` (`WorkflowState` and its reducers), `cache/` (LLM response and node-output caches), `mcp_client/` (MCP connection, availability probes, campaign admission), `offline/` (the deterministic offline backend), `exceptions.py` (domain exception hierarchy), `progress.py` (shared progress-event emission used by all agent nodes), `tools/` (tool registry subpackage for YAML-based tool configuration).

Each of those packages keeps its public names in its `__init__.py` and splits the rest into prefix-free modules (`models/metrics.py`, `cache/__init__.py`, `offline/llm.py`): import a sibling by its full path and the package by its short one. `cache/` depends on the re-include lines for `co_scientist/cache` in the root `.gitignore`, `engine/.gitignore` and `.dockerignore`; without them git, ruff and the production image all drop it as a runtime cache directory.

**LLM dispatch and bounds.** Calls go through LiteLLM, in the `llm/` package (`llm/__init__.py` lists the layers, lowest first, and is the only import surface outside it; `tests/test_llm_layering.py` keeps the imports pointing down). Every completion is bounded twice: `llm.request.completion.llm_timeout_seconds()` (env `COSCIENTIST_LLM_TIMEOUT_SECONDS`, default 600s, `0` disables) is passed to litellm *and* re-imposed as a hard `asyncio.wait_for` ceiling in `llm.request.completion._acompletion_within_timeout` (+30s grace), raising `LLMTimeoutError`. Physical dispatch, admission and telemetry are shared with app calls in `llm/request/transport.py::complete_request`; stream consumption keeps the app's silence deadline. What answers that await is chosen in one place, `llm/request/backend.py`: a `CompletionBackend` with two operations, `complete(**request)` and `supports_json_schema(model)` (does this model take a native `json_schema` response format; it travels with the backend because the backend that answers a model's calls is the one that knows). `active_backend()` returns the installed one, `install_backend()` swaps it (and returns what it replaced), `using_backend()` scopes one to a `with`. The default, `LitellmBackend`, reads the live `litellm.acompletion` attribute at call time, which is why a patch on `"co_scientist.llm.litellm.acompletion"` still steers a call that is already built. `offline.llm.OfflineRouter` is the second adapter (`install_offline_router()` installs it once at process start and no longer assigns over `litellm`; non-`offline/` models go to the backend it replaced); the third is the recording fake in `tests/_llm_fake.py`, which `install_fake_llm`, `patch_acompletion` and `isolate_offline_router` ride. The registry is a plain module global, not a `ContextVar` (the cohorts' threads and event loops would not see a context set elsewhere) and holds no asyncio primitive. The capability answer is read in two places on purpose: `llm/request/schema.py` asks the installed backend on every call, so it decides which response format a call is built with, while `llm/attempts/json_attempt.py` binds the default answer at import, so the validation shim never sees an installed backend (`tests/test_llm_completion_routing.py` pins both). A test that needs the provider installs a fake backend rather than patching `litellm`.

Retrying lives in exactly one place, `llm/attempts/retry.py::run_attempts`: run attempts at escalating rungs, given how to make one attempt and, optionally, a `Judge` of the response (accept it, or reject it with feedback for the next attempt). `call_llm` supplies no judge and defaults to `max_attempts=3`, the number of attempts that walks the ladder's three rungs. `call_llm_json` supplies the parse/repair/validate judge (`llm/attempts/json_attempt.py`) and defaults to 5: its schema and parse failures keep the current rung and are answered by asking again, with the validation error appended to the prompt, which a plain-text call has no counterpart for. The tool turn (`llm/tools/loop.py`) supplies an attempt that stops before tool execution, so a retry never runs a turn's tools twice. The loop owns what a failed attempt is answered with, so there is one place to read it: the rung sequence (`llm.attempts.escalation.BudgetEscalation`; see the "A floor is not a guarantee" gotcha in `docs/OPERATIONS.md`); the never-retried set (`LLMTimeoutError`, `LLMCallBudgetExceededError`, `ContextWindowExceededError` — a stalled provider will not answer the same request faster) and the `FreeModelEligibilityError` re-raise; the platform rate-limit park (`LLMRateLimitParkError`, classified in `llm/attempts/retry.py`); a **jittered** exponential wait for a throttle and a longer schedule for an outage (`llm/attempts/retry.py`; unjittered releases every throttled caller at once and reproduces the burst); the process-wide throttle counter behind `rate_limited_attempt_count` (a plain int, never an asyncio primitive, because the worker cohorts' event loops share it); retry telemetry; and log severity (a warning, and an error only when it gives up). **Tool turns use the same bounded policy with three physical attempts per turn**, including jittered backoff, quota parking and retry telemetry. A retry never spans tool execution. Its rung-to-request mapping remains its own: the mandatory-reasoning rung raises the budget without switching to minimal effort. `tests/test_llm_attempt_loop_tools.py` and `test_llm_attempt_loop.py` cover the policy. The separate `AttemptPlan.escalation_only` contract retains a call-local visited-rung guard: each rung, including the initial rung, can be entered once, so alternating reasoning failures terminate within four attempts. Failures with no recovery rung propagate without backoff, parking or retry telemetry under that contract. Production tool turns use their three-attempt bounded plan instead, and bounded plans may revisit rungs within their configured allowance. Do not add another retry loop for a new call site: supply an attempt (and a judge) to this one.

**Model facts.** What depends on which model is called is one `ModelProfile` from `llm.profile.model_profile(name)` (also exported by `co_scientist.llm`): whether it reasons and how to ask it to (`reasons`, `thinking`, `reasoning_can_disable`), whether it takes a `json_schema` response format, its temperature floor, its gateway pin and fallback chain, its price, and whether it is an admitted promotional free route. A name resolves through `llm/profile/__init__.py` (substring/prefix families, e.g. DeepSeek) and then `llm/profile/__init__.py` (one entry per exact route, which overrides its family; the only place a price is stated — `constants.pricing.MODEL_PRICING` is derived from it). Add, retire or correct a model by editing that one entry; do not branch on a model-name substring at a call site. `tests/test_model_profile_snapshot.py` records every answer for every named route and fails if a regrouping changes one. `llm/request/thinking.py` is the routing *policy* applied to a profile (price multiple, upstream order, throughput floor, fallback cap); it states no per-model fact.

**MCP and the web.** Literature-review tools are pulled from an external MCP server via `mcp_client/` using `langchain-mcp-adapters`, bounded independently by `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` (default 300s). State preparation detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode. The literature-review pre-flight gate checks **server** reachability (`check_mcp_available`), not any single source's health: gating on one source let an unreachable remote service veto sources that were otherwise fine. For conditionally-registered tools, ask `mcp_client.check_tool_available(tool_name)`.

**A run that reaches no source now says so.** "Falls back to LLM-only" is four silent branches, not one: both paths route around `literature_review` and `reflection` (`workflow_topology`), `run_setup._resolve_research_tier` resolves to no research, and the deep reviews' probes and evolution's grounding each refuse themselves on `mcp_available`. All four are correct, and none of them is visible — the run publishes ideas, reviews and a tournament that look exactly like a healthy run's, with nothing saying they were never checked against a paper. `retrieval_degradation.py` turns that into a fact the run carries: set at setup and again if the server is lost mid-node, drained into the report payload, and carried on every node event after it so a watcher sees it live. The only thing that survives an MCP outage is a run's own attached documents, searched in-process (`run_attachments`); without those the floor is `none`.

The engine can also search and read the open web. `web_search` (MCP `search_web`) is a default `literature_review` search source alongside PubMed/OpenAlex, weighted lower (`papers_per_query: 2` against their 4) with `read_url` as its content tool; its results carry `source: "web"` so web evidence stays distinguishable downstream. It is deliberately absent from `validation` and `reflection`, which are direct-call paths. The agentic path — the model deciding when to search and what to open — lives in `draft_generation` and is active only when a caller passes `enable_tool_calling_generation=True`; the tools being available is a precondition, never on its own a request. The app opts in **by tier**, not by user toggle: `engine_adapter/opts.py::_apply_capability_opts` asks for it on `extended` and `ultra` only. Each tool call is an LLM round-trip that re-sends every prior result, so one hypothesis costs ~9 calls on prompts growing past 12k tokens, per cycle — measured as the largest single line in an express run's token budget during the window this was default-on. See `engine/docs/ARCHITECTURE.md` and `src/co_scientist/config/tools.yaml`.

**The drafting pass can query databases, not just read papers.**
`vendor/science-skills/` is Google DeepMind's Science Skills bundle -- 38
directories, each a `SKILL.md` of operational judgement plus a Python CLI
that queries one scientific resource (UniProt, STRING, ClinVar, gnomAD,
ChEMBL, ClinicalTrials, AlphaGenome, ...). `skills/__init__.py` reads it into
a one-line-per-skill catalogue for the prompt and returns a full document
only when the model calls `read_skill`; the scripts then run through the
workspace's ordinary `run_command`, confined like any other command, which
is why this needed no second execution path. The interpreter is baked at
image build (`COSCIENTIST_SKILLS_PYTHON`) because `uv` cannot run inside the
sandbox at all -- its cache contains a `.git` directory and `.git` is in
`PROTECTED_METADATA_NAMES`. Three things about it are load-bearing.

**Which agent gets them is decided per consumer, not per deployment.**
`WorkspaceSession.skills_enabled` defaults off and `workspace_tool_schemas`
takes it explicitly. The skills were wired into the simulation review first
and measured *negative* there over eighteen runs -- a reviewer that engaged
a skill produced an observation 5 times in 7 against baseline's 9 in 9, at
40% the length -- because that node's job is to build a model of a mechanism
and run it, and retrieval competes with that. The drafting pass
(`literature_tools/draft_skills.py`) is where retrieval *is* the job, and it
drafts a whole cycle's hypotheses in one tool loop, so the cost is per cycle
rather than the per-hypothesis multiplicity behind the 299-call incident.
Deep verification and evolution grounding are deferred for exactly that
reason. A single environment variable as the gate would have re-armed the
review the moment the bundle was installed for drafting.

**Disclosure is two levels deep.** 20 of the 38 skills give the overview in
`SKILL.md` and the command syntax in `references/*.md`. Serving only the
first level does not make the model stop -- it guesses, and a live pass
reached STRING's CLI with no subcommand for exit 2. `read_skill` therefore
takes an optional path inside the skill, resolved and checked to be within
it. The same preamble also tells the model there is no user to ask, because
several skills instruct it to stop and ask one.

**Offering them is not requesting them, and turns are not what they cost.**
With a descriptive prompt section the drafting pass ignored the surface
entirely across three mechanisms while paying 6.2k prompt characters a turn
for it; a directive instruction to check one entity against a database
before finalising is what produced use. Funding that with extra *turns* --
the obvious move -- bought nothing, because until transcript ageing landed
this loop was never turn-bound: for four hypotheses the iteration budget is
13 and live passes stopped at seven to eleven on the transcript backstop.
The catalogue is ~1.6k tokens on every turn and a skill document another
~3k on every turn after it is read -- a quarter of a finished pass's last
transcript, measured -- so `DRAFT_SKILLS_TOKEN_BUDGET` raises the transcript
ceiling instead, leaving the pass the same number of *working* turns rather
than trading drafting for lookups.
Two overheads are removed for any consumer: the catalogue is summarised to
routing sentences (12,079 to 5,155 chars, since every line is re-sent every
turn), and `skills/__init__.py` seeds the `.licenses/` notices 35 of the 38
skills demand before they will work, which cost a live loop four turns of
fourteen. Credentials reach a vendored skill script and nothing else
(`skills/__init__.py::invoked_skill`, which also names the source for
attribution) -- the same workspace runs model-written programs against an open
network.

**Every defect that stopped this working was a missing instruction, not
missing code.** The mechanism was complete and correct and produced zero
successful skill commands over two measurement rounds; three sentences in the
`read_skill` preamble and the `run_command` description took it to 4 of 4.
Skill scripts write their result to a file rather than stdout, and nothing
said where: a live pass lost a well-formed STRING query to
`--output /tmp/...` after paying for the API call. `run_command`'s
description stated flatly that there was no network, which is true of the
review workspace and false of the drafting one -- a model told the attempt is
impossible never makes it, so the sentence now follows
`SandboxPolicy.allows_network`. And the general rule about output paths only
got to 2 of 3: 27 of the 38 documents write `--output /tmp/out.json` in
*every* example, and a rule stated generally loses to a dozen concrete
counter-examples, so the preamble contradicts the pattern by name. Measured
over three research goals x four hypotheses on the production model: 0 of 7,
then 2 of 3, then 4 of 4.

**What it buys, in one instance.** A drafting pass read STRING's `SKILL.md`,
then `references/interactions.md`, ran `string_cli.py partners --identifiers
SLC9A1 --species 9606`, read the file back, and two of its four hypotheses
argued from the result -- "STRING database analysis confirms that SLC9A1
(NHE1) strongly interacts with MAPK3, PRKACA, CALM3, and ROCK1 (combined
scores 0.94-0.99)". A gap argued from a record rather than from what someone
wrote up. The ceiling on how often that happens was never the skills.
Measured on a live drafting pass, `search_pubmed` results were **96% of the
loop's transcript** (282k of 295k characters over 9 searches) and the skills
4%, which is why the loop used to stop on its token backstop rather than on
having finished. Two elisions fixed that, both in `llm.tools.transcript` and
both applied at `llm.tools.loop_run._drop_dead_context`, so every tool loop
inherits them. `elide_repeated_papers` drops a paper an earlier search in
the same transcript already returned -- 35% of records on that pass, 94
carrying 61 distinct papers. `elide_aged_evidence` is the one that removes
the growth: a record stays whole for two more assistant turns, long enough
for the model to judge a gap from its abstract, and is then cut to what a
draft cites it by, while a page fetched whole (`read_url`) is cut to the
call that can fetch it again. **Order is
load-bearing** and pinned by a test -- ageing runs first, because an elided
record is no longer a copy of anything, and reversed the two eliders between
them delete every copy of a paper found again after its first sighting aged
out.

Measured over three research goals x four hypotheses, before and after: all
three passes used to stop on the token ceiling at seven to eleven of
thirteen turns with per-turn spend climbing monotonically to 45k, 61k and
72k tokens; afterwards per-turn spend is flat and the same goals run to
their turn budget at 296k-363k total. Every arm produced 4 of 4 drafts, all
4 literature-sourced -- including the ceiling-hit ones, since reaching a
bound buys a closing turn rather than discarding the pass. What remains in a
finished pass's last transcript is 37% search results, 25% skill documents,
13% prompt, 9% echoed reasoning; nothing there grows with the turn count.
A stopping rule in the draft prompt was tried against the same three goals
and reverted: it produced one natural finish in three, did not reduce
searching, and drafts came back 14% shorter, which is the one thing that
phase is tuned for.

**Three of the sources are also first-class tools, on every run.** The
skills are gated: `extended`/`ultra` only, and only when the drafting model
chooses to reach for one. So the three it reached for on its own --
interaction networks, pathway membership, target association -- are
additionally declared in the *default* `config/tools.yaml` as
`search_string_interactions`, `search_reactome_pathways` and
`search_open_targets` (`mcp_server/tools/systems_biology.py`), wired into
literature-review enrichment and reflection. They are entity-keyed, not
free-text, which is why they sit on those paths rather than among the
literature search sources. Declaring them in the default config is the
load-bearing part: a tool declared only in an example is unreachable in
production, which is what the 8 INDRA CoGex tools still are.

**The catalogue withholds what it cannot run** (`_withholding_reason`), for
the same reason `run_command` is withheld with no sandbox backend: reading a
skill costs a turn and then several thousand tokens re-sent on every turn
after. Six of the 38 go -- four ship no script at all (`pymol` needs a binary,
`uv` and `credentials` describe setup the harness has already done and the
preamble contradicts, `workflow_skill_creator` authors skills rather than
using one) and two declare a 695 MB closure the image omits. 32 are offered,
and installing a package is all it takes to make its skill reappear.

**The sources a run queries are attributed to its reader.** `skills/__init__.py`
is a `scoped_telemetry`-shaped context variable -- the invocation happens in a
tool handler and the count is wanted at the node boundary, and each durable
run's cohort has its own loop, so a module-level total would mix runs. It
rides `ExecutionMetrics.skills_used` through the ordinary reducer, scoped by
the node-level generation call and per strategy task on the durable
path, into a report section naming only what was actually queried. This is what
discharges the third-party licence notices; the `.licenses/` file the skills
themselves ask for is written into a directory that is then deleted.

The run-level gate needs nothing new: the drafting pass only runs at all
when `enable_tool_calling_generation` is set, which the app asks for by tier
on `extended`/`ultra`, so the skills inherit that gate rather than adding a
second one to keep in step. Inert without `COSCIENTIST_SKILLS_DIR`, which a
checkout, a test and a CI job do not set -- which is also the whole offline
story, since an empty catalogue offers no skill tool and runs exactly as the
engine did before skills existed. Provenance and upstream revision: the
`NOTICE` at the repo root.

**Per-run tool disabling is reconciled once, at registry load.** Connector toggles reach the engine as `GeneratorOptions(disable_tools=[...])` (built in `app/app/engine_adapter/opts.py`), which `generator/run_setup.py` passes on as `ToolRegistry(disabled_tools=...)`. `registry._apply_disabled_tools` flips `enabled = False` on the tool *and* on every workflow `search_source` backed by it, covering every way a tool can be off — the `disabled_tools` argument, a YAML `enabled: false`, or a source naming a tool that does not exist. That one pass is load-bearing: the multi-source pipeline selects on `SearchSourceConfig.enabled` alone and never consults the tool's own flag, so a source left enabled over a dead tool keeps being searched. The Phase 2 searches in `evidence/search.py` therefore trust `workflow.get_enabled_search_sources()` and deliberately do not re-check the registry — a second filter there was removed once the registry covered every case, so new gating belongs at the registry, not at the call site. `engine/tests/test_config_registry.py` pins the reconciliation.

**Evidence budget and `reserved_slots`.** Multi-source search fills its budget through `evidence/search_fusion.py::select_within_budget`, not by truncating the ranked list. Retrieval score rewards source quality, citation count, and recency — axes a source can lack entirely rather than score poorly on, so it sorts below every indexed paper however well it matches. Such a source can claim guaranteed places via `reserved_slots` in its `SearchSourceConfig`; reserved places are filled best-first within the source, never padded, never over budget. No shipped source currently uses it (`test_the_shipped_sources_reserve_no_slots`).

Caching (`cache/`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

Engine architecture lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Use [`../docs/RUNNING-LOCALLY.md`](../docs/RUNNING-LOCALLY.md) for setup and
[`../docs/OPERATIONS.md`](../docs/OPERATIONS.md) for operational invariants.

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Registered tool families (see `mcp_server/server.py`): PubMed search + full-text retrieval, OpenAlex search, ChEMBL/UniProt lookups, INDRA CoGex queries, and web search/fetch.

**Style conventions:**
- Ruff formats and lints Python at 80 columns; config is in `pyproject.toml`.
- Apply the hidden-reasons documentation policy in [`../AGENTS.md`](../AGENTS.md); docstrings are optional.
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalized.
- No emojis or unicode decoration in code or logs.
- Keep terminal presentation libraries outside runtime engine code.

## Reference MCP server (`engine/mcp_server/`)

A separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors.

The live manifest groups the sources into four families:
- **Literature** — `search_pubmed`, `pubmed_search_with_fulltext`, `check_pubmed_available` (Biopython/Entrez), `search_openalex` (keyless, cross-disciplinary), `get_opencitations_citation_edges`, `search_europepmc` and its `search_preprints`/`search_biorxiv` preprint-restricted siblings, `search_arxiv` (arxiv.org's own export API, keyless).
- **Open web** — `read_url` (always registered), `search_web` and `check_web_search_available` (both key-gated).
- **Biomedical and systems lookups** — ChEMBL, UniProt, STRING, Reactome, Open Targets, Ensembl, gnomAD, GWAS Catalog and ClinicalTrials.
- **8 INDRA CoGex knowledge-graph queries.**

The `_MCP_TOOLS` tuple in `server.py` is the single source for both registration and the `mcp_tools` manifest at `GET /`. **Adding a tool takes two edits**: register it there, and declare it in the engine's `src/co_scientist/config/tools.yaml` with a matching `mcp_tool_name` (plus the `draft_generation` whitelist if the model should call it directly).

- **Registration says a key was set, not that it works.** A provider that refuses the key -- revoked, unpaid, or out of quota -- leaves `search_web` registered while every search degrades to `{}`, which reads downstream as "the web had nothing on this". Brave withdrew its free tier in Feb 2026 and exhausted keys answer `402`, so this is not hypothetical. `web_providers._handle_provider_error` records the refusal per provider -- 401/402/403, plus Tavily's 432/433 for a month's credits spent, but never 429, which self-heals -- logs it at ERROR, and `check_web_search_available` reports it. That tool, not the presence of `search_web`, is what the app's connector probe asks. A search that succeeds clears that provider's record.
- **Two keys chain, they do not choose.** `candidate_providers` drops refused providers, so a search whose provider is out of credit falls through to the next configured one *within the same call* and later searches skip the spent provider entirely. `WEB_SEARCH_PROVIDER` names the preference, not the only provider. Two rules keep the arithmetic honest: an empty result is an answer and does **not** fall through (re-asking would spend two allowances to hear "nothing" twice), and when every provider has been refused the preferred one is still tried, since a record only clears on a success and a monthly reset would otherwise stay invisible until the process restarts.
- **`search_web` is registered only when a provider key resolves** — `BRAVE_API_KEY` or `TAVILY_API_KEY`, with `WEB_SEARCH_PROVIDER=brave|tavily` selecting one (otherwise autodetect, brave first). Without a key the tool is *absent from the manifest*, not failing — so "the agent never searched the web" is a deployment question first. `curl http://localhost:8888/` returns the live `mcp_tools` list plus `integrations.web_search_provider`.
- **`read_url` fetches a URL an LLM chose**, so every URL passes `web_fetch.check_fetchable`: http(s) only, cloud metadata hosts blocked, and the hostname resolved via `getaddrinfo` *before* the range check, so `nip.io`-style names pointing at loopback/private/link-local addresses are refused too. `web_fetch.py` follows redirects manually (`follow_redirects=False`, max 5), re-screening each hop, because httpx's own redirect handling would skip the check. In production this server sits on Railway's private network next to the api, so weakening the guard is a live SSRF. Page content is untrusted data, never instructions.
- **Every tool is wrapped by `tool_logging.with_call_logging`** in the registration loop, emitting one INFO line per call (`tool search_pubmed(query='...') -> 2 items, 4102 chars in 812ms`). These tools degrade to an empty result rather than raising, so a missing key, a failed HTTP call, and a genuine zero-hit query are otherwise indistinguishable. Any wrapper added here **must copy `__signature__`** — FastMCP derives the advertised parameter schema from it, and a bare `*args, **kwargs` wrapper silently strips every parameter from what the agent sees.
- **Its own env surface**, in `engine/mcp_server/.env.example`, loaded from a `.env` co-located in `mcp_server/` (not the engine's; a missing file only warns): `ENTREZ_EMAIL`/`ENTREZ_API_KEY`, `COSCIENTIST_LIT_REVIEW_DIR`, `COSCIENTIST_MCP_PORT`, `COSCIENTIST_MCP_LOG_LEVEL`, `COSCIENTIST_MCP_SHARED_SECRET` (optional shared-secret auth — see `docs/DEPLOYMENT.md`), `WEB_SEARCH_PROVIDER`/`BRAVE_API_KEY`/`TAVILY_API_KEY`, `INDRA_COGEX_URL`/`INDRA_COGEX_TIMEOUT`. Setting these in the app's `.env` does nothing. An inherited `DISABLE_SSL_VERIFY=true` is rejected; the service never disables TLS verification globally.
- **Its own pytest suite.** `mcp_server/` is its own project; the engine's `testpaths = ["tests"]` does not reach it and the engine's mypy excludes it. Run `pytest` *and* `mypy .` from `engine/mcp_server/`.
