# `cosci` operator CLI — final report

An agent-facing terminal front end that drives Co-Scientist runs end to end
through the app's HTTP API, with no web UI and no API keys required (it works
offline against the deterministic mock provider).

## What was built

A new `cosci` console command implemented inside the app package:

- `app/app/cli/` — the CLI package (stdlib `argparse` + the existing `httpx`
  dependency, no new heavy deps, no `rich`):
  - `http.py` — `ApiClient` (thin `httpx` wrapper) and `CliError`; centralizes
    base-URL/client-id resolution and turns every transport/HTTP error into a
    clear one-line message with a non-zero exit code.
  - `render.py` — line-oriented and `--json` output formatters, plus SSE frame
    parsing.
  - `status_cmd.py`, `runs_cmd.py` — one handler per command, each a thin
    wrapper over one endpoint.
  - `main.py` — the `argparse` command tree and dispatch; kept import-light so
    `cosci --help` does not import FastAPI or the engine.
- `app/pyproject.toml` — `[project.scripts] cosci = "app.cli.main:main"`, and
  `httpx` moved from the dev extra into `[project.dependencies]` (the entry
  point imports it at runtime; FastAPI does not pull it in).
- Tests in `app/tests/`: `test_cli_render.py`, `test_cli_http.py`,
  `test_cli_commands.py`.
- `app/README.md` — a "`cosci` operator CLI (for coding agents)" section.

No API endpoint, diagnostics internal, frontend, CI workflow, or unrelated code
was modified.

## Command inventory

Global options accepted on every subcommand: `--api-url` /
`COSCIENTIST_API_URL` (default `http://localhost:8008`), and `--client-id` /
`COSCIENTIST_CLIENT_ID` (the `X-Client-ID` header). Every read command takes
`--json`. All commands exit non-zero with a stderr message on HTTP/connection
errors.

| Command | Endpoint | Default output |
|---|---|---|
| `cosci status [--json]` | `GET /health` + `GET /status` | aligned `key : value` |
| `cosci runs list [--limit N] [--json]` | `GET /api/runs` | one run per line: `id  status  provider  goal` |
| `cosci runs show RUN_ID [--json]` | `GET /api/runs/{id}` | `key : value` incl. summary counts |
| `cosci runs create "GOAL" [config] [--json]` | `POST /api/runs` | `id  status` |
| `cosci runs start RUN_ID [--provider mock\|engine] [--json]` | `POST /api/runs/{id}/start` | `id  status` |
| `cosci runs pause RUN_ID [--json]` | `POST /api/runs/{id}/pause` | `id  status` |
| `cosci runs resume RUN_ID [--json]` | `POST /api/runs/{id}/resume` | `id  status` |
| `cosci runs cancel RUN_ID [--json]` | `POST /api/runs/{id}/cancel` | `id  status` |
| `cosci runs watch RUN_ID [--after SEQ] [--json]` | `GET /api/runs/{id}/events` (SSE) | one event per line: `seq  type  payload`; exits on terminal |
| `cosci runs hypotheses RUN_ID [--json]` | `GET /api/runs/{id}/hypotheses` | `id  elo  title` |
| `cosci runs evidence RUN_ID [--json]` | `GET /api/runs/{id}/evidence` | `id  source  title` |
| `cosci runs reviews RUN_ID [--json]` | `GET /api/runs/{id}/reviews` | `id  reviewer  summary` |
| `cosci runs citations RUN_ID [--json]` | `GET /api/runs/{id}/citations` | `id  state  claim` |
| `cosci runs safety RUN_ID [--json]` | `GET /api/runs/{id}/safety` | `id  stage  decision  reason` |
| `cosci runs report RUN_ID [--md] [--json]` | `GET /api/runs/{id}/report[.md]` | summary + Elo leaderboard |
| `cosci runs steer RUN_ID "MSG" [--json]` | `POST /api/runs/{id}/messages` | `key : value` |
| `cosci runs ask RUN_ID "QUESTION" [--json]` | `POST /api/runs/{id}/messages/ask` (SSE) | streamed answer to stdout |

