# 09 — Build Methodology, Landscape, and Fidelity

> **Purpose.** How to *build* the clone with AI agents, what to *borrow* from existing systems, and how to *prove* the result matches DeepMind's. Covers the Claude-Code development harness, the competitive/open-source landscape (what to fork vs mine vs reject), deep-research engineering precedents, the "Science Superpowers" discipline, and the full fidelity-evaluation harness (9 categories, BRIDGE, M2M, phased build, testing). The *runtime* architecture is in file `03`; *fidelity invariants* originate in file `01`.
>
> Consolidates: `Agentic_Development_Harness_for_Co-Scientist_Clone.md`, `AI_Co-Scientist_Landscape_Analysis_and_Cloning_Guide.md`, `Engineering_Precedents_for_Agentic_Scientific_Discovery.md`, `Co-Scientist_Engineering_Blueprint_and_Fidelity_Evaluation.md` (fidelity portions), and the fidelity-harness sections of the architecture docs.

---

# Part I — Agentic Development Harness (building with Claude Code)

The project director's strategy is to delegate context-gathering, planning, and implementation to AI agents, intervening only at approval checkpoints. The build harness is **Claude Code** plus an MCP tool ecosystem.

## 1. Model orchestration & context engineering

- **Model aliases:** `opus` → Opus-class (architecture, safety, dependency routing); `sonnet` → Sonnet-class (high-speed code generation). The **`opusplan`** hybrid auto-routes **plan mode → Opus, execution mode → Sonnet**. (Concrete model names drift by provider — keep in config.)
- **Effort slider** `/effort {low|medium|high|xhigh|max}` — standard debugging at medium/high; complex coordination (tournament game-theory logic) at xhigh/max. **`ultracode`** combines max reasoning with background subagent parallelism.
- **Context commands:** `/plan` (planning state before a feature branch), `/btw` (ephemeral questions without bloating history), `/context` (visualize token distribution), `/compact` (summarize history), `/clear` (reset session, preserve `CLAUDE.md` memory).
- **Context budget model:**
$$T_{\text{context}} = T_{\text{history}} + \sum_{i=1}^{n} S_i + T_{\text{system}} + T_{\text{mcp}}$$
($T_{\text{system}}$ includes `CLAUDE.md`; $S_i$ = active skill footprints; $T_{\text{mcp}}$ = MCP tool definitions). On compaction, the CLI re-attaches up to the first **5,000 tokens per recently-invoked skill**, to a **25,000-token** total skill budget.

## 2. Full-stack implementation via MCP

- **Database** — Supabase + PostgreSQL MCP servers; `execute_sql` for schema/constraints. Protect the workspace with `read_only=true` (disables `apply_migration`/`deploy_edge_function`).
- **Frontend** — automated UI generation following the Material 3 design system (file `02`).
- **Testing** — Playwright MCP drives the app and verifies interactive UI behavior; CI/CD pipeline monitoring.

## 3. Reusable skills & deterministic hooks

- **Agent Skills** — multi-step procedures packaged as `.claude/skills/<name>/SKILL.md` with YAML frontmatter; full text loads only when triggered (progressive disclosure saves tokens vs always-on `CLAUDE.md`). Frontmatter controls: `disable-model-invocation` (require human timing for side-effecting ops like deploys/DB mutations), `user-invocable` (CLI `/` menu visibility), `allowed-tools` (pre-approve specific tool runs).
- **Lifecycle Hooks** — deterministic executables the CLI runs at lifecycle points, independent of LLM state:
  - `SessionStart` → `git fetch origin && git status` (branch alignment).
  - `UserPromptSubmit` → scan inputs for hardcoded secrets before transmission.
  - `PreToolUse` → strict interceptor; non-zero exit **blocks** destructive shell commands (`rm -rf /`, exfiltration) and returns a refusal to the model.
  - `PostToolUse` → auto-format/type-check modified files.

## 4. Parallel coordination

- **Hierarchical delegation** — a lead supervisor agent spawns specialized subagents with limited tools and focused context; outputs return to the supervisor for synthesis.
- **Flat peer-collaboration (Agent Teams)** — agents coordinate via a shared `TASKS.md` board (claim → lock with agent ID → execute), giving persistence (board survives crashes), transparency (humans read progress), and granular dependency mapping (`Blocked by ...`).
- **Worktree isolation** — `{"isolation": "worktree"}` creates a separate git worktree per parallel session, preventing file/commit collisions; torn down on merge.
- Optional command center (e.g. AgentsRoom) manages role-based templates with E2E-encrypted sync to mobile.

