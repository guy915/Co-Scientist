<h1 align="center">AI Co-Scientist</h1>

<p align="center">
  <sub>Inspired by Google DeepMind</sub><br/><br/>
  A locally-runnable, multi-agent hypothesis-generation workbench.<br/>
  Not a chatbot. Not a summariser. <strong>A scientific workbench.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-59_passing-brightgreen" alt="Tests"/>
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python"/>
  <img src="https://img.shields.io/badge/TypeScript-React_19-blue" alt="TypeScript"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-purple" alt="License"/></a>
</p>

<table align="center">
<tr>
<td align="center"><strong>Pipeline Architecture</strong></td>
<td align="center"><strong>Workbench UI</strong></td>
</tr>
<tr>
<td><img src="docs/pipeline.svg" alt="Multi-agent hypothesis pipeline" width="440"/></td>
<td><img src="docs/screenshots/chat.png" alt="Co-Scientist workbench" width="440"/></td>
</tr>
</table>

---

## Features

<table>
<tr>
<td width="33%" valign="top">

**🏆 Elo Tournament**<br/>
<sub>Pairwise ranking with standard Elo formula. K-factor configurable.</sub>

</td>
<td width="33%" valign="top">

**🛡️ Dual Safety Gates**<br/>
<sub>Intake + final-output safety screening. Blocks weaponisation patterns.</sub>

</td>
<td width="33%" valign="top">

**📚 Citation Audit**<br/>
<sub>Four-state classification: verified, partial, unsupported, unavailable.</sub>

</td>
</tr>
<tr>
<td valign="top">

**🧪 Mock Mode**<br/>
<sub>Full pipeline without an LLM key. Deterministic, free, instant.</sub>

</td>
<td valign="top">

**🧬 Evolution Lineage**<br/>
<sub>Append-only: evolved hypotheses are new rows with <code>parent_id</code> tracing to gen-0.</sub>

</td>
<td valign="top">

**💬 Scientist-in-the-Loop**<br/>
<sub>Chat tab with auto-steering, manual steering, and QA modes.</sub>

</td>
</tr>
</table>

## Quickstart

```bash
make setup          # Python venv + frontend deps
make dev            # API on :8008, UI on :5173
open http://localhost:5173
```

> Run `make help` for all targets. See [`.env.example`](.env.example) for configuration.

## Workbench Tour

Click **New run**, type a research goal, pick Standard or Advanced, hit **Start**. The pipeline streams live across six tabs:

| Tab | Shows |
| --- | --- |
| **Overview** | Live pipeline timeline with progress bar and event counters |
| **Ideas** | Ranked hypotheses by Elo. Click any row for the detail modal: statement, mechanism, experimental design, lineage |
| **Evidence** | Retrieved sources with abstracts, links, and 4-state citation classification |
| **Tournament** | Leaderboard + per-iteration matchup log with Elo deltas and judge rationale |
| **Report** | Server-generated Markdown report with download buttons (MD / JSON) and safety verdict |
| **Chat** | Scientist-in-the-loop steering: auto, manual, and QA conversation modes |

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="System architecture" width="600"/>
</p>

Full diagrams and module map in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Mock Mode vs Real Engine

The system reports its mode at `/status`:

| | Mock Mode | Real Engine |
| - | - | - |
| **Trigger** | No LLM key in `.env` | Any provider key set (`GEMINI_API_KEY`, `OPENAI_API_KEY`, …) |
| **Behaviour** | Deterministic seed → 11 agent steps, stable hypotheses and Elo | LangGraph engine, real LLM calls |
| **Cost** | Free | Provider billing applies |

Force mock mode for development: `COSCIENTIST_FORCE_MOCK=1`. Check mode: `curl localhost:8008/status | jq .mock_mode`

## Environment

Copy `.env.example` to `.env`. Empty keys keep you in Mock Mode.

```
GEMINI_API_KEY=                      # empty = Mock Mode; any key triggers real engine
MODEL_NAME=deepseek/deepseek-chat    # LiteLLM format
COSCIENTIST_DB_PATH=./coscientist.db
SAFETY_MODE=standard                 # 'strict' for dual-use filtering
```

See [`.env.example`](.env.example) for the full variable list (CORS, Elo tuning, MCP, cache).

## Fidelity

This clone preserves the core invariants of the published system: 11 agent-equivalent pipeline steps, Elo-1200 starting scores, append-only evolution lineage, 4-state citation classification, and dual safety gates.

Full invariant list with paper sources in [`docs/FIDELITY.md`](docs/FIDELITY.md).

## Non-goals

The clone is deliberately not:

- A chat wrapper over papers.
- An autonomous wet-lab executor.
- A medical / clinical / regulatory decision system.
- A multi-tenant SaaS — this is a local-first research tool.

## Acknowledgements

Based on [AI Co-Scientist](https://research.google/blog/accelerating-scientific-discovery-with-ai-co-scientist/) by Google DeepMind. See [`references/`](references/) for the original research papers and product analysis.

## License

[MIT](LICENSE)