`create` config knobs map straight to the `POST /api/runs` body:
`--tier {express,standard,extended,ultra}`,
`--focus {prefer_evidence,balance,prefer_novelty,breakthrough}`,
`--requirement/--attribute/--criterion TEXT` (repeatable),
`--initial-hypotheses/--max-iterations/--evolution-max/--k-factor N`,
`--literature/--no-literature`.

## Decision note: CLI, not an MCP server

The goal was to make Co-Scientist operable by an agent from a terminal. I built
a CLI rather than an MCP server, and deliberately did not build both:

- **Agents operating this repo already have shell access.** A CLI is the native
  interface for that context; it composes with pipes, `$(...)`, `cut`, `jq`, and
  `set -e` with no extra runtime or protocol handshake.
- **The API is local and unauthenticated.** The value to add is ergonomics over
  the existing HTTP endpoints, not a new transport or auth layer. An MCP server
  would be a second process to run and keep in sync for no capability gain.
- **A CLI is directly and cheaply testable.** `main(argv)` is a plain function
  returning an exit code, so every command is exercised by `pytest` against a
  real server (see below). An MCP server would need a client harness to test
  equivalently.
- **The correct seam is the HTTP API, not SQLite.** `/start` reserves an
  in-process slot and launches the workflow as a background task, and the event
  log makes runs restart-durable; driving runs by writing SQLite directly would
  bypass all of that. `engine/mcp_server/` is a literature-tool provider *to*
  the engine, not an operator surface, so it was not the seam either. The CLI is
  a thin client of `app/app/runs.py` (`/api/runs`) plus the `main.py`
  diagnostics — it changes no endpoint or behavior.

## Captured transcript (offline, no API keys)

