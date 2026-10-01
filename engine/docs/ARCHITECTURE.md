# Architecture

Co-Scientist mirrors Google's AI Co-Scientist: a coalition of **six specialized agents** — Generation, Reflection, Ranking, Evolution, Proximity, and Meta-review — coordinated by a **Supervisor**, with **Safety** screening as a cross-cutting concern. It uses LangGraph to run them as a durable, resumable multi-stage workflow over shared state.

## The Six Agents

Each agent is a package under [`co_scientist.agents`](../src/co_scientist/agents/__init__.py) that holds that agent's node implementations — the canonical, Google-aligned structure of the system. Every agent's work is decomposed into one or more durable LangGraph **nodes** so the engine can checkpoint and resume at fine granularity. `co_scientist.agents.NODE_TO_AGENT` is the source-of-truth node→agent mapping:

| Agent | Role (Google) | Durable graph nodes |
|---|---|---|
| **Supervisor** | Plans the run; picks the next task each cycle | `supervisor`, `orchestrator` |
| **Generation** | Proposes novel, literature-grounded hypotheses | `generate`, `literature_review` |
| **Reflection** | Reviews, critiques, and verifies hypotheses | `review`, `reflection`, `comprehensive_reflection`, `deep_verification` |
| **Ranking** | Elo tournament of pairwise scientific debates | `ranking` |
| **Evolution** | Improves and recombines top hypotheses | `evolve` |
| **Proximity** | Clusters near-duplicate hypotheses | `proximity` |
| **Meta-review** | Synthesizes findings into the research overview | `meta_review`, `research_overview` |
| _Safety_ (cross-cutting) | Screens goal + hypotheses at intake / per-idea / final | `safety_screen` (+ the app viewer's intake and final gates) |

**Why more than six nodes?** The agents are the conceptual unit; the nodes are the durable-execution unit. Decomposing an agent (e.g. Reflection → `review` → `comprehensive_reflection` → `deep_verification`) lets an interrupted run resume mid-agent instead of re-running expensive LLM work. Those node key strings are persisted verbatim — as `engine.node.<key>` durable tasks, in checkpoint `resume_successor`/`next_task`, and inside idempotency keys — so collapsing them to six runtime keys would orphan any in-flight run. The node implementations live in the six-agent `agents` packages; only that runtime-key collapse is deferred, as a separate migration-guarded change.

## Workflow Graph

The workflow consists of specialized nodes that handle different aspects of hypothesis generation and refinement, declared once in `workflow_topology.py` and wired into the graph by `generator/graph.py`. Every work phase converges on the same review-through-ranking spine, and every completion path (a work phase's own end, or a maintenance task) returns to a single **orchestrator** loop point rather than following a fixed iteration count:

```
┌─────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW GRAPH                            │
└─────────────────────────────────────────────────────────────────────┘

                              START
                                │
                 (resume=True: re-enter at ORCHESTRATOR instead)
                                ▼
                         ┌─────────────┐
                         │ SUPERVISOR  │  Creates research plan
                         └──────┬──────┘  and strategy
                                │
                     ┌──────────┴──────────┐
                     │   [MCP Available]   │
                     ▼                     ▼
          ┌──────────────────┐      ┌─────────────┐
          │ LITERATURE REVIEW│      │  GENERATE   │
          └────────┬─────────┘      └──────┬──────┘
                   ▼                       │
          ┌──────────────────┐             │
          │    GENERATE      │             │
          └────────┬─────────┘             │
                   ▼                       │
          ┌──────────────────┐             │
          │   REFLECTION     │             │
          │ (uses literature)│             │
          └────────┬─────────┘             │
                   └──────────┬─────────────┘
                              ▼
                       ┌──────────────┐
                       │   REVIEW     │◄────────────────────┐  re-review after
                       └──────┬───────┘                      │  evolution
                              ▼                               │
                 ┌─────────────────────────┐                  │
                 │ COMPREHENSIVE REFLECTION│                  │
                 └────────────┬────────────┘                  │
                              ▼                                │
                       ┌──────────────┐                        │
                       │ SAFETY SCREEN│  removes blocked        │
                       └──────┬───────┘  hypotheses first       │
                              ▼                                  │
                       ┌──────────────┐                          │
                       │    RANKING   │  Elo tournament            │
                       └──────┬───────┘                            │
                              ▼                                     │
                     ┌──────────────────┐                           │
                     │ DEEP VERIFICATION│  probes top-3 by Elo        │
                     └────────┬─────────┘                            │
                              ▼                                       │
                      ┌────────────────┐        ┌─────────────┐       │
       ┌─────────────►│  ORCHESTRATOR  │◄───────┤  PROXIMITY  │       │
       │              └───────┬────────┘        └──────┬──────┘       │
       │   picks the next task from live SchedulerStats  │             │
       │   (pool growth, Elo stability, match/proximity   ▲             │
       │    backlog) via the deterministic scheduling      │             │
       │    policy — an LLM may only recommend              │             │
       │                    │                                │             │
       │        ┌───────────┼──────────┬──────────┐          │             │
       │        ▼           ▼          ▼          ▼          │             │
       │   [generate]  [reflect]   [proximity] [evolve]───────┘             │
       │        │           │          │          │                        │
       │        ▼           └──────────┘          ▼                        │
       │   GENERATE       (loops to REVIEW)  ┌─────────────┐                │
       │   (new iteration)                   │ META-REVIEW │                │
       │                                      └──────┬──────┘                │
       │                                             ▼                       │
       │                                       ┌─────────────┐               │
       │                                       │   EVOLVE    │               │
       │                                       └──────┬──────┘               │
       │                                              └──────────────────────┘
       │
       └──── [terminate] ────► RESEARCH OVERVIEW ────► END
```

A rendered (mermaid) version of the same graph, plus the exact orchestrator routing table (`TASK_ROUTES`), is in [`docs/EXPLAINER.md`](../../docs/EXPLAINER.md) §4.

### Dynamic orchestration

The **orchestrator node** (`agents/supervisor/orchestrator.py`) is the graph's single adaptive loop point. Each time it fires it computes `SchedulerStats` from live state (pool growth, Elo stability, tournament match coverage, proximity backlog), passes them to a deterministic scheduling policy (`scheduling/policy.py::decide_next_task`, validated by `validate_decision`), records the decision and its reason in the run's Supervisor allocation ledger, and sets `next_task`. An LLM supervisor may *recommend* a task; the policy — not the model — decides and enforces the allowed transitions and budget. A fifth route, `rank`, is omitted from the diagram above for space: it re-enters the spine directly at `safety_screen` (not at `review` or `ranking`), the same node the main pipeline reaches after `comprehensive_reflection`. Termination fires on Elo convergence (top hypothesis stable across cycles) or an exhausted iteration/task budget, never on a fixed `max_iterations` branch hard-coded after ranking. `current_iteration` only advances when the orchestrator schedules a work task (`generate`/`evolve`); scheduling a maintenance task (`reflect`/`proximity`/`rank`) does not.

One node commit can also enqueue more than one future task at once: `task_runtime.plan_portfolio` resolves however much of a node's successor chain is knowable without running it, and the app's durable executor chains that lookahead through the queue's existing dependency gate (`app/app/engine_tasks/portfolio.py`) rather than enqueueing one task at a time and waiting on each. This changes *when* work is queued, not what the orchestrator decides — the routing above is unaffected.

## Adaptive Review Strategy

The Review node uses an adaptive strategy based on hypothesis count:

- **Small batches (≤5 hypotheses)**: Comparative batch review where the LLM sees all hypotheses together and assigns differentiated scores based on relative strengths
- **Large batches (>5 hypotheses)**: Parallel individual reviews for better scalability

This approach balances score differentiation (important for small batches) with token efficiency and speed (critical for large batches).

## State Management

Co-Scientist uses a typed state dictionary (`WorkflowState`) that flows through all nodes. Each node:

1. Receives the current state
2. Performs its operation (often with LLM calls)
3. Updates relevant state fields
4. Returns state updates to merge

Key state fields relevant to hypothesis output:

| Field | Set By | Description |
|-------|--------|-------------|
| `hypotheses` | Generate, Evolve | List of `Hypothesis` objects; each has `text`, `explanation`, `literature_grounding`, `experiment`, `citation_map`, `enrichments` |
| `articles` | Literature Review | Retrieved papers with `used_in_analysis` flag |
| `articles_with_reasoning` | Literature Review | Formatted literature summary used by Generate and Reflection nodes |
| `context_enrichment_sources` | Literature Review | Structured items from knowledge graph tools (e.g., INDRA statements); merged into citation index alongside papers |

See `state/__init__.py` for the full `WorkflowState` type definition.

## Citations

When a literature review runs, each hypothesis receives structured citations. The Generate node builds a `ReferenceIndex` from papers (`used_in_analysis=True`) and any knowledge graph enrichment sources (e.g., INDRA statements), assigning sequential `[C1]`, `[C2]`, ... keys. The LLM uses these keys in `literature_grounding`, and `citation_map` resolves each key to full source metadata (title, URL, authors, year for papers; display label and structured data for knowledge graph entries).

## Parallel Execution

Several nodes leverage parallel execution for performance:

- **Review node**: Reviews multiple hypotheses concurrently
- **Reflection node**: Runs reflection analysis for multiple hypotheses in parallel
- **Ranking node**: Runs pairwise comparisons in parallel
- **Evolve node**: Refines multiple hypotheses simultaneously

This parallelization significantly reduces total execution time, especially for large hypothesis pools.