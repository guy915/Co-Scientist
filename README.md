<h1 align="center">Co-Scientist</h1>

<p align="center">
  A multi-agent hypothesis-generation system for scientific discovery.
</p>

<p align="center">
  <a href="https://deepwiki.com/guy915/Co-Scientist"><img src="docs/assets/deepwiki-badge.svg" alt="DeepWiki"/></a>
</p>

<table align="center">
<tr>
<td align="center"><strong>Pipeline architecture</strong></td>
<td align="center"><strong>Workbench</strong></td>
</tr>
<tr>
<td><img src="docs/assets/pipeline.svg" alt="Multi-agent hypothesis pipeline" width="440"/></td>
<td><img src="docs/assets/chat.png" alt="Co-Scientist workbench" width="440"/></td>
</tr>
</table>

## Overview

Co-Scientist generates, reviews, ranks, and evolves research hypotheses with a
LangGraph multi-agent pipeline and streams progress into a web workbench.
Researchers can attach documents, refine their goals, steer a run, inspect
its evidence and hypothesis lineage, and share a final report.

This is an independent implementation inspired by Google's published
AI Co-Scientist research. It is not affiliated with or endorsed by Google.
The [parity ledger](docs/PARITY.md) records implemented requirements,
deliberate differences, and evaluation gaps; the [fidelity audit](docs/fidelity-audit/README.md)
provides the supporting analysis. Passing implementation tests does not
establish scientific validity, expert agreement, or wet-lab results.
Generated hypotheses need researcher review and experimental validation.

## Features

- Supervised hypothesis generation, review, Elo ranking, and evolution.
- Durable, resumable task execution with persisted progress and lineage.
- Literature retrieval, document attachments, and claim-level evidence assessment.
- Intake, hypothesis, and final-output safety screening; see the
  [limitations](docs/FIDELITY.md).
- Researcher steering and grounded Q&A during a run.
- Authenticated hosted access, BYOK credentials, and revocable report sharing.
- Deterministic offline mode for development without a model API key.

## Quick start

Install Python **3.12**, Node.js **22.13+**, and Bun **1.3.14**. The standalone
engine also supports Python 3.10+. From a checkout of this repository:

```bash
make setup          # Python venv + locked frontend dependencies
make start          # API :8008, UI :5173, MCP :8888
```

Open [localhost:5173](http://localhost:5173). Leave provider keys empty to use
all hypothesis-generation stages with deterministic offline responses.
MCP retrieval is a separate service and may contact public scientific sources.

To use a real model, edit the root `.env`. The default system route needs
`OPENROUTER_API_KEY`; another provider requires its own model configuration
and matching key. See [`.env.example`](.env.example) and
[the complete API configuration reference](app/.env.example).

```dotenv
OPENROUTER_API_KEY=
MODEL_NAME=openrouter/stealth/space-bunny-alpha
SAFETY_MODE=standard
```

`make setup` creates `app/.env` as a link to the root `.env`. The MCP server
has its own configuration under `engine/mcp_server/.env`. See
[local setup](docs/RUNNING-LOCALLY.md) for prerequisites and troubleshooting.
Run `make help` for all targets.

Before exposing the API, follow [deployment](docs/DEPLOYMENT.md) and
[security](SECURITY.md), including `AUTH_MODE=required`. Compatibility mode
uses caller-selected IDs and is intended for local development.

## Using the workbench

Describe a research goal in chat, review its configuration, and select
**Start**. The chat timeline shows progress and accepts steering messages.
Completed runs have four report views:

| View | Contents |
| --- | --- |
| Details | Configuration, provider, artifact counts, and safety decisions |
| Learning | Retrieved sources and citation classifications |
| Overview | Synthesized report with Markdown and JSON downloads |
| Ideas | Ranked hypotheses, mechanisms, experimental designs, and lineage |

The terminal client is available after setup:

```bash
.venv/bin/cosci runs create "Investigate a research mechanism" --tier express --start
.venv/bin/cosci runs wait <run-id>
.venv/bin/cosci runs report <run-id> --md
```

With no usable provider credential, or `COSCIENTIST_FORCE_OFFLINE=1`, runs use
the offline backend. Check `/status` for `llm_backend` (`offline` or `real`).
Offline runs exercise the pipeline and do not establish hypothesis quality.

## Development checks

```bash
make check          # lint, types, all suites, eval smoke, build, browser tests
make docker-build   # build both production images; never deploys
make audit-deps     # online advisory review; requires uv
```

Individual checks: `make lint`, `make typecheck`, `make test-app`,
`make test-engine`, `make test-mcp`, `make test-frontend`, `make parity`,
`make eval-smoke`, `make build`, `make e2e`, and `make e2e-production`.
The browser suite uses an
isolated database and offline model responses. Provider-backed evaluations
remain explicit opt-in operations.

## Repository map

| Path | Purpose |
| --- | --- |
| `app/` | FastAPI API, SQLite store, operator CLI, and React workbench |
| `engine/` | LangGraph hypothesis-generation engine and reference MCP server |
| `evaluations/` | Offline evaluation tools, parity checker, and release gate |
| `e2e/` | Playwright browser tests |
| `requirements/` | Hash-pinned Python runtime dependencies for production images |
| `docs/` | [Documentation index](docs/README.md), architecture, operations, and launch guidance |
| `.github/` | CI, nightly checks, dependency updates, and review template |
| `vendor/` | Unmodified third-party science skills; provenance in [NOTICE](NOTICE) |
| `references/` | External-source assessments and retained evaluation evidence |
| `PLAN.md` | Completed external-reference campaign record, retained for evidence links |

Start with [architecture](docs/ARCHITECTURE.md),
[the product walkthrough](docs/EXPLAINER.md), and
[launch readiness](docs/LAUNCH.md). For contributions, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

First-party software is licensed under [Apache 2.0](LICENSE).
[NOTICE](NOTICE) records included third-party software and data provenance.
Vendored documentation, referenced papers, and scientific data retain their
own terms; the software license does not grant rights to those materials.

## Acknowledgements

- [Towards an AI Co-Scientist](https://arxiv.org/abs/2502.18864)
- [Accelerating scientific discovery with Co-Scientist](https://doi.org/10.1038/s41586-026-10644-y)
- [Gemini Enterprise — Idea Generation agent](https://docs.cloud.google.com/gemini/enterprise/docs/idea-generation)
- [Science Skills for Antigravity](https://github.com/google-deepmind/science-skills)
- [Jataware Open Co-Scientist](https://github.com/jataware/open-coscientist)
- [Sakana AI Scientist](https://github.com/SakanaAI/AI-Scientist)
- [Pi Agent](https://github.com/Dicklesworthstone/pi_agent_rust)
