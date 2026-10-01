# Development Guide

Guide for contributors and developers working on Co-Scientist internals.

## Project Structure

```
engine/
├── src/
│   └── co_scientist/
│       ├── __init__.py
│       ├── generator/          # HypothesisGenerator package (core, graph, streaming)
│       ├── state.py            # WorkflowState TypedDict
│       ├── schemas/            # JSON schemas for LLM responses
│       ├── models/             # Hypothesis, Article dataclasses (among others)
│       ├── llm/                # LLM dispatch package (call, request, attempts, tools)
│       ├── cache.py            # LLM response caching
│       ├── mcp_client.py       # MCP server integration
│       ├── constants/          # Configuration constants
│       ├── config/             # YAML-based tool/domain configuration
│       │   ├── registry.py     # Config loading and merge logic
│       │   ├── schema.py       # Config schema validation
│       │   ├── tools.yaml      # Default tool/source config (PubMed, OpenAlex, web)
│       │   └── examples/       # Domain-specific example configs
│       ├── agents/             # Node implementations, one package per agent
│       │   ├── supervisor/     # supervisor.py (planning), orchestrator.py (routing)
│       │   ├── generation/     # generate.py, coordinator*.py, debate.py,
│       │   │                   # citations.py, literature_review/, literature_tools/
│       │   ├── reflection/     # reflection.py, review.py, deep_verification.py, ...
│       │   ├── ranking/        # Elo tournament (ranking.py, ranking_elo.py, ...)
│       │   ├── evolution/      # evolve.py + evolve_* helpers
│       │   ├── meta_review/    # meta_review.py, research_overview.py
│       │   ├── proximity/      # proximity.py (dedup)
│       │   └── safety/         # safety_screen.py (cross-cutting screen)
│       ├── scheduling/         # Deterministic orchestrator scheduling policy
│       ├── progress.py         # Shared progress-event emission for agent nodes
│       └── prompts/            # Prompt builders grouped by consumer node
│           └── templates/      # Markdown prompt templates
│               ├── supervisor.md
│               ├── review.md
│               └── ...
├── examples/
│   └── run.py                  # CLI example
├── mcp_server/                 # Reference MCP server implementation
└── docs/                       # Documentation
```

## Node Structure

Each node is an async function that follows a consistent pattern:

```python
from typing import Any
from co_scientist.state import WorkflowState
from co_scientist.llm import CompletionSpec, call_llm_json

async def node_name(state: WorkflowState) -> dict[str, Any]:
    """
    Brief description of what this node does.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with state updates to merge
    """
    # 1. Extract relevant state
    hypotheses = state["hypotheses"]
    research_goal = state["research_goal"]

    # 2. Perform operation (often with LLM call)
    response = await call_llm_json(
        prompt="Your prompt here",
        spec=CompletionSpec(
            model_name=state["model_name"],
            temperature=0.7,
            max_tokens=4000,
            json_schema=YourSchema,
        ),
    )

    # 3. Update metrics
    metrics = create_metrics_update(...)
    result["metrics"] = metrics

    # 4. Process results and update hypotheses
    for hyp in hypotheses:
        # Update hypothesis based on node operation
        pass

    # 5. Return state updates (only changed fields)
    return {
        "hypotheses": hypotheses,
        "metrics": metrics,
        "messages": [f"{node_name} completed"],
    }
```

## Adding a New Node

### 1. Create Node File

Create the node inside the agent package that owns it, e.g.
`src/co_scientist/agents/my_agent/my_node.py`:

```python
from typing import Any
from co_scientist.state import WorkflowState
from co_scientist.llm import call_llm_json

async def my_node(state: WorkflowState) -> dict[str, Any]:
    """Your node implementation."""
    # Implementation here
    return {"hypotheses": state["hypotheses"]}
```

### 2. Create Prompt Template

Create `src/co_scientist/prompts/templates/my_node.md`:

```markdown
# My Node Prompt

Your prompt instructions here.

## Research Goal
{research_goal}

## Hypotheses
{hypotheses}
```

### 3. Register the Node and Wire It

`co_scientist.agents.NODE_REGISTRY` is the single source of truth for durable
graph-node keys: `graph.py` registers nodes by iterating it, `task_runtime`
derives its task nodes from it, and `NODE_TO_AGENT` is projected from it. Add
a `NodeSpec` there, then name its successor once in
`src/co_scientist/workflow_topology.py` -- the compiled graph is wired from
that table and the durable runtime resolves through it, so both paths get the
edge:

```python
# In src/co_scientist/agents/__init__.py: import my_agent alongside the
# other agent packages, then add its node inside NODE_REGISTRY:
"my_node": NodeSpec("my_agent", my_agent.my_node),

# In workflow_topology.py, in WORKFLOW_ROUTES:
"previous_node": "my_node",
"my_node": "next_node",
```

