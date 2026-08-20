# `langchain-ai/open_deep_research` — analysis

Clone pinned at `1b7d2e80` (MIT, last commit 2026-08-10). Read against the
question this cycle asks: what can we lift, and what must we only learn from,
to close `GEN-TECHNIQUES-001` and `REFLECT-TYPES-001`?

**Why it is first on the list:** it is LangGraph, like our engine. The
concurrency, budget and compaction patterns below are expressed in exactly the
primitives `engine/src/co_scientist/` already uses, so they transfer as code
shapes rather than as ideas needing translation.

## What the thing is

Five nodes, ~2,350 lines of source, three graphs nested inside each other.

```
clarify_with_user → write_research_brief → research_supervisor → final_report_generation
                                                  │
                                    supervisor ⇄ supervisor_tools
                                                  │  (spawns N in parallel)
                                            researcher ⇄ researcher_tools → compress_research
```

- `deep_researcher.py` (718 lines) — all five nodes and all three graph builds.
- `state.py` (95) — the three state objects and the structured-output models.
- `configuration.py` (251) — every budget and model role as a typed field.
- `utils.py` (925) — search wrappers, MCP loading, token-limit detection.
- `prompts.py` (367) — five prompts, one per node.

The `src/legacy/` tree holds the earlier plan-and-execute and multi-agent
implementations. Ignore it: the current one supersedes both.

## The five ideas worth taking

### 1. Delegation is a tool call, not a graph edge

`ConductResearch(research_topic: str)` is a Pydantic tool the supervisor model
calls (`state.py:16`). The supervisor decides *how many* researchers to spawn
and *what each one is for*, in one LLM turn, by emitting N tool calls.
`supervisor_tools` then invokes `researcher_subgraph.ainvoke(...)` once per
call under `asyncio.gather` (`deep_researcher.py:288-300`).

This is the cleanest answer to a question our generation coordinator currently
decides statically. It also means the *reason* for each subagent is written
down as an argument — a paragraph-long topic description the prompt explicitly
demands — which is exactly the provenance we want on a research thread.

### 2. Budgets are typed config fields, and overflow answers rather than fails

Four separate ceilings, each a `Configuration` field with a UI-metadata
description: `max_concurrent_research_units`, `max_researcher_iterations`,
`max_react_tool_calls`, plus per-model `*_max_tokens`.

The overflow handling is the part to copy. When the supervisor asks for more
concurrent units than allowed, the extra calls are not dropped and do not
raise — each gets a `ToolMessage` back saying *why* it did not run and what
number to retry with (`deep_researcher.py:307-313`). The model then re-plans
against the real budget instead of silently losing a thread. That is the same
principle as our "a crashing variant must return a score, not raise" rule, one
layer up.

### 3. Compression is a node, and token-limit is a control-flow signal

`compress_research` (`deep_researcher.py:511`) runs after each researcher
finishes and before its output reaches the supervisor. On failure it inspects
the exception: if `is_token_limit_exceeded`, it calls
`remove_up_to_last_ai_message` to drop the oldest turn and retries, up to
three attempts, then returns an error *string* rather than raising.

`utils.py:665-830` is the reusable asset here — provider-specific token-limit
detection for OpenAI, Anthropic and Gemini, plus a model→limit table. Our
`llm_failure.py` / `llm_json_escalation.py` classify provider errors already;
this is a second opinion on the same problem, worth diffing against ours
before we write our own for a new provider.

### 4. Raw notes survive compression

`ResearcherState` carries both `compressed_research` (what the supervisor
sees) and `raw_notes` (every tool and AI message, concatenated). Both flow up
through `override_reducer` into `AgentState`.

This is the seed of the artifact store the survey argues for, and it is the
one place ODR gets provenance structurally right — though only as concatenated
strings, not addressable objects. We should take the *split* and reject the
representation.

### 5. Model roles are separated at config level

Five roles — summarization, research, compression, final report, and the
supervisor's own — each with its own model string, max-tokens and API key
resolution. Nothing in the graph hardcodes a model.

Our `llm.py` dispatch already does role-based selection; the lesson is the
granularity, specifically that *compression* and *summarization* are their own
roles and want cheap models, which is where a deep-research loop's token
budget actually goes.

## What we should not take

- **`clarify_with_user`.** Our runs are durable and asynchronous; a blocking
  clarification turn does not fit the task queue, and steering already has a
  designed path (`HITL-STEERING-001`).
- **The final-report node.** It writes one long markdown document from notes.
  Our terminal artifact is a ranked hypothesis pool with grounded claims, not
  a report; this node has no analogue and importing it would invent a second
  output surface.
- **`raw_notes` as concatenated strings.** Loses the query, the URL, the
  timestamp and the span — everything replay needs.
- **The bare `except ... or True` in `supervisor_tools`** (`:334`) silently
  ends the whole research phase on *any* subagent exception. Under our durable
  task model that is a stranded run, not a degraded one.
- **Tavily coupling.** `get_search_tool` hardcodes a small provider set. We
  reach search through MCP, which is strictly better for our case, and ODR's
  own `load_mcp_tools` path shows they are converging on it.

## Reuse verdict

**Copy with attribution:** the token-limit detection and message-trimming
helpers in `utils.py` (`is_token_limit_exceeded`, `_check_*_token_limit`,
`get_model_token_limit`, `remove_up_to_last_ai_message`) — MIT, self-contained,
no LangChain-version coupling beyond message types we already use.

**Port the shape, write our own code:** the supervisor/researcher subgraph
split, delegation-as-tool-call, the four budget ceilings, overflow-answers-
instead-of-fails, and the compress-before-return contract.

**Learn only:** everything else.
