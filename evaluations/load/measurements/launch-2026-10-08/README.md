# Launch load receipt — 2026-10-08

All traffic and data were synthetic and local. Root production API image,
one process/embedded worker, SQLite WAL on a disposable volume, 2 CPU / 2 GiB;
model completions are deterministic with 100 ms I/O. Runtime Docker networking
is internal-only, with no credentials/dotenv/inherited outbound configuration.
Static assets are excluded. These establish short-run API/store capacity;
real provider/MCP throughput, production ingress and long-duration memory
behavior are unmeasured. Capacity and spike steps are in
[OPERATIONS.md](../../../../docs/OPERATIONS.md#load-and-capacity).

| Receipt | Workload / purpose | Result |
|---|---|---|
| [before.json](before.json) | 300 s, 500 offered visitors/min, 200 pages, 50 starts, reports/chat; forty generators, no OPTIONS | 482.2 achieved visitors/min, only 8 live SSE, 8/30,373 unexpected errors; runner/master exit 1 |
| [after-overlay.json](after-overlay.json) | Same API base with the three SSE modules overlaid, 15 s HTTP keepalive; one generator/40 real source aliases plus OPTIONS | 478.2 visitors/min, 200 SSE, 0/44,803 unexpected errors; all exits 0 |
| [keepalive-5.json](keepalive-5.json) / [keepalive-15.json](keepalive-15.json) | Otherwise identical 60 s/200-page profiles, ten starts, no OPTIONS; only HTTP keepalive differs | 17 history socket resets/5,483 requests at 5 s; 0/5,522 at 15 s; runner/master 1 → 0 |
| [integrated-no-retry.json](integrated-no-retry.json) | 300 s integrated production image, schema unions corrected, OPTIONS, ordinary Requests adapter | 200 SSE, 12 history idle-socket resets/44,501 requests (0.027%); retained nonzero receipt |
| [after.json](after.json) | Same integrated image, browser-like safe-read retry adapter; full 300 s mixed workload | 468.4 achieved visitors/min, 200 SSE, 0/44,028 unexpected errors; zero recovered retries observed; all exits 0 |
| [over-cap.json](over-cap.json) | 120 s, 1,000 offered visitors/min, 300 pages, no starts, reports/chat/OPTIONS; SSE overlay image | 749.5 achieved visitors/min, 256 SSE, 176 clear stream refusals, 0/28,191 unexpected errors; all exits 0 |
| [admission-cap.json](admission-cap.json) | 60 s mixed profile, ten starts, MAX_CONCURRENT_RUNS=1 | Two admitted/completed, four clear concurrency refusals and four daily-host refusals; zero unexpected errors |

The first broken limit was GET SSE inheriting an unset write-only peer context:
all visitors shared one eight-stream bucket. The fix corrects request-peer admission,
sets bounded configurable global capacity, backs quiet polling off to two seconds,
retains wall-clock deadlines, shows capacity refusal/backoff in the run view,
and uses 15-second production HTTP keepalive. Existing owner=4/host=8 guards
remain. A common proxy/NAT peer still permits eight streams; 200 requires the
forty distinct connecting peers used here. No client forwarded header supplied
identity. Do not infer production ingress behavior from the local test.

Keepalive mitigates idle-socket races; it cannot prohibit them. A forced-close
probe recorded Requests: warm GET, reused GET closes, ConnectionError. Chromium
recorded warm GET, reused GET closes, fresh GET, status 200. The load adapter now
matches that bounded safe-read recovery. The automated socket test proves GET
recovery and that a POST whose body was received is never replayed. Connect
failures, HTTP status codes and streaming bodies receive no adapter retry.
Recovered retries are published separately and their cost stays in latency.
The final five-minute repeat observed zero retries, so it alone is not a causal
proof of recovery; the forced-close regression is that proof.

Fifty distinct browser IDs from one connecting host admitted six and clearly
refused 44. In the integrated repeats, three admitted runs completed and three
stored a clear daily-provider-admission failure. Free admission does not
reserve enough provider allowance to promise completion. Budgets stayed at
20 free starts/day globally, 6/host/day, 3/browser/day and 512 physical calls/day
per host; actual model completions/hour are not established by fake I/O. Use
0.83 starts/hour only as the global ceiling averaged over a full day.

Source and measurement identity (commit IDs refer to the development history
before this repository was published and are not present here):

- Historical API base: `e6cf5b9211ce4d101c29596e07dcfdc8f2f3b04d`, image
  `sha256:e62e4e8c91603ab56f6e88e32514ae34a50359fc13750be854331cdd979f0b28`.
- SSE overlay: `api/runs/{__init__,stream_admission,events}.py` from
  `fc390d856190916b2e67b6ae03135a3e0c65f9fe`, image
  `sha256:1c0a9b5069c986cd67883675e577c0c18a7f08bffb7cf430e6aaa85d2cfcea8c`.
  Keepalive 15 s is supplied on the CLI, matching the fixed entrypoint; that
  historical overlay image itself retains the old entrypoint.
- Integrated root image: `31b58b4dabb723f3b2df60612711c41fcd582282`, image
  `sha256:a5b8899b2a5d13ae36c84323660deef1050af4bb58a87cc5840411b45c86ccf2`.
  Normal production Dockerfile/locks/source were used, with only the public
  execution-workspace CA supplied in scratch for intercepted build TLS.
- Generator image IDs and exact profile parameters are retained in each JSON.
  Locust is 2.43.1. Historical model doubles did not resolve schema unions;
  final ones do. Do not attribute differences across source/generator/schema
  versions solely to one serving change.
- `harness_checkout_revision` identifies the checkout, independently from image
  source. Integrated receipts include harness SHA-256 fingerprints captured at
  start. Subsequent edits add a type annotation/format correction and count SSE
  body exceptions while keeping the watcher alive for bounded reconnection. No
  body exception occurred in the accepted captures; a truncated-stream probe
  reproduced the silent watcher exit before this guard and passed afterward.
  Raw logs, DBs, CSVs and reports remain ignored rather than published.

JSONs include route p50/p95/p99, error rate, process exit statuses, peak RSS/FDs,
SSE counts, SQLite writer-acquisition/statement timings and loop lag. Historical
individual OPTIONS-route percentiles are omitted from their JSON projections;
request totals still include OPTIONS when enabled. Timing windows retain the
most recent 100,000 values; last-sample percentiles include the short idle tail.
Writer acquisition includes syscall cost, FD peaks are one-second samples and
VmHWM covers process lifetime. No SQLite busy/locked exception occurred in the
published trials. After the integrated load, SSE fell to zero and FDs to 15.

The recommended local envelope is 450 landing visitors/minute plus 200 run
pages with the tested peer distribution, while report/chat and bounded start
traffic continue. It leaves headroom below achieved rate. The 256-stream probe
shows controlled shedding, not safe sustained 1,000-visitors/min capacity.
