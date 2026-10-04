# co-scientist-engine

Internal multi-agent engine for automated research hypothesis generation, adapted from Google's AI Co-Scientist.

Given a research goal, the system runs a pipeline of specialized agents — literature review, hypothesis generation, peer review, Elo tournament ranking, meta-review, and iterative evolution — to produce a ranked list of novel, grounded hypotheses.

Demo: [AI Co-Scientist — early detection of Alzheimer's disease](https://youtu.be/LyOvigZ59yE?si=JiIJnXajgLhTb1yj)

## Features

- **Multi-agent workflow**: Supervisor, Generator, Reviewer, Ranker, Tournament Judge, Meta-Reviewer, Evolution, Proximity Deduplication
- **Rich hypothesis output**: Each hypothesis includes `text`, `explanation` (layman summary), `literature_grounding` with structured `[C*]` citations, and `experiment` (suggested validation design)
- **Literature review integration**: Optional MCP server provides access to real published research; structured citations resolve to full source metadata
- **Domain-agnostic customization**: YAML-based configuration to bring your own MCP servers, literature sources, and domain-specific prompt guidance — no code changes needed
- **Intelligent caching**: Faster development iteration with LLM response caching
- **Elo-based tournament**: Pairwise hypothesis comparison with Elo ratings
- **Iterative refinement**: Evolves top hypotheses while preserving diversity
- **Post-generation enrichments**: Attach domain-specific data (e.g., related CVEs, knowledge graph statements) to each hypothesis via configurable tool calls

The app owns run scheduling, persistence and recovery. Internal setup lives in
`generator/core.py`; durable nodes execute through `task_runtime.py`.

## Workflow

Every work phase converges on the same review-through-ranking spine, then returns to the orchestrator loop point, which picks the next task from live state rather than following a fixed iteration count:

```
Supervisor
    └─► Literature Review  (optional, requires MCP server)
            └─► Generate
                    └─► Reflection  (only if Literature Review ran)
                            └─► Review
                                    └─► Comprehensive Reflection
                                            └─► Safety Screen
                                                    └─► Ranking / Elo Tournament
                                                            └─► Deep Verification
                                                                    └─► Orchestrator

Orchestrator (the single loop point) routes to the task it picked:
    generate   ─► Generate     ─► (back into the spine at Review)
    reflect    ─► Review
    rank       ─► Safety Screen
    evolve     ─► Meta-Review ─► Evolve ─► Review
    proximity  ─► Proximity   ─► Orchestrator
    terminate  ─► Research Overview ─► END
```

| Node | Purpose | Key Operations |
|---|---|---|
| Supervisor | Decomposes the research goal into a structured plan | Analyzes research goal, identifies key areas, creates workflow strategy |
| Literature Review *(recommended)* | Runs MCP-provided search tools; falls back to LLM-only if unavailable | Queries the configured sources (PubMed, OpenAlex, and web search in the default config), retrieves and analyzes real published papers |
| Generate | Produces initial hypotheses via debate or literature-grounded tool calls | Generates N initial hypotheses using LLM with high temperature for diversity |
| Reflection *(recommended)* | Compares hypotheses against retrieved literature | Analyzes hypotheses against literature review findings, identifies novel contributions |
| Review | Parallel peer reviews scoring novelty, soundness, relevance, etc. | Reviews hypotheses across 6 criteria using adaptive strategy (comparative batch for ≤5, parallel for >5) |
| Comprehensive Reflection | Deeper critique of the hypotheses that cleared the review gate | Tool-grounded observation, full, simulation, and recurrent reviews |
| Safety Screen | Per-hypothesis screen before the tournament | Removes blocked hypotheses and records the decision audit trail |
| Ranking | Sorts by score, then runs an Elo pairwise tournament | LLM ranks all hypotheses considering composite scores and review feedback |
| Deep Verification | Probes the top hypotheses by Elo with targeted questions | Decomposes assumptions and checks them against retrieved evidence |
| Orchestrator | The adaptive loop point; picks the next task each cycle | Computes scheduler stats from live state and applies the deterministic policy |
| Meta-Review | Synthesizes cross-hypothesis insights to guide evolution | Analyzes all reviews to identify common strengths, weaknesses, and strategic directions |
| Evolve | Refines the top-k hypotheses using meta-review feedback | Refines top-k hypotheses with context awareness to preserve diversity |
| Proximity | Semantic deduplication; removes near-duplicate hypotheses | Clusters similar hypotheses and removes high-similarity duplicates |
| Research Overview | Terminal synthesis once the orchestrator decides to stop | Produces the research overview and roadmap |

State flows through the `WorkflowState` typed dictionary and its declared reducers. The `hypotheses` field uses a custom `deduplicate_hypotheses` reducer that auto-removes duplicates on every state update.

## Literature review and MCP server

Literature review requires a running MCP server. The bundled reference server (`mcp_server/`) is built on FastMCP and provides PubMed search + fulltext extraction (via Biopython), OpenAlex search, ChEMBL/UniProt lookups, INDRA CoGex knowledge-graph queries, a local paper-corpus fetch, and open-web search/read tools.

### Starting the reference server

The server requires Python 3.12 and an NCBI Entrez email:

```bash
# Docker (recommended)
cp mcp_server/.env.example mcp_server/.env
# edit mcp_server/.env: set ENTREZ_EMAIL
docker compose up -d

# Local (run from engine/)
python3.12 -m venv .venv-mcp && source .venv-mcp/bin/activate
pip install -e mcp_server/
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

The engine auto-detects MCP availability at runtime. If the server is not reachable, the literature review and reflection nodes are skipped and generation proceeds with LLM-only mode.

Configure the server URL (defaults to `http://localhost:8888/mcp`):

```bash
export MCP_SERVER_URL=http://localhost:8888/mcp
```

### Custom tool configuration

The engine uses a YAML-based tool registry that decouples literature sources from library code. This lets you bring your own MCP servers without modifying the engine.

The default config (`src/co_scientist/config/tools.yaml`) declares the bundled
academic, biomedical and web tools. The retained examples extend it with INDRA
CoGex guidance for oncology (`indra_cancer.yaml`) and cardiac remodeling
(`indra_hfpef.yaml`). Use either as the starting point for a custom YAML overlay.

Set the app's `TOOLS_CONFIG` to the selected YAML file:

```dotenv
TOOLS_CONFIG=/absolute/path/to/indra_cancer.yaml
```

See `src/co_scientist/config/schema.py` for the schema and
`src/co_scientist/config/tools.yaml` for the shipped configuration.

## Caching

LLM responses are cached to disk by default, keyed by prompt content. This makes iterative development much faster.

```bash
COSCIENTIST_CACHE_ENABLED=false   # disable caching
COSCIENTIST_CACHE_DIR=.my_cache   # change cache directory (default: .coscientist_cache)
```

Cache utilities:

```python
from co_scientist.cache import clear_cache, get_cache_stats
print(get_cache_stats())
clear_cache()
```

## LLM providers

Model strings follow the LiteLLM convention (`provider/model-name`). Any provider supported by LiteLLM works — set the corresponding API key:

```bash
# DeepSeek (the default model's provider)
export DEEPSEEK_API_KEY=...

# Gemini
export GEMINI_API_KEY=...

# OpenAI
export OPENAI_API_KEY=...

# Anthropic
export ANTHROPIC_API_KEY=...
```

Set `MODEL_NAME` in the app configuration or choose a model in the workbench.

## Development

### Commands

Run from `engine/`:

```bash
pip install -e '.[dev]'     # install with dev dependencies
pytest                       # run tests
ruff format .                # format (80 cols)
ruff check .                 # lint
mypy .                       # typecheck
```

### Focused development

Use the existing `tests/` suites for isolated agent checks:

```bash
pytest tests/test_coordinator.py tests/test_supervisor.py
```

### Code style

- Apply PLAN.md’s hidden-reasons documentation policy.
- `logger.debug()` lowercase; `info` / `warning` / `error` capitalized.
- No emojis or Unicode decoration in library code or logs.
- Line length: 80. Formatter: `ruff format`. Linter: `ruff check`.

#### Logging

| Level | When to use | Capitalization |
|---|---|---|
| `logger.debug()` | Internal traces, detailed diagnostics | lowercase |
| `logger.info()` | User-facing milestones, progress updates | Capitalize |
| `logger.warning()` | Recoverable issues, important notices | Capitalize |
| `logger.error()` | Errors that affect functionality | Capitalize |

```python
# Debug - lowercase, internal details
logger.debug("cache hit for prompt")
logger.debug(f"analyzing hypothesis {i+1}/{len(hypotheses)}")

# Info/warning/error - capitalize
logger.info("Starting literature review")
logger.warning("No articles found, skipping reflection")
logger.error(f"Reflection failed for hypothesis {i}: {e}")
```

Use package-level loggers to avoid noise from other libraries:

```python
import logging
logger = logging.getLogger(__name__)

# Scope log level to this package only
logging.getLogger("co_scientist").setLevel(logging.DEBUG)
```

## Architecture reference

```
src/co_scientist/
├── generator/          # Internal configuration and durable initial state
├── state/              # WorkflowState TypedDict + custom reducers
├── models/             # Hypothesis, HypothesisReview, ExecutionMetrics dataclasses
├── llm/                # LiteLLM dispatch: call, request, attempts, structured, tools
├── mcp_client/         # MCP server connection (langchain-mcp-adapters)
├── cache/              # Disk-based LLM response cache
├── constants/          # Elo params, token limits, workflow defaults
├── progress.py         # Shared progress-event emission used by agent nodes
├── schemas/            # JSON schemas for structured LLM output
├── prompts/            # Prompt builders; templates/ has the markdown files (bundled as package data)
├── scheduling/         # Deterministic orchestrator scheduling policy and budget
├── config/             # ToolRegistry, YAML tool configs, domain examples
└── agents/             # Node implementations, one package per agent
    ├── supervisor/     # supervisor.py (planning), orchestrator.py (per-cycle routing)
    ├── generation/     # generate.py, coordinator*.py, debate.py, citations.py, literature_review/, literature_tools/
    ├── reflection/     # reflection.py, review.py, comprehensive_reflection.py, deep_verification.py
    ├── ranking/        # Elo tournament (ranking.py, ranking_elo.py, ranking_matchmaking.py, ...)
    ├── evolution/      # evolve.py + evolve_* helpers
    ├── meta_review/    # meta_review.py, research_overview.py
    ├── proximity/      # proximity.py (dedup)
    └── safety.py       # hypothesis screen and research-direction monitor
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — agents, workflow, state and generation modes
- [Running locally](../docs/RUNNING-LOCALLY.md) — setup and checks
- [Operations](../docs/OPERATIONS.md) — operational invariants
- [Engine guide](AGENTS.md) — implementation map and conventions
