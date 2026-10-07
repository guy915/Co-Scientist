# ADR-004: LLM gateway interface

**Status:** accepted, 7 October 2026. Re-architecture phase 1.

## Context

Model calls take two paths today:

- **Science calls** go through the engine's `co_scientist.llm`:
  `call_llm`, `call_llm_json` and `call_llm_with_tools` run the attempt
  ladder (retry, budget escalation, JSON repair) over `complete_request`,
  the one physical-call seam, which applies provider constraints and
  zero-price admission.
- **Surface calls** (chat, interviews, Q&A, start announcement, goal text,
  BYOK validation) go through the app's `llm_request.acompletion`, which adds
  the BYOK check, the offline guard, the surface output cap and the daily
  usage reservation (`provider_usage.reserve`) before the same
  `complete_request`.

Policy that decides whether and how a call is sent is spread over the app's
`llm_request`, `llm_scope` (surface call budget and telemetry),
`execution_policy` (zero-cost admission for a run), `process_mode` and
`offline_guard` (offline decision), `provider_usage` (daily budget,
raising `HTTPException`), `config` (thinking and DeepSeek delegates) and
`credentials` (BYOK validation through `litellm`). `litellm` is imported in
three app modules. `co_scientist.llm/__init__.py` resolves 33 exports from
dotted strings at first access to avoid import cycles.

## Decision

**`co_scientist.platform.llm` is the gateway.** Every model call in the
product goes through it, and nothing outside it imports `litellm` or a
provider SDK.

**Interface** (the package `__init__.py`, explicit imports, no string-based
lazy loader once its cycles are gone):

| Entry point | For |
|---|---|
| `call_llm(prompt, spec, options)` | One text answer with the attempt ladder |
| `call_llm_json(prompt, spec, options)` | One structured answer validated against `spec`'s schema |
| `call_llm_with_tools(prompt, spec, loop, options)` | A bounded tool loop |
| `complete_surface(surface, **completion_args)` | A surface call (streaming or not): BYOK, offline guard, output cap, daily reservation, surface budget |
| `CompletionSpec`, `LLMCallOptions`, `ToolLoop` | Typed inputs |
| `scoped_zero_cost_admission(...)`, `scoped_completion_budget(...)`, `scoped_api_key(...)`, `scoped_telemetry(...)` | Context a caller (the orchestration runtime, a surface) opens around its calls |
| `ModelProfile`, `model_profile(name)` | Read-only model facts for callers that size prompts |
| `ModelCallStats`, telemetry snapshot | Usage numbers for the persisted metrics |

The existing three science entry points keep their signatures; phase 5 only
moves the surface path and the app-side policy behind the same package:
`llm_request.acompletion` becomes `complete_surface`; `llm_scope`,
`execution_policy`, `process_mode`, `offline_guard`, the DeepSeek and thinking
delegates in `config.py`, `credentials.validate_byok_credential` and the
`litellm` logging-worker stop in `async_bridge.py` move inside it.
`provider_usage` keeps its SQL in a repository and raises a gateway error that
`api/` maps to the same HTTP response as today.

**What stays outside:** who may run what (free allowance, ownership, BYOK
storage) is `domains/access`; the gateway receives the decision as context
(`scoped_api_key`, zero-cost admission) and never reads those tables itself.
Prompts and schemas belong to the science agents; the gateway sees only the
rendered prompt and the schema.

**Invariants it owns** (unchanged, from `docs/OPERATIONS.md`): bounded
provider calls, token and reasoning budget escalation within the profile's
ceiling, spend caps, zero-price admission for free runs, free routes without
paid fallbacks, one physical-call seam with no retry of its own, failure logs
at the retry boundary only, and offline isolation.

## Consequences

- One place to add tracing (ADR-005): the attempt ladder and
  `complete_request`.
- App code calls one function per kind of call and never sees provider
  details; the three `litellm` imports in the app go away.
- `engine/tests/test_agents.py`'s internal ordering of the gateway's
  subpackages (`profile`, `values`, `admission`, ...) remains the gateway's own
  layering rule.
- Behavior does not change: same requests, same budgets, same retries, same
  telemetry fields. Each phase 5 gateway PR runs one Express benchmark.
