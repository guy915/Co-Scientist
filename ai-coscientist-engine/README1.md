# open-coscientist

LangGraph-based multi-agent framework for automated research hypothesis generation, adapted from Google DeepMind's AI Co-Scientist.

Given a research goal, the system runs a pipeline of specialized agents — literature review, hypothesis generation, peer review, Elo tournament ranking, meta-review, and iterative evolution — to produce a ranked list of novel, grounded hypotheses.

## Installation

Requires Python 3.10+.

```bash
pip install open-coscientist
```

For local development:

```bash
git clone https://github.com/jataware/open-coscientist
cd open-coscientist
pip install -e '.[dev]'
```

## Quick start

Set an API key for your LLM provider (Gemini is the default model):

```bash
export GEMINI_API_KEY=your_key_here
```

Run the interactive CLI demo:

```bash
python examples/run.py
```

Or call the library directly:

```python
import asyncio
from open_coscientist import HypothesisGenerator

async def main():
    generator = HypothesisGenerator(
        model_name="gemini/gemini-2.5-flash",
        max_iterations=1,
        initial_hypotheses_count=5,
        evolution_max_count=3,
    )

    result = await generator.generate_hypotheses(
        research_goal="Develop novel approaches for early detection of Alzheimer's disease"
    )

    for hyp in result["hypotheses"]:
        print(f"[{hyp.elo_rating}] {hyp.text[:120]}")

asyncio.run(main())
```

`generate_hypotheses` returns a dict with the full `WorkflowState`. The `hypotheses` list is sorted by Elo rating descending.

## Streaming

Pass `stream=True` to get an async generator of node-level events:

```python
async for event in generator.generate_hypotheses(
    research_goal="...",
    stream=True,
):
    phase = event.get("phase")
    data  = event.get("data", {})
    print(phase, data)
```

For rich terminal output, use the built-in `ConsoleReporter`:

```python
from open_coscientist import HypothesisGenerator
from open_coscientist.console import ConsoleReporter, default_progress_callback

reporter = ConsoleReporter()
await reporter.run(
    event_stream=generator.generate_hypotheses(
        research_goal="...",
        progress_callback=default_progress_callback,
        stream=True,
    ),
    research_goal="...",
)
```

## Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model_name` | `str` | `"gemini/gemini-2.5-flash"` | LiteLLM model string |
| `max_iterations` | `int` | `1` | Refinement iterations after initial generation |
| `initial_hypotheses_count` | `int` | `5` | Number of hypotheses to generate initially |
| `evolution_max_count` | `int` | `3` | Top-k hypotheses to evolve each iteration |
| `enable_cache` | `bool \| None` | `None` | Override `COSCIENTIST_CACHE_ENABLED` env var |
| `cache_dir` | `str \| None` | `None` | Override cache directory |
| `tools_config` | `str \| None` | `None` | Path to a custom tools YAML config |
| `disable_tools` | `list[str] \| None` | `None` | Tool IDs to disable from the config |

`generate_hypotheses` accepts optional `opts` dict for per-run feature flags:

```python
await generator.generate_hypotheses(
    research_goal="...",
    opts={
        "enable_literature_review_node": True,   # requires MCP server
        "enable_tool_calling_generation": True,  # generate node calls lit tools directly
    },
)
```

Additional per-run steering via keyword arguments:

```python
await generator.generate_hypotheses(
    research_goal="...",
    preferences="Focus on non-invasive biomarkers",
    attributes=["novelty", "experimental feasibility"],
    constraints=["must be testable in mouse models"],
    starting_hypotheses=["Tau protein changes precede amyloid plaques"],
)
```

## Workflow

The graph executes the following nodes in order:

```
Supervisor
    └─► Literature Review  (optional, requires MCP server)
            └─► Generate
                    └─► Reflection  (if Literature Review ran)
                            └─► Review
                                    └─► Ranking / Elo Tournament
                                            ├─► [end if max_iterations = 0]
                                            └─► Meta-Review
                                                    └─► Evolve
                                                            └─► Review
                                                                    └─► Ranking
                                                                            └─► Proximity (dedup)
                                                                                    └─► [loop or end]
```

| Node | Purpose |
|---|---|
| Supervisor | Decomposes the research goal into a structured plan |
| Literature Review | Runs MCP-provided search tools; falls back to LLM-only if unavailable |
| Generate | Produces initial hypotheses via debate or literature-grounded tool calls |
| Reflection | Compares hypotheses against retrieved literature |
| Review | Parallel peer reviews scoring novelty, soundness, relevance, etc. |
| Ranking | Sorts by score, then runs an Elo pairwise tournament |
| Meta-Review | Synthesizes cross-hypothesis insights to guide evolution |
| Evolve | Refines the top-k hypotheses using meta-review feedback |
| Proximity | Semantic deduplication; removes near-duplicate hypotheses |

State flows through `WorkflowState` (a LangGraph `TypedDict`). The `hypotheses` field uses a custom `deduplicate_hypotheses` reducer that auto-removes duplicates on every state update.

## Literature review and MCP server

