# Configuration Guide

Complete guide to configuring Co-Scientist for your needs.

## Basic Configuration

```python
from co_scientist import GeneratorOptions, HypothesisGenerator

generator = HypothesisGenerator(
    model_name="deepseek/deepseek-v4-flash",  # Default; any LiteLLM-supported model
    max_iterations=1,                         # Number of refinement cycles
    initial_hypotheses_count=5,               # Initial pool size
    evolution_max_count=3,                    # How many to evolve and keep
    options=GeneratorOptions(
        enable_cache=True,                    # LLM response caching
        cache_dir=".coscientist_cache",       # Cache location (relative to CWD)
        tools_config="path/to/tools.yaml",    # Optional: custom domain/source config
    ),
)
```

Only the four run-size knobs are top-level constructor arguments; every other
knob lives on `GeneratorOptions` and is passed as `options=`. See constants.py
for other defaults.

## Configuration Parameters

Constructor arguments:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model_name` | `"deepseek/deepseek-v4-flash"` | LLM model in LiteLLM format (e.g., `"claude-sonnet-4-6"`, `"gpt-4o"`, `"gemini/gemini-2.5-flash"`) |
| `max_iterations` | `1` | Number of refinement cycles (0 = no evolution/meta-review phase) |
| `initial_hypotheses_count` | `5` | Initial hypothesis pool size |
| `evolution_max_count` | `3` | Number of top hypotheses to evolve in each iteration |

`GeneratorOptions` fields (see `generator/options.py`):

| Field | Default | Description |
|-----------|---------|-------------|
| `supervisor_model_name` | `None` | Model for the supervisor and meta-review steps (`None` = `model_name`) |
| `tournament_pairs` | `12` | Elo tournament comparisons per ranking pass |
| `elo_k_factor` | `24` | Rating change magnitude per match |
| `literature_review_papers_count` | `8` | Number of papers to read and analyze |
| `enable_cache` | `None` | Override caching for this generator (`None` = the `COSCIENTIST_CACHE_ENABLED` process default, which is on) |
| `cache_dir` | `None` | Cache directory (`None` = `COSCIENTIST_CACHE_DIR`, default `.coscientist_cache`) |
| `tools_config` | `None` | Path to a custom YAML tools configuration file; see [Literature Review Tools Configuration](LITERATURE_REVIEW_TOOLS_CONFIGURATION.md) |
| `disable_tools` | `None` | Tool IDs to disable from the resolved config |
| `budget` | `None` | Serialized scheduler `Budget` (`max_iterations`, `max_llm_calls`, `max_tasks`, `max_wall_clock_s`) |
| `api_key` | `None` | Per-run provider credential; forces caching off for the run |

## Model Selection

Co-Scientist uses [LiteLLM](https://docs.litellm.ai/docs/providers), which supports 100+ LLM providers:

### OpenAI

```python
# Set API key
export OPENAI_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="gpt-4o")
```

### Anthropic

```python
# Set API key
export ANTHROPIC_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="claude-sonnet-4-6")
```

### Google Gemini

```python
# Set API key
export GEMINI_API_KEY="your-key-here"

# Use in code
generator = HypothesisGenerator(model_name="gemini/gemini-2.5-flash")
```

### Azure, AWS Bedrock, Cohere

See [LiteLLM provider documentation](https://docs.litellm.ai/docs/providers) for configuration details.

### Offline / deterministic backend

Any model name prefixed `offline/` (default: `offline/deterministic`) is
answered locally instead of calling a real provider. Call
`co_scientist.offline_llm.install_offline_router()` once at process startup
to install the router: it wraps `litellm.acompletion` so calls to
`offline/`-prefixed models are intercepted, while every other model passes
through untouched — real and offline models can coexist in the same process.

```python
from co_scientist.offline_llm import install_offline_router

install_offline_router()

generator = HypothesisGenerator(model_name="offline/deterministic")
```

**Determinism contract:** identical calls (same model, prompt, and response
schema) always produce byte-identical output; different prompts produce
different output. Each call seeds a `random.Random` from a SHA-256 digest of
`(model, prompt, schema name)` and fills the response schema from that seed,
drawing free-text leaves from a small pseudo-scientific phrase bank so the
output reads as presentable prose rather than placeholder hashes.

This is not a test-only fixture — it's a real runtime backend. The
`co-scientist-viewer` app installs the router unconditionally at startup and
routes every keyless, `COSCIENTIST_FORCE_OFFLINE=1`, demo-seeding, and test
run through it, so the full engine graph runs with no LLM provider key and
no API spend.

## Runtime Options

The `generate_hypotheses()` method accepts an `opts` dictionary for runtime configuration:

```python
# Non-streaming
result = await generator.generate_hypotheses(
    research_goal="Your research question",
    stream=False,  # Will have to wait with no feedback, sometimes >10 minutes, if no cache and no logging enabled
    opts={
        # Literature review control
        "enable_literature_review_node": True,
        "enable_tool_calling_generation": False,
    }
)

