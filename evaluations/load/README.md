# Local launch load

Requires Docker Engine and Compose. All runtime services use an internal Docker
network, and the harness accepts only `http://api:8008`. No production URL,
credential, dotenv file or production database is used. `run.sh` recreates only
this compose project's disposable `load-db` volume. Static frontend assets are
excluded because the CDN serves them.

Build from the repository root:

```sh
docker build -f Dockerfile.api -t coscientist-launch-load:local .
docker build -f evaluations/load/Dockerfile.locust -t coscientist-locust:local .
evaluations/load/run.sh
```

The API is the root production image, one Uvicorn process, an embedded durable
worker with `WORKER_POOL_SIZE=1`, SQLite on a named volume, and a 2 CPU / 2 GiB
container limit. A mounted measurement adapter wraps the production app. It
replaces only process credential/offline detection and physical completions:
production free-run, storage and provider admission remain enabled. Responses
come from the existing deterministic schema backend with a 100 ms delay and
streamed text chunks. Provider keys are absent, and runtime outbound networking
is blocked. Provider/network throughput is therefore **not** measured.

By default, twenty-five Locust workers have distinct real connecting IP
addresses. This avoids mistaking a single load generator's NAT limit for global capacity. No
forwarded header supplies peer identity. Idle draft run fixtures are created
before measuring, after startup recovery, and contain no worker tasks. Production
closes idle draft streams after 30 seconds; pages reconnect while start traffic
enters the normal durable queue. The completed report/chat fixture is a private
copy of a packaged example. Only fixture storage-admission counters are cleared before measurement.
No serving transaction or poll performs that cleanup.

Default five-minute mixed workload:

- 500 landing visits/minute: ten paced users with a new browser identity per
  visit call `/status`, `/api/free-usage`, `/api/runs`, `/api/runs/demo` and
  `/api/interviews` and the layout's scoped `/api/logs` warning probe, matching
  the shared status/history/allowance/diagnostics clients.
- 200 open run pages: distinct owned run fixtures, event snapshot plus sustained
  SSE (including draft idle reconnection), history and run-detail refresh every
  ten seconds. SSE header latency is separate from connection lifetime. Refusals
  reconnect with bounded backoff and honor `Retry-After`.
- 50 distinct identities attempt Express creation/start at six-second intervals.
  Most are refused by the unchanged per-host free-run ceiling. Every 403/409/429
  must contain a nonempty human-readable `detail`; raw 500s count as failures.
- 20 report visits/minute, including all seven collections and Markdown download.
- 10 streamed Q&A turns/minute against a private completed report.

Change `VISITORS_PER_MINUTE`, `SSE_PAGES`, `START_ATTEMPTS`, `LOAD_DURATION`,
`LOAD_WORKERS`, `LOAD_MODEL_DELAY`, `LOAD_API_IMAGE` and `LOAD_RESULTS` for
repeatable experiments:

```sh
LOAD_RESULTS=./results/mixed evaluations/load/run.sh
LOAD_WORKERS=40 SSE_PAGES=300 VISITORS_PER_MINUTE=1000 START_ATTEMPTS=0 \
  LOAD_RESULTS=./results/over-cap evaluations/load/run.sh
```

Set `SSE_MAX_CONNECTIONS` only for a local capacity experiment. Do not raise
free-run/provider limits to make a test pass. The runner saves API/Locust logs,
CSV p50/p95/p99 request latency, failure tables, per-scenario admission counts,
one-second process RSS/high-water/FD/active-SSE samples, and a JSON summary.
Expected admission refusals are counted separately from unexpected errors.
Check actual visit/start counts: closed-loop pacing can miss its target under
saturation, and a nominal requested rate is not achieved throughput.

The measurement adapter times SQLite `BEGIN IMMEDIATE` acquisition (including
lock waiting and its syscall cost), counts busy/locked exceptions, and samples
API-loop scheduling lag every 100 ms. It keeps bounded 100,000-value windows;
measurement percentiles beyond that count describe the most recent window. FD and
memory measurements are for the API process; the load generators run outside
its CPU/memory limit. SQLite statement timings include instrumentation overhead.
The summary uses the last telemetry sample for measurement percentiles; a separate
final snapshot records cleanup. The stack must stop before full backend/browser
suites.

If a development workspace intercepts TLS, provide its trusted CA to a temporary
build layer; keep certificate verification enabled and do not commit that CA or
change the production Dockerfile. Locust is an optional measurement dependency,
installed only in the generator image, never in the API runtime closure.