Literature review requires a running MCP server. The bundled reference server (`mcp_server/`) provides PubMed search + fulltext extraction via Biopython and FastMCP.

### Starting the reference server

The server requires Python 3.12 and an NCBI Entrez email:

```bash
# Docker (recommended)
cp mcp_server/.env.example mcp_server/.env
# edit mcp_server/.env: set ENTREZ_EMAIL
docker compose up -d

# Local
python3.12 -m venv .venv-mcp && source .venv-mcp/bin/activate
pip install -e mcp_server/
cd ..   # parent of open-coscientist
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

The engine auto-detects MCP availability at runtime. If the server is not reachable, the literature review and reflection nodes are skipped and generation proceeds with LLM-only mode.

Configure the server URL (defaults to `http://localhost:8888/mcp`):

```bash
export MCP_SERVER_URL=http://localhost:8888/mcp
```

### Custom tool configuration

The engine uses a YAML-based tool registry that decouples literature sources from library code. This lets you bring your own MCP servers without modifying the engine.

The default config (`src/open_coscientist/config/tools.yaml`) targets the bundled PubMed server. Pre-built examples in `src/open_coscientist/config/examples/` cover:

- `arxiv_only.yaml` — arXiv for AI/ML/CS/physics research
- `multi_source.yaml` — PubMed + arXiv + Google Scholar in parallel
- `google_scholar.yaml` — Google Scholar with two-step PDF retrieval
- `indra_cancer.yaml` / `indra_alzheimers.yaml` / `indra_ibd.yaml` / `indra_hfpef.yaml` — domain-specific biomedical configs extending PubMed with INDRA CoGex knowledge-graph tools

Pass a config at construction time:

```python
generator = HypothesisGenerator(
    tools_config="src/open_coscientist/config/examples/indra_cancer.yaml",
)
```

See `src/open_coscientist/config/examples/README.md` and `docs/literature_review_tools_configuration.md` for the full schema.

## Caching

LLM responses are cached to disk by default, keyed by prompt content. This makes iterative development much faster.

```bash
COSCIENTIST_CACHE_ENABLED=false   # disable caching
COSCIENTIST_CACHE_DIR=.my_cache   # change cache directory (default: .coscientist_cache)
```

Cache utilities:

```python
from open_coscientist import clear_cache, get_cache_stats
print(get_cache_stats())
clear_cache()
```

## LLM providers

Model strings follow the LiteLLM convention (`provider/model-name`). Any provider supported by LiteLLM works — set the corresponding API key:

```bash
# Gemini (default)
export GEMINI_API_KEY=...

# OpenAI
export OPENAI_API_KEY=...

# Anthropic
export ANTHROPIC_API_KEY=...
```

Pass the model string to `HypothesisGenerator`:

```python
HypothesisGenerator(model_name="openai/gpt-4o")
HypothesisGenerator(model_name="anthropic/claude-opus-4-5")
```

## Development

### Commands

Run from `ai-coscientist-engine/`:

```bash
pip install -e '.[dev]'     # install with dev dependencies
pytest                       # run tests
black . && ruff check --fix . # format
ruff check .                 # lint
mypy .                       # typecheck
```

### Node isolation scripts

The `dev/` directory contains standalone scripts for running individual nodes without the full graph — useful for fast iteration on a single component. They load a `.env` from `dev/` itself (not the project root).

```bash
cp dev/.env.example dev/.env
# add GEMINI_API_KEY (and MCP_SERVER_URL for lit review)

python dev/run_supervisor_standalone.py
python dev/run_generate_standalone.py
python dev/run_lit_review_standalone.py   # requires MCP server
```

See `dev/README.md` for full details and available environment flags.

### Code style

- Docstrings: capitalized, full sentences.
- `logger.debug()` lowercase; `info` / `warning` / `error` capitalized.
- No emojis or Unicode decoration in library code or logs.
- `rich` only in `examples/` and `dev/`, never in core library code.
- Line length: 100. Formatter: `black`. Linter: `ruff`.

## Architecture reference

```
src/open_coscientist/
├── generator.py        # HypothesisGenerator — public entry point, builds/runs LangGraph
├── state.py            # WorkflowState TypedDict + custom reducers
├── models.py           # Hypothesis, HypothesisReview, ExecutionMetrics dataclasses
├── llm.py              # LiteLLM wrapper
├── mcp_client.py       # MCP server connection (langchain-mcp-adapters)
├── cache.py            # Disk-based LLM response cache
├── constants.py        # Elo params, token limits, workflow defaults
├── prompts/            # Markdown prompt files (bundled as package data)
├── config/             # ToolRegistry, YAML tool configs, domain examples
└── nodes/
    ├── supervisor.py
    ├── literature_review.py
    ├── generate.py / generation/
    ├── reflection.py
    ├── review.py
    ├── ranking.py          # Elo tournament lives here
    ├── meta_review.py
    ├── evolve.py
    └── proximity.py
```

## Links

- GitHub: https://github.com/jataware/open-coscientist
- Original paper: [Towards an AI co-scientist (Google DeepMind, 2025)](https://storage.googleapis.com/coscientist_paper/ai_coscientist.pdf)
