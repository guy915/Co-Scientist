# Monitoring

Railway's healthcheck runs only while a deploy goes live; after that only
the monitors below poll the service. This guide lists what exists and where
the code hooks in.

## Uptime

Use a free external monitor (UptimeRobot, Better Stack or similar) with a
five-minute interval and email alerts.

| Monitor | URL | Alert when |
|---|---|---|
| API up | `https://api.open-coscientist.com/health` | status is not 200 |
| API healthy | same URL, keyword check | `"status":"healthy"` is absent |
| Site up | `https://open-coscientist.com` | status is not 200 |

`/health` returns 503 only when the store is unreachable. A stuck run, a
terminally failed task or low disk report `"status":"degraded"` with 200, so
the keyword monitor is what catches them. The public response hides check
detail, so it is safe to poll. Do not monitor the MCP service: it is private
to Railway's network.

## Error tracking

Use Sentry's free tier (or self-hosted GlitchTip, which speaks the same
protocol) with one project for the API and one for the frontend.

| Where | Variable | Value |
|---|---|---|
| Railway, api | `SENTRY_DSN` | the API project's DSN |
| Railway, api | `SENTRY_ENVIRONMENT` | `production` |
| Frontend host, build environment | `VITE_SENTRY_DSN` | the frontend project's DSN |

Both SDKs stay off while their DSN is unset, so local runs, CI and forks
send nothing. Researcher data must not leave through error reports.

The frontend reads `VITE_SENTRY_DSN` at build time
(`src/shared/lib/error_tracking.ts`, loaded as its own chunk only when built
with a DSN), so whichever host builds the frontend needs it set there; a
host change that omits it silently disables browser reporting. Frontend
reports carry no PII or console breadcrumbs, and the browser's client ID and
saved provider keys are redacted. Source-map upload is not implemented.

The API (`platform/telemetry/error_tracking.py`) reports unhandled exceptions and
`ERROR` log records. Each report:
- drops request headers (including `X-Client-ID`), cookies, bodies and query
  strings;
- has no stack-frame variables, personal data or performance traces;
- replaces the run's own provider key and every environment value whose name
  ends in `KEY`, `SECRET`, `TOKEN`, `PASSWORD` or `DSN` with `[REDACTED]`.

Only the Starlette and FastAPI integrations are on; Sentry's auto-enabled AI
and HTTP-client integrations would attach prompts and model output.

## Tracing

OpenTelemetry spans ([ADR-005](adr/005-tracing.md)) are exported only when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set and `OTEL_SDK_DISABLED` is not `true`;
otherwise no exporter, thread or socket exists. Use any OTLP/HTTP backend
with a free tier (Grafana Cloud Traces, Honeycomb or similar).

| Where | Variable | Value |
|---|---|---|
| Railway, api | `OTEL_EXPORTER_OTLP_ENDPOINT` | the backend's OTLP/HTTP endpoint |
| Railway, api | `OTEL_EXPORTER_OTLP_HEADERS` | its auth header, e.g. `Authorization=Basic ...` |
| Railway, api | `OTEL_SERVICE_NAME` | `co-scientist-api` |
| Railway, api (optional) | `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG` | `parentbased_traceidratio`, `0.25` |

A trace reads request or durable task → logical LLM call → attempt →
provider request:

| Span | Attributes |
|---|---|
| `GET /api/runs/{run_id}` (route template) | method, route, status |
| `task.execute` | run, task id and type, node, attempt, outcome (`committed`, `retried`, `parked`, `superseded`, `failed`, `lease_lost`) |
| `llm.call_llm`, `llm.call_llm_json`, `llm.call_llm_with_tools` | requested model, surface, prompt name |
| `llm.attempt` | attempt number, budget rung, retry reason |
| `chat <model>` | GenAI request and response model, max tokens, input/output tokens; reasoning and cached prompt tokens; route |

Spans carry no prompt, completion, tool argument, goal, query string, header
or body, and a failure records its exception type only. Stdout log lines carry
`trace_id` while a span is active; persisted logs are unchanged. Span names
and attributes are an operator contract, renamed only deliberately.