## 5. Security governance (defense-in-depth)

The **Read Tool Environment Bypass Vulnerability** (pre-2.1.128 Claude Code) is the cautionary case: `Bash` was sandboxed (Bubblewrap) but native `Read` ran in-process, so a prompt-injected paper could read `/proc/self/environ` and exfiltrate API keys via `WebFetch`/GitHub MCP. Exfiltration risk:
$$P(\text{exfiltrate}) = P(\text{inject}) \cdot P(\text{bypass}) \cdot P(\text{network})$$
Mitigations: disable bypass/auto modes in managed settings; `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` to strip credentials from subprocesses; containerize sessions (Devcontainers/VMs); read-only Postgres roles; short-term tokens / env-var expansion (`${ANTHROPIC_API_KEY}`), never plaintext keys in git. (This is *build-time* security; the *runtime* dual-agent CBRN safety layer is in file `06`.)

---

# Part II — Competitive Landscape & Open-Source Strategy

## 6. The major systems (comparative)

| System | Architecture | Multi-agent | Experimental validation | Notable for the clone |
|---|---|---|---|---|
| **DeepMind AI Co-Scientist** | 7 specialized agents | ✅ | ✅ (lab collabs) | the target; novelty + tournament + validation |
| **FutureHouse Robin** | 3 agents (Crow/Falcon/Finch) | ✅ | ✅ (lab-in-loop) | **PaperQA2** high-accuracy RAG |
| **Sakana AI Scientist v2** | BFTS tree-search pipeline | partial | simulated | tree search + Docker sandbox; ~42% error, weak novelty |
| **Elicit** | single-agent + tools | ✗ | ✗ | systematic-review automation |
| **Semantic Scholar** | search + AI ranking | ✗ | ✗ | massive DB + SPECTER embeddings |
| **Consensus** | single-agent synthesis | ✗ | ✗ | evidence-based synthesis |
| **Perplexity / ChatGPT / Gemini Deep Research** | single-agent + tools | ✗ | ✗ | deep web research; not science-specific; hallucinations |
| **Claude Research** | orchestrator-worker | ✅ | ✗ | multi-agent + CitationAgent pattern |
| **NotebookLM** | source-grounded single agent | ✗ | ✗ | grounding in user sources, audio overviews |
| **Drug-discovery platforms** (Insilico/BenevolentAI/Recursion) | varies | varies | ✅ (internal) | domain depth → real validation |

