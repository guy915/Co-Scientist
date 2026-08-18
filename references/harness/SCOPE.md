# Execution harness inside Co-Scientist — stage 1 scoping

Status: **stage 1 (data collection)**. This file frames the problem and lists
the decisions the stage-2 plan must resolve. It is deliberately not an
implementation plan — the architectural calls depend on the `_analysis/`
write-ups still in flight.

## What we are actually building

Two capabilities that are easy to conflate and should not be:

**A. A code-execution tool surface** — the agent gets a terminal: run a
command, read/write/edit files, install packages, inspect results, iterate.
This is the Claude-Code / OpenCode / Codex shape. It serves *ad-hoc*
work: sanity-check an assumption, plot a distribution, run a statistical test
a reviewer asked for.

**B. A Computational Discovery loop** — an optimization task + a baseline
program + a scoring function + a dataset, evolved over hundreds of executed
variants with parent-child lineage and a best-score-so-far curve. This is the
AlphaEvolve / OpenEvolve shape, and it is what the Google surface in
`references/core/google-co-scientist/media/computational-discovery/` actually
shows.

B is built **on top of** A — the evolution loop needs a sandbox to execute
candidates in — but B is not a natural consequence of A, and shipping A does
not get you B. Conflating them is the main scoping risk here.

## Why this is not a bolt-on

The host already runs a generate → review → rank → evolve loop with append-only
lineage, an Elo tournament, and a durable leased-task queue. Capability B is
*the same loop with a different fitness function*: instead of an LLM debate
judging two hypotheses, a deterministic metric scores executed code on held-out
data. That is a much better starting position than it looks — but it also means
the biggest design question is a reuse question, not a build question.

Four host constraints that any design must respect (each is a documented past
outage or data-loss bug — see `AGENTS.md` "Gotchas"):

1. **One SQLite writer.** Variant scores, artifacts, and lineage rows all land
   in the same single-writer store. A loop producing 300 variants writes a lot.
2. **Never hold the write lock across I/O.** Executing a candidate program is
   unbounded blocking I/O. The assess-then-persist split used by
   `claim_grounding.py` / `engine_adapter/drain.py` is the pattern to copy.
3. **Durable tasks are leased, idempotent, and restartable.** A variant
   evaluation must be a task row like any other, or a restart mid-run strands
   it. Attempts are capped at 3 and only `UnsupportedTaskError` is permanent.
4. **Startup work runs before the port binds.** Nothing in this subsystem may
   make boot slower or fallible.

## Decisions the stage-2 plan must resolve

| # | Decision | Why it is contested |
| --- | --- | --- |
| D1 | **Sandbox substrate** — OS primitives (seatbelt/Landlock/seccomp), containers (Docker), a microVM, or a hosted sandbox service | Determines the security ceiling, the local-dev story, and whether prod on Railway can run it at all. The host is currently a single container with a mounted volume. |
| D2 | **In-process vs out-of-process** — does the coding agent run inside the existing worker cohort, or as a separate service? | Cohorts already run one event loop per thread; no process-global asyncio primitives. A long-lived sandbox per run has a lifecycle the task queue does not currently model. |
| D3 | **Reuse the evolve/rank machinery, or build a parallel subsystem?** | The host's lineage + tournament is close to what B needs, but its selection is Elo-from-debate, not score-from-execution. Generalizing it risks destabilizing the shipping hypothesis path. |
| D4 | **File-edit representation** — diff/patch blocks vs whole-file rewrite vs delimited evolve-blocks | Drives token cost per variant, failure modes, and whether variant N+1 is diffable against its parent for the lineage view. |
| D5 | **Tool exposure route** — native engine tools, or an MCP server the agent already knows how to call? | The host already has an MCP client and a reference MCP server. An MCP sandbox server is the cheapest seam; it may also be the wrong one for latency and for streaming output. |
| D6 | **Where does data live?** The Google surface has a 200 GB source library shared across runs. | The host's volume is small and deliberately holds only the SQLite DB. Datasets are a new storage class. |
| D7 | **Trust boundary for agent-authored code** | Today no untrusted code executes anywhere in this system. This is the single largest change to its threat model, and the survey in `references/peripheral/coding-agent-harness/` flags policy-grade safe tool use as the gap nobody fills. |
| D8 | **Scope of v1** — capability A only, B only, or a thin slice of both? | A alone is useful and much cheaper. B alone is the actual parity gap. |

## What is settled

- **Ground truth changed.** The published papers describe tool use as web
  search, domain databases, a private publication index, and specialized models
  like AlphaFold — no code execution (`towards-an-ai-co-scientist.md` §3.5), and
  the paper explicitly contrasts itself with systems that execute code. Per
  direct conversation with the team, the current system does have these
  capabilities; the papers are treated as outdated on this point. The
  Computational Discovery captures corroborate it.
- **`docs/FIDELITY.md:93` needs revising** once the plan lands — it currently
  records Computational Discovery as an accepted divergence, which is no longer
  the intent.
- **Sources are permissively licensed except Pi Agent** — see `MANIFEST.md`.
- **No leaked proprietary source enters this repo.** Not as reference, not as
  a port target.
