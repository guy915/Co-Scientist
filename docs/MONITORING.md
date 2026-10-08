# Monitoring

Railway's healthcheck runs only while a deploy goes live; after that only
the monitors below poll the service. This guide lists what exists and where
the code hooks in.

## Uptime

Use a free external monitor (UptimeRobot, Better Stack or similar) with a
five-minute interval and email alerts.

| Monitor | URL | Alert when |
|---|---|---|
| API up | `https://api.ai-co-scientist.com/health` | status is not 200 |
| API healthy | same URL, keyword check | `"status":"healthy"` is absent |
| Site up | `https://ai-co-scientist.com/` | status is not 200 |

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
| Vercel, production | `VITE_SENTRY_DSN` | the frontend project's DSN |
| Vercel, build (optional) | `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` | source-map upload for readable stack traces |

Both SDKs stay off while their DSN is unset, so local runs, CI and forks
send nothing. Researcher data must not leave through error reports.

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

## Status

Live since 7 October 2026:
- Uptime (UptimeRobot, free plan, five-minute checks, email alerts): a
  keyword monitor on `/health` for `"status":"healthy"`, which also alerts
  when the API is down or not 200, and an HTTP monitor on the site. Together
  they cover the three rows above.
- Error tracking, API: Sentry project `co-scientist-api`; `SENTRY_DSN` and
  `SENTRY_ENVIRONMENT=production` are set on the Railway api service.
- Error tracking, frontend: Sentry project `co-scientist-ui`
  (`src/shared/lib/error_tracking.ts`, loaded as its own chunk only when built with
  a DSN); `VITE_SENTRY_DSN` is set for Vercel production builds. Reports
  carry no PII or console breadcrumbs, and the browser's client ID and saved
  provider keys are redacted. The DSN is read at build time, so the launch's
  frontend host needs it set again.