Captured against a fresh mock-mode server started from an isolated working
directory (so neither `load_dotenv` nor pydantic-settings find the repo `.env`);
the server reports `has_provider_key: False`. `create -> start -> watch (to
completion) -> report -> ask`, verbatim (the `…` marks are the CLI's own line-length trimming, not elisions):

```text
$ env | grep -cE '^(GEMINI|OPENAI|ANTHROPIC|DEEPSEEK|GROQ|MISTRAL)_API_KEY='
0

$ cosci status
status            : healthy
version           : 0.1.0
model             : deepseek/deepseek-chat
provider          : mock
mock_mode         : True
has_provider_key  : False
engine_importable : True
mcp_available     : False
pubmed_available  : False
literature_review : False

$ cosci runs create "Explore mitochondrial dynamics in neurons" --tier express
16780d21-1b41-4703-acf6-1759b3baec73	draft

$ cosci runs start 16780d21-1b41-4703-acf6-1759b3baec73
16780d21-1b41-4703-acf6-1759b3baec73	queued

$ cosci runs watch 16780d21-1b41-4703-acf6-1759b3baec73
1	lifecycle	{"event": "created", "run_mode": "default", "provider": "mock", "focus": "balance", "tier": "express"}
2	lifecycle	{"event": "queued"}
3	safety.intake	{"stage": "intake", "decision": "allow", "reason": "", "matches": []}
4	status	{"status": "running"}
5	supervisor.plan	{"agents": ["supervisor", "intake", "literature_review", "generation", "reflection", "proximity", "ranking", "evolution", "meta_review", "citation_audit", "safety", "report"], "run_mode": "default", …
6	literature_review	{"count": 4, "evidence": [{"title": "Mock study 1: explore dynamics in a model system", "url": "https://example.org/mock/1"}, {"title": "Mock study 2: mitochondrial dynamics in a model system", "url"…
7	generate	{"count": 4, "hypotheses": [{"id": "a1e70147-f806-42ef-8c67-06fc6743eb5f", "title": "H1: Stabilizing a transient intermediate in the canonical signalling module"}, {"id": "b79b43f6-87ce-4beb-99ec-7d1…
8	reflection	{"reviewed": 4}
9	safety.hypothesis	{"screened": 4, "blocked": 0, "eligible": 4}
10	citation.grounding	{"grounded": 4, "blocked": 0, "eligible": 4}
11	proximity	{"clusters": {"cluster-0": 2, "cluster-1": 1, "cluster-2": 1}}
12	ranking	{"iteration": 1, "matches": [{"winner": "a1e70147-f806-42ef-8c67-06fc6743eb5f"}, {"winner": "2a87e949-bb5c-4758-8ae8-db94d81e00f8"}, {"winner": "b79b43f6-87ce-4beb-99ec-7d13ba07e697"}, {"winner": "22…
13	evolve	{"children": [{"id": "6c8d2a57-b062-49c2-8585-58442bb6f88d", "title": "H5: Exploiting allosteric switching in the bottleneck enzyme (evolved from H2: Enforcing temporal restric...)"}, {"id": "f5df419…
14	meta_review	{"iteration": 1, "critique": "Meta-review (iter 1): the leading hypotheses cluster around the same mechanistic frame; recommend diversifying the experimental context in the next round and tightening …
15	ranking	{"iteration": 2, "matches": [{"winner": "a1e70147-f806-42ef-8c67-06fc6743eb5f"}, {"winner": "2a87e949-bb5c-4758-8ae8-db94d81e00f8"}, {"winner": "b79b43f6-87ce-4beb-99ec-7d13ba07e697"}, {"winner": "22…
16	deep_verification	{"verified": 3, "probes": [{"hypothesis_id": "b79b43f6-87ce-4beb-99ec-7d13ba07e697", "verdict": "holds", "probes": [{"question": "Regarding 'H2: Enforcing temporal restriction on the upstream regulat…
17	citation_audit	{"verified": 0, "partial": 0, "unsupported": 8, "unavailable": 0}
18	research_overview	{"research_overview": {"overview": {"summary": "Synthesizing the top hypotheses for 'Explore mitochondrial dynamics in neurons', a coherent research program emerges around h2: enforcing temporal rest…
19	safety.final	{"stage": "final", "decision": "allow", "reason": "", "matches": []}
20	report	{"research_goal": "Explore mitochondrial dynamics in neurons", "run_mode": "default", "provider": "mock", "hypothesis_count": 8, "evidence_count": 4, "match_count": 12, "citation_summary": {"verified…
21	status	{"status": "completed"}
21	_terminal	completed

$ cosci runs report 16780d21-1b41-4703-acf6-1759b3baec73
research_goal : Explore mitochondrial dynamics in neurons
provider      : mock
hypotheses    : 8
evidence      : 4
matches       : 12

leaderboard:
  1	1222	H2: Enforcing temporal restriction on the upstream regulator
  2	1220	H3: Enforcing temporal restriction on the canonical signalling module
  3	1200	H5: Exploiting allosteric switching in the bottleneck enzyme (evolved from H2: Enforcing temporal r…
  4	1200	H7: Leveraging cross-pathway interference in the bottleneck enzyme (evolved from H3: Enforcing temp…
  5	1200	H9: Decoupling co-expression in the dominant pathway (evolved from H4: Exploiting allosteric swit..…
  6	1200	H11: Leveraging cross-pathway interference in the proposed mechanism (evolved from H1: Stabilizing …
  7	1180	H4: Exploiting allosteric switching in the bottleneck enzyme
  8	1178	H1: Stabilizing a transient intermediate in the canonical signalling module

$ cosci runs report 16780d21-1b41-4703-acf6-1759b3baec73 --md | head -12
# Research Report — Explore mitochondrial dynamics in neurons

_Provider: **mock**_

## Summary
This run was executed in deterministic mock mode. Hypotheses, citations, and tournament results below are illustrative artefacts produced without any LLM provider.

## Top hypotheses

### 1. H2: Enforcing temporal restriction on the upstream regulator  _Elo: 1222_
In the context of 'Explore mitochondrial dynamics in neurons', we hypothesise that enforcing temporal restriction on the upstream regulator will produce a measurable effect via a mechanism distinct from current consensus.


$ cosci runs ask 16780d21-1b41-4703-acf6-1759b3baec73 "Which hypothesis ranked highest?"; echo "exit: $?"
Q&A requires a language model API key (set CHAT_MODEL_NAME or MODEL_NAME).
exit: 1
```

`ask` streams the API's own frames. Offline (no model key) the endpoint returns
HTTP 200 and emits a graceful `error` frame; the CLI prints that fallback to
stderr and exits 1. This is expected and honest, not a failure of the command —
the CLI correctly relays whatever the endpoint streams. With a model key
configured, the same command streams the answer to stdout and exits 0.

## Verification

All from the worktree root, on the mock provider, fully offline.

```text
$ make test-all
961 passed in 4.20s                      # engine
281 passed, 1 warning in 36.19s          # app (incl. 50 new CLI tests)
parity: 62 requirement rows (external=6, undisclosed=2, verified=54)
parity: OK — every 'verified' row cites test/eval evidence that exists on disk

$ cd app && ../.venv/bin/python -m mypy app/
Success: no issues found in 50 source files

$ cd app && ../.venv/bin/python -m ruff check app tests
All checks passed!
```

Entry point exposed by the editable install:

```text
$ .venv/bin/pip show -f co-scientist-viewer | grep cosci
  ../../../bin/cosci
$ .venv/bin/cosci --help        # resolves; prints usage without importing FastAPI/engine
```

### Test coverage (50 new tests)

- `test_cli_render.py` (12) — pure formatter/SSE-parser unit tests.
- `test_cli_http.py` (12) — `ApiClient` over `httpx.MockTransport`: JSON/text
  success, header injection, HTTP-status and connection-error → `CliError`,
  streaming line yield, and error-status-before-yield.
- `test_cli_commands.py` (26) — every command driven through `main(argv)` (the
  console-script entry point) against a spawned uvicorn on a temp
  `COSCIENTIST_DB_PATH` with `COSCIENTIST_FORCE_MOCK=1` and provider keys
  stripped: status, create/list/show, start+watch to terminal, `--after`
  replay, `--json` streaming, all five read collections (text and JSON), report
  summary/`--md`/`--json`, steer, the offline `ask` fallback, the pause→resume
  and cancel happy paths, and error paths (404 on a missing run, cancel/resume
  on a terminal run, no-command help → exit 2). The lifecycle happy paths use a
  multi-iteration `ultra` run (measured ~1.66s wall-clock) while the pause/cancel
  call lands within tens of milliseconds of `start` — a ~30–100× margin, so
  those tests are not timing-fragile.

**Testing-approach note (a small, deliberate deviation).** The goal suggested
ASGI transport for non-streaming commands and a spawned server only for the SSE
paths. Because `ApiClient` is HTTP-only and httpx's `ASGITransport` is
async-only (a sync `httpx.Client` cannot use it), I run *all* integration tests
against one session-scoped spawned uvicorn. This is higher fidelity — it
exercises the real ASGI server and the real `/start` background task, which an
in-process transport bypasses — and keeps the suite offline and deterministic.
The HTTP layer still gets fast, server-free unit coverage via `MockTransport`.
A one-line `transport=` seam was added to `ApiClient` purely to enable those
unit tests; production leaves it unset.

## Unresolved blockers

None. The full command set works offline on the mock provider, `make test-all`
is green, mypy and ruff are clean, and `cosci` is exposed by the editable
install.

The only capabilities that remain unexercised are the ones that require live
external services, by design and consistent with the offline constraint:

- `ask` producing a real answer needs an LLM provider key; offline it correctly
  degrades to the documented fallback (shown above).
- `start --provider engine` and any literature-review evidence need a provider
  key and/or a running MCP server; the mock provider covers the full workflow
  shape without them.
