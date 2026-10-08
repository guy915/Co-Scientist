# ADR-005: Tracing

**Status:** accepted, 7 October 2026. Re-architecture phase 1; built in
phase 6. Span names and attributes are listed in `docs/MONITORING.md`.

## Context

Run diagnostics today are persisted logs (`app_logs`), per-call model
telemetry folded into run metrics, `run_events`, and Sentry for errors
(`error_tracking.py`, off unless `SENTRY_DSN` is set). None of them shows one
request or one node as a tree of timed steps: which model attempt, retry or
tool round a slow node spent its time in has to be rebuilt from log lines.
CI and tests are hermetic: no network, no keys.

## Decision

**OpenTelemetry, with spans created by hand at three seams, exported only
when the standard exporter variable is set.**

- **Dependencies:** `opentelemetry-api` everywhere a span is made;
  `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http` in the api
  image. No auto-instrumentation packages: three seams do not justify their
  dependency trees, and hand-made spans keep content out by construction.
- **Off by default.** `platform/telemetry` configures a tracer provider only
  when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (and `OTEL_SDK_DISABLED` is not
  `true`). Otherwise the API's no-op tracer is used and no exporter, thread
  or socket exists. CI, tests and local runs never set it.
- **Seams:**
  - **LLM gateway** (ADR-004): one span per logical call
    (`call_llm`, `call_llm_json`, `call_llm_with_tools`), one per attempt of
    the attempt loop, and one per physical provider request at
    `complete_request`. Attributes
    follow the OpenTelemetry GenAI semantic conventions where a name exists
    (`gen_ai.operation.name`, `gen_ai.request.model`,
    `gen_ai.response.model`, `gen_ai.usage.input_tokens`,
    `gen_ai.usage.output_tokens`, `gen_ai.request.max_tokens`) and
    `co_scientist.*` names otherwise (reasoning tokens, cached prompt tokens,
    attempt number, retry reason, budget rung, route, prompt name, surface).
  - **Node runner**: one span per durable task execution, with node key, task
    type, task id, run id and outcome (committed, parked, retried, failed).
  - **HTTP**: one server span per request, named by the route template, with
    method and status. No query strings, headers or bodies.
- **No content.** Prompts, completions, tool arguments, goal text and
  attachment text never become span attributes or events. This matches the
  diagnostics rule (`diagnostic_events.py` records sizes and timings, never
  transcript text).
- **Existing telemetry stays.** Persisted logs, run metrics, `run_events` and
  Sentry are unchanged; spans add to them. Log records carry the current trace
  id when a span is active, so a log line leads to its trace.
- **Context across the worker cohorts:** each cohort runs its own event loop;
  spans use `contextvars`, which the existing `run_in_scoped_loop` copies, and
  no asyncio primitive is shared between loops.

## Owner actions

Create an OTLP/HTTP tracing backend on a free tier (for example Grafana Cloud
Traces or Honeycomb) and set on the Railway `api` service:

| Variable | Value |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | The backend's OTLP/HTTP endpoint |
| `OTEL_EXPORTER_OTLP_HEADERS` | Its authentication header, for example `Authorization=Basic ...` |
| `OTEL_SERVICE_NAME` | `co-scientist-api` |
| `OTEL_TRACES_SAMPLER` (optional) | `parentbased_traceidratio` with `OTEL_TRACES_SAMPLER_ARG=0.25` if volume matters |

Until then the code ships dormant.

## Consequences

- Three new runtime packages in the api lock, reviewed with
  `make audit-deps`.
- A slow node can be read as one trace: node → calls → attempts.
- Span names and attributes are an operator-facing contract; renames are
  avoided like logger-name renames.