### Ten key patterns/lessons
1. Multi-agent architectures dominate advanced systems. 2. The **orchestrator-worker** pattern recurs (Claude Research + Co-Scientist). 3. **Lab-in-the-loop** (Co-Scientist, Robin) is safer/more practical than full autonomy (Sakana). 4. **Iterative refinement** is essential. 5. **Tournament/evolution** mechanisms improve quality. 6. Literature review is the foundation. 7. Domain specialization improves performance. 8. Biology/biomed dominates experimental validation. 9. Real experimental validation is the credibility gold standard. 10. Automated evaluation of scientific quality is **hard** (Sakana's reviewer rejected ~90% of human papers).

## 7. Open-source candidate evaluation (fork vs mine vs reject)

| Project | License | Architecture | Integration plan |
|---|---|---|---|
| **Jataware open-coscientist** (+viewer) | Source-available | LangGraph + LiteLLM, 8–10 agents, MCP PubMed, Elo tournament, React/TS viewer | **FORK PRIMARY** — core orchestration backbone + UI frame |
| **LLNL open-ai-co-scientist** | MIT | flat sequential Python, 6 agents, arXiv search, Elo K-factor loop, Gradio | **MINE** — agent prompt templates, Elo calculations, Gradio cost-control |
| **Sakana AI Scientist v2** | Apache-2.0 | Best-First Tree Search (AIDE), Semantic Scholar novelty, Docker | **MINE** — BFTS + Docker sandboxing |
| **FutureHouse Robin** | Apache-2.0 | Edison pipeline, PaperQA2 RAG, assay CSVs | **MINE** — PaperQA2 RAG pipeline |
| **OpenScientist (K-Dense)** | CC-BY-4.0 | Claude Code + KSDS, 140+ Agent Skills, 78+ DBs, sandboxed exec | **MINE** — DB connectors + Agent Skills templates |
| **aimclub CoScientist** | MIT | Google ADK + FEDOT.MAS, Marker PDF parsing | **MINE** — Marker PDF parsing + molecular utils |
| **The-Swarm-Corporation AI-CoScientist** | MIT | linear Gen→Reflect→Rank, basic web search | **INSPECT** — minimal agent-design reference only |
| **mims-harvard AutoScientists** | Source-available | decentralized self-organizing teams | **REJECT** — P2P approach unsuited to a central UI |

> **What "1:1 fidelity" actually means:** match every behavior the paper *specifies* (the invariants from file `01`); make reasonable, configurable, documented choices for what it leaves unspecified (K-factor, embedding model, termination predicates, context-memory schema). Lock the specified behaviors into automated tests; expose the rest as TOML/config.

---

# Part III — Engineering Precedents & Discipline

## 8. Deep-research precedents

| Platform | Coordination | Decomposition | State/recovery | Output |
|---|---|---|---|---|
| **OpenAI Deep Research** | central orchestrator + activity workers | 3–7 prioritized aspects, 3–5 queries each | Temporal persistence, cached replay, retries | narrative reports w/ inline citations |
| **Anthropic Q+** | think-tool-guided planners | dynamic query planning, long-snapshot extraction | session-level recovery, incremental caching | high-fidelity evidence syntheses |
| **Salesforce EDR** | hierarchical master planner | simple/complex classification → parallel tasks | enterprise DB persistence | business-intelligence reports |
| **OpenScientist** | Agent-Skills autonomous loop | fixed-iteration loop (default **N=10**) | document checkpointing | in-silico validation + PubMed digests |
| **AutoScientists** | self-organizing decentralized forum | hypotheses posted to a peer-review board | shared state, continuous mutation | optimized programs; $p^* = \arg\max_{p\in\mathcal{P}} \ell_{\text{eval}}(p;\mathcal{D})$ |

## 9. Output is for downstream agents, not just humans

A clone must collect/verify/synthesize primarily for **downstream AI agents**. When targeting agents (lab robotics, assay instruments, simulation models, code engines), priorities shift to **syntactic precision, machine-readable structure, rigorous metadata** — nested JSON/YAML/graph configs, not prose. Downstream systems like **AlphaEvolve** (optimizes codebases/GPU instructions/TPU layouts) and **ERA** (tree search over code to maximize a scorable empirical task) ingest these without parsing ambiguity. Every hypothesis compiles to a machine-readable schema (target proteins, binding-site coordinates, SMILES, quantitative parameters).

## 10. The "Science Superpowers" discipline (stateful skills)

Built on the MCP-tool-vs-stateful-skill distinction (file `03`), this framework enforces an **"Iron Law": no confirmatory scientific claim without an explicit, pre-registered prediction committed beforehand** — using Git commits as timestamped, frozen records before any data is loaded. Ten modular skills:

`framing-research-questions` · `surveying-prior-work` · `designing-the-analysis` · `preregistering-analysis` (writes hypotheses/designs/decision-rules to a Git-committed markdown baseline) · `setting-up-reproducible-analysis` (pinned deps, fixed seeds, immutable raw data) · `executing-analysis` / `subagent-driven-analysis` · `investigating-anomalous-results` (root-cause, never delete contradicting results) · `verifying-results-before-claiming` · `requesting-red-team-review` / `receiving-critical-review` (independent reviewer; address criticism with evidence, not performative agreement) · `reporting-and-archiving-findings`.

This prevents post-hoc data fitting and confirmation bias — directly reinforcing the Reflection/deep-verification behavior (files `04`/`05`).

---

# Part IV — Fidelity Evaluation Harness

> Evaluators must **avoid lexical-overlap metrics** (ROUGE/BLEU) that reward fluent-but-wrong text. Validate against reference benchmarks **Matter-to-Mechanism** (problem→hypothesis reasoning) and **BixBench** (computational biology).

## 11. The nine similarity dimensions

| # | Dimension | Protocol | Metric | Baseline |
|---|---|---|---|---|
| 1 | **Product Flow** | trace across standard/advanced runs | 8-stage state-transition alignment | **≥98%** match vs reference traces |
| 2 | **Terminology** | static analysis of logs/schemas/UI | nomenclature alignment ("hypothesis","research overview","tournament","NIH Specific Aims") | **100%** vocabulary compliance |
| 3 | **Report Structure** | structural audit of generated reports | component completeness (Ideas/Knowledge Base/Summary/Run Specs; disease/unmet-need/solutions/aims) | **100%** layout compliance |
| 4 | **Agent Behavior** | actions vs isolated test datasets | role-specific fidelity; all 4 Gen modes + 6 Reflection reviews + 6 Evolution strategies in a 30-min trace | **≥95%** adherence |
| 5 | **Tournament Behavior** | Elo vs human expert rankings | Spearman's $\rho$ between Elo and expert evals | **$\rho \ge 0.82$** on GPQA + expert sets |
| 6 | **Evidence & Citation** | claim-to-source auditing | citation faithfulness; ≥80% tier-2; zero unresolved in final report | **≥96%** accuracy, **zero hallucinated refs** |
| 7 | **Safety Behavior** | red-teaming adversarial prompts | safety recall on CBRN/hazardous | **100%** rejection; benign-biology false-positive ≤5% |
| 8 | **Progress & Latency** | parallel-run monitoring | task progression, fail-recovery, update accuracy | **zero deadlocks**, auto-recovery, updates **≤30s** (AG-UI ≤2s; checkpoint p95 <100ms) |
| 9 | **Final Output Quality** | human + LLM-judge consensus | scores (1–5) on reasoning fidelity, alignment, mechanistic specificity, novelty, plausibility, decomposition | **avg ≥4.2/5** on M2M + BixBench |

**Release threshold (open-source build):** each category scored 0–100; pass ≥80; overall release = 7/9 ≥80 and none <60. Gold-set hits: **AML ≥3/8** (Binimetinib, Pacritinib, KIRA6, Leflunomide…), **liver-fibrosis epigenetic target ≥1/3**.

## 12. BRIDGE — behavioral fidelity across dialogues

Evaluate multi-turn behavior, not just outputs. **Four deterministic gates** analyze execution logs first:
- **$G_1$ Epistemic** — factual claims grounded in literature (no hallucination).
- **$G_2$ Logical** — internal consistency, no contradictions.
- **$G_3$ Intent** — aligned with the research goal, no task drift.
- **$G_4$ Pragmatic** — formatting + correct reference integration.

Runs passing all gates are scored by a **calibrated probabilistic judge** across behavioral traits, mapped to {yes, ambiguous, no} via dual thresholds centered on human prevalence $P$ with half-width from interrater agreement $\kappa$:
$$T_{\text{upper}} = P + \tfrac{1-\kappa}{2}, \qquad T_{\text{lower}} = P - \tfrac{1-\kappa}{2}$$
Approve only if **all** relevant traits = "yes"; otherwise halt and escalate to human review. Traits → gates → remediation: **Cognitive Support**/$G_3$ (re-init scoping narrower); **Epistemic Honesty**/$G_1$ (halt, clear cache, re-run retrieval); **Strategic Adaptability**/$G_2$ (restart planning, add compute); **Divergent Curiosity**/$G_2$ (increase diversity); **Pragmatic Integrity**/$G_4$ (re-run synthesis with template).

## 13. Matter-to-Mechanism (M2M) — output quality

**2,645 expert-curated instances**, **reference-free** (because complex problems admit multiple valid solutions; grade against the input problem fields + internal scientific structure, not exact text match). Six dimensions: **(1) Logical Chain Fidelity** (problem→solution logic vs historical datasets/models); **(2) Problem Alignment** (intervention addresses the failure mode; vs disease/materials DBs); **(3) Mechanistic Specificity** (specific physical/chemical/biological interactions; vs UniProt/ChEMBL); **(4) Scientific Novelty** (vs literature DBs); **(5) Intervention Plausibility** (vs in-vitro assays / organoid studies); **(6) Problem Decomposition Quality** (analyze the planning agent's execution graph).

## 14. Phased build sequence & acceptance gates

| Phase | Weeks | Deliverables | Acceptance |
|---|---|---|---|
| **1 Foundations** | 1–2 | docker-compose (pg+pgvector, redis, api, worker); Alembic V1+V2; FastAPI `/runs` CRUD; Celery + dummy LangGraph; PostgresSaver; LLM router (opus/sonnet/opusplan); LangSmith | `POST /runs` returns id; ≥3 trace rows; kill-worker resume with **zero duplicates** |
| **2 Retrieval** | 3 | MCP client + PubMed/Europe PMC/ChEMBL/UniProt; hybrid search (RRF k=60); Citation Verification 3 tiers | AML test: ≥80% cited works reach tier-2; ≥50% tier-3 |
| **3 Core Loop** ★ | 4–6 | Generation (4 modes), Reflection (6 reviews), Proximity (kNN), Ranking (annealed K, init 1200, pairing policy), Evolution (6 strategies, new-only), Meta-Review (critique injection), Supervisor termination, Safety dual-agent | AML run ≤30 min @ \$5 budget; ≥10 hypotheses; **≥3 named candidates** in top-10; meta-critique changes next Gen prompt (snapshot diff) |
| **4 Tournament/UI** | 7–8 | React+Tailwind+CopilotKit; NewRun/RunDashboard/Report pages; AG-UI event mapping; SSE fallback | hypothesis cards appear ≤2s after DB insert; Elo ticks live |
| **5 Report/Fidelity** | 9–10 | NIH Specific Aims renderer; suggested-contacts; `eval_runner.py` (9-cat scorecard); `bench.py` (cross-model Elo) | fidelity scorecard ≥80% per category on AML/liver-fibrosis/cf-PICI |

## 15. Testing strategy

| Layer | Tooling | Examples |
|---|---|---|
| Unit (pure fns) | pytest + hypothesis | `elo.py` idempotence/monotonicity/K-decay; pairing invariants |
| Unit (agents) | pytest + VCR cassettes; snapshot | per-agent fixture→output schema + invariants |
| Prompt snapshot | syrupy | rendered Jinja prompts hashed; PR fails if a prompt changes without fidelity review |
| Integration | pytest + testcontainers (pg, redis) | full `intake→…→report` on 60s budget; resume-from-checkpoint |
| Retrieval | live MCP (`RUN_LIVE_MCP=1`) | PubMed rate limiting, Europe PMC, ChEMBL, UniProt |
| Safety | WMDP + FORTRESS-subset probes | dual-agent blocks all CBRN-uplift; benign-biology FP ≤5% |
| Fidelity | `eval_runner.py` | the 9-category rubric |
| Load | Locust | 50 concurrent runs; checkpoint write p95 <100ms |

The single most important behavioral test:
```python
def test_evolution_never_modifies_existing():
    state = seed_state_with_top_hypotheses(n=5)
    new_state = evolution_agent(state, strategy="combination")
    assert all(h.id not in {x.id for x in state.hypotheses} for h in new_state.hypotheses[-2:])
    assert len(new_state.hypotheses[-1].parent_ids) >= 2
```

## 16. Automated multi-agent bootstrapping (the build pipeline)

The director deploys a three-step agent pipeline, intervening only at checkpoints:
1. **Context gathering** (research agents) — crawl the paper (Gottweis et al.), ADK/Temporal/LangGraph docs → a high-density Context Repository (code patterns, schemas, API configs).
2. **Technical planning** (planning agents) — emit structured Markdown specs: LangGraph StateGraph schemas, Temporal workflow defs, SQL session-persistence schemas, OpenAPI definitions.
3. **Implementation + testing** (coding agents) — build state layers, Elo brackets, UI panels; an Evaluator agent runs tests + Playwright checks, feeding tracebacks back until **100% compile + test pass**.

This maps directly onto the Claude-Code harness (Part I) and lets the director manage the build with minimal manual oversight while still hitting the fidelity bar.

---

## 17. The fidelity bottom line

A clone is faithful when it reproduces the three behaviors the paper specifies and the broader corpus repeatedly flags (file `01` §12):
1. **Elo init = 1200**; multi-turn debate for top-ranked, single-turn for lower-ranked.
2. **Evolution generates new hypotheses, never modifies existing ones** (test §15).
3. **Meta-review critique is appended to every other agent's prompt next iteration** (snapshot-diff test, Phase 3).

Everything else is configurable — but these three, plus the 9-category harness ≥80%, are the line between a 1:1 clone and a generic multi-agent RAG system.