Node keys are persisted verbatim in durable tasks, checkpoints, and
idempotency keys, so an existing key must never change value.

### 4. Update State Type (if needed)

If your node adds new state fields, update `src/co_scientist/state.py`:

```python
class WorkflowState(TypedDict, total=False):
    # Existing fields...
    my_new_field: str  # Add your field
```

## Working with State

### WorkflowState Fields

| Field | Type | Description |
|-------|------|-------------|
| `research_goal` | `str` | Original research question |
| `supervisor_guidance` | `dict` | Strategy from supervisor (exposed to stream/result consumers as `research_plan`) |
| `hypotheses` | `list[Hypothesis]` | Current hypothesis pool (serialized to dicts in stream/result payloads) |
| `articles_with_reasoning` | `str \| None` | Literature summary (if MCP available) |
| `articles` | `list[Article] \| None` | Retrieved papers (literature review) |
| `metrics` | `ExecutionMetrics` | Performance tracking |

There are many other fields. Inspect state as each node completed or view state.py for other captured state.

### Hypothesis Structure

Each hypothesis is a `Hypothesis` dataclass in state, serialized to a dict in stream and result payloads. Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | The technical hypothesis formulation |
| `explanation` | string | Step-by-step layman explanation |
| `literature_grounding` | string | Grounding in literature with `[C*]` citation keys |
| `experiment` | string | Suggested validation design |
| `citation_map` | dict | Resolves `[C*]` keys to full source metadata (papers and knowledge graph entries) |
| `enrichments` | dict | Post-generation domain data, keyed by `output_key` from enrichment config |
| `novelty_validation` | string | Novelty search summary (tool-calling generation only) |
| `score` | float | Composite review score |
| `elo_rating` | int | Elo rating from tournament |
| `reviews` | list | Per-review scores and feedback |
| `evolution_history` | list | Refinement summaries from Evolve node |
| `reflection_notes` | string | Reflection node analysis against literature |
| `generation_method` | string | One of `"debate"`, `"literature_tools"`, `"assumptions"`, `"research_expansion"` |

See `models/__init__.py` for the full `Hypothesis` dataclass.

## LLM Calling

### Standard JSON Response

```python
from co_scientist.llm import CompletionSpec, call_llm_json

response = await call_llm_json(
    prompt="Your prompt",
    spec=CompletionSpec(
        model_name="gemini/gemini-2.5-flash",
        temperature=0.7,
        max_tokens=4000,
        json_schema=MySchema, # uses schema where possible to avoid brittleness
    ),
)
```

### With Tool Calling (MCP)

```python
from co_scientist.llm import CompletionSpec, ToolLoop, call_llm_with_tools
from co_scientist.mcp_client import get_mcp_client
from co_scientist.tools.provider import MCPToolProvider

mcp_client = await get_mcp_client()
provider = MCPToolProvider(mcp_client=mcp_client)
_, openai_tools = provider.get_tools()

response, _ = await call_llm_with_tools(
    prompt="Your prompt",
    spec=CompletionSpec(model_name="gemini/gemini-2.5-flash"),
    loop=ToolLoop(tools=openai_tools, executor=provider.execute_tool_call),
)
```

## Debugging

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("co_scientist")
```

### Inspect State Between Nodes

```python
async for node_name, state in generator.generate_hypotheses(research_goal, stream=True):
    print(f"\n{node_name} completed")
    print(f"Hypotheses: {len(state['hypotheses'])}")
    print(f"Metrics: {state['metrics']}")
```

### Cache Debugging

```python
from co_scientist import get_cache_stats

# Check what's cached
stats = get_cache_stats()
print(f"Cached: {stats['cache_files']} responses")

# Clear cache to force fresh LLM calls
from co_scientist import clear_cache
clear_cache()
```

## Performance Optimization

### Parallel Execution

Use `asyncio.gather()` for parallel operations:

```python
import asyncio

# Run reviews in parallel
review_tasks = [
    review_single_hypothesis(hyp, state)
    for hyp in hypotheses
]
results = await asyncio.gather(*review_tasks)
```

### Token Optimization
- Use shorter prompts when possible
- Batch similar operations (comparative review)
- Use appropriate max_tokens limits

## Contributing

### Prompt Engineering

- Store prompts in `prompts/templates/` as markdown files
- Use clear section headers
- Include examples in prompts
- Test prompts with multiple models

## Advanced Topics

### Extending MCP Tools

Add new tools to the MCP server for domain-specific needs:

- Custom databases
- Domain-specific validators
- Simulation runners
- Data analysis tools

See [MCP Integration](MCP_INTEGRATION.md) for details.