# Streaming
async for node_name, state in generator.generate_hypotheses(
    research_goal="Your research question",
    stream=True,
    opts={...}
):
    print(f"Completed: {node_name}")
```

### Available Runtime Options

| Option | Default | Description |
|--------|---------|-------------|
| `enable_literature_review_node` | `True` (if MCP available) | Enable/disable literature review node |
| `enable_tool_calling_generation` | `False` | Allow Generate node to use MCP tools (requires literature review) |
| `dev_test_lit_tools_isolation` | `False` | Forces all hypotheses through tool-calling generation (no debate) and forces literature review node caching. Development/testing only. |

See [MCP Integration](MCP_INTEGRATION.md) for details on literature review modes.

## Caching

LLM caching dramatically speeds up development and testing by reusing identical LLM calls.

### Cache Management

```python
from co_scientist import clear_cache, get_cache_stats

# Clear all cached responses
cleared = clear_cache()
print(f"Cleared {cleared} responses")

# Check cache statistics
stats = get_cache_stats()
print(f"Cache: {stats['cache_files']} files, {stats['total_size_mb']:.2f} MB")
```

### Environment Variables

#### Caching

```bash
# Enable/disable caching
export COSCIENTIST_CACHE_ENABLED=true

# Custom cache directory
export COSCIENTIST_CACHE_DIR=".cache"
```

#### Literature Review (PubMed)

Literature review uses a separate MCP server that runs in its own process (Python 3.12+). Configure the MCP server by editing `mcp_server/.env`:

```bash
# Required for PubMed access
ENTREZ_EMAIL=your_email@example.com

# Optional: higher rate limits
ENTREZ_API_KEY=your_ncbi_api_key

# Optional: literature review cache directory
COSCIENTIST_LIT_REVIEW_DIR=./cache/literature_review
```

**Important Notes**:
- The MCP server runs separately with its own environment - set API keys in `mcp_server/.env`, not in the main co-scientist-engine environment
- The literature review node is gated on the MCP **server** being reachable, not on any single source. Without `ENTREZ_EMAIL` the PubMed tools report themselves unavailable, but the node still runs and the other configured sources (OpenAlex, web search) still contribute. Only an unreachable MCP server disables the node entirely, falling back to standard mode (no literature analysis)

### Cache Behavior

- **Default location**: `.coscientist_cache/` relative to current working directory
- **Cache key includes**: prompt, model name, temperature, max_tokens, cache schema version, plus the response-shape parameters when set (`tools`, `json_schema`, `force_json`, `tool_contract`)
- **Benefits**: faster iteration during development, significant cost savings
- **Safe to delete**: Cache directory can be deleted at any time

## Constants and Internal Parameters

Most users won't need to modify these, but they're centralized in `src/co_scientist/constants.py`:

### Elo Rating Parameters

Defined in `src/co_scientist/constants_tournament.py` (re-exported from `constants.py`):

```python
INITIAL_ELO_RATING = 1200  # Starting Elo rating for all hypotheses
ELO_K_FACTOR = 24          # Rating change magnitude per match
```

### LLM Token Limits

```python
DEFAULT_MAX_TOKENS = 4000     # Standard responses
EXTENDED_MAX_TOKENS = 8000    # Longer responses
LONG_MAX_TOKENS = 10000       # Very long responses
THINKING_MAX_TOKENS = 18000   # Extended thinking models
```

### Temperature Settings

```python
LOW_TEMPERATURE = 0.3     # Ranking, tournament (consistency)
MEDIUM_TEMPERATURE = 0.5  # Meta-review, supervisor (balanced)
HIGH_TEMPERATURE = 0.7    # Generation, evolution, review (creativity)
```

Some models, especially thinking ones, require temperature=1 or ignore the parameter altogether to default to 1.

### Similarity Thresholds

```python
DUPLICATE_SIMILARITY_THRESHOLD = 0.95  # Remove near-identical hypotheses
```

### Modifying Constants

If you need to tune these parameters, edit `src/co_scientist/constants.py` (or
`constants_tournament.py` for the Elo/tournament parameters above).

Modifying constants may affect result quality and should be done with careful evaluation.

## Performance Tuning

### For Speed

```python
generator = HypothesisGenerator(
    model_name="gemini/gemini-2.5-flash",   # Fast, cheap model
    max_iterations=1,                       # Not many iterations
    initial_hypotheses_count=3,             # Smaller pool
    options=GeneratorOptions(enable_cache=True),  # Reuse responses
)
```

### For Quality

```python
generator = HypothesisGenerator(
    max_iterations=4,                         # Multiple refinement cycles
    initial_hypotheses_count=8,               # Larger diverse pool
    evolution_max_count=6,                    # Evolve more hypotheses
    model_name="claude-sonnet-4-6",    # High-quality model
)
```

### For Cost Optimization

```python
generator = HypothesisGenerator(
    model_name="gemini/gemini-2.5-flash",   # Cost-effective model
    initial_hypotheses_count=5,             # Moderate pool size
    options=GeneratorOptions(enable_cache=True),  # Avoid redundant calls
)
```