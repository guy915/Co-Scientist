# Science skills inside Co-Scientist — stage 1 scoping

Status: **stage 1 (scoping)**. This file frames the problem and lists the
decisions the stage-2 plan must resolve. It is deliberately not an
implementation plan.

Reading order: this file, then [`MANIFEST.md`](MANIFEST.md) for what the bundle
contains and what of it we already have, then
[`_analysis/science-skills.md`](_analysis/science-skills.md) for the mechanism
and the measured claims.

## What we are actually building

**Not** a skills marketplace, and not 34 database integrations. The bundle's
own report is explicit that coverage is a starting point rather than a map, and
this repository's own rule from 2026-06-21 still binds: *Co-Scientist is the
main character* — we want grounding breadth that serves hypothesis generation.

What we are building is the answer to a narrower question the repository keeps
running into: **a run's grounding is bounded by the sources it can reach, and
adding a source currently costs an MCP tool, a YAML entry and workflow wiring
per source.** That per-source cost is why the 2026-06-21 grounding roadmap has
moved by three entries in fourteen months, and why a systems-biology run cannot
reach a pathway, a variant-consequence, or a population-frequency database at
all.

Two halves, decided:

1. **A skill mechanism** — a catalogue the agent routes on, a document it loads
   on demand, and a script it runs in the existing confined workspace. This is
   what makes the *next* source cost prose rather than engineering, and it is
   the only way the operational judgement in a `SKILL.md` reaches a model at
   all (see `_analysis`, "what the prose carries").
2. **A small number of first-class MCP tools** for sources every run should
   have by default, following the OpenAlex/ChEMBL/UniProt pattern already in
   the tree.

## Why the recorded decision is now open

`docs/decisions/2026-06-21-science-grounding-sources.md` (Accepted) examined
this same bundle and declined to port it, on two independent legs. **Leg 1 —
"the format is not portable: prose plus `uv`-run CLIs with file-based JSON I/O
and no typed tool manifest"— no longer holds.** Between then and now the
coding-harness work landed:

- `workspace/tools.py` serves six local tools (`run_command`, `poll_command`,
  `read_file`, `write_file`, `list_files`, `apply_patch`) and already takes the
  `MCPToolProvider` as a delegate, so local and MCP tools reach the model as
  one surface.
- `sandbox/` confines every command, with `policy.py` carrying a
  `network_allowed` field and backends for macOS seatbelt, bubblewrap, and an
  unprivileged Landlock+seccomp path for containers.
- `llm_tool_loop.py` drives bounded tool loops with budget escalation, transcript
  elision, and partial-answer harvesting.
- `agents/reflection/simulation_execution.py` is a production caller of all of
  it.

A `uv run` CLI that writes JSON to a file is now an ordinary thing this engine
executes. **Leg 2 still holds** and remains the filter on everything.

Any stage-2 plan amends that ADR explicitly. It is Accepted, and this
repository does not work quietly against a recorded decision.

## Why this is not a bolt-on, and not a rewrite either

The host already has the substrate; what it does not have is any notion of a
skill. There is no registry, no loader, and nothing an agent selects at
runtime. The four things that come closest are all fixed at config time:
prompt templates (`prompts/templates/*.md`), five domain-guidance strings
(`PromptsConfig`), domain packs (`config/examples/*.yaml`), and per-tool
`prompt_snippet` blurbs in `tools.yaml`.

The nearest *behavioural* precedent is audience context (`app/app/audience.py`,
`content/sbi_ucd_context.md`) — the group's methods and assays injected into
twelve agent modules — and its history is the warning this design has to answer.
It was originally two-tier: a short profile everywhere, the long reference
loaded when needed. That split was **reversed**; the full ~19k-token document
now ships verbatim on every call. Progressive disclosure has been tried here
once and abandoned once, and a plan that reintroduces it owes an account of why
this time differs.

## Settled

Three of the decisions below are answered and no longer open:

- **The consumer is the autonomous run.** Skills reach the engine's tool loops
  — draft generation, the research loop, the deep reviews — not the chat or
  interview surface. Grounding is what we are buying, and the report's
  reliability result is the one that translates.
- **The bundle is vendored as-is**, upstream directories and scripts intact,
  bringing `uv` and `scienceskillscommon` with it. This settles decision 2 in
  favour of breadth over house style, and makes the vendored tree a standing
  exception to the repo's lint, type and file-length gates — that exception is
  explicit and scoped, not silent.
- **Keyed sources are in scope.** AlphaGenome is included from the start.
  NCBI/Entrez is already keyed on both the local and production MCP server, so
  ClinVar, dbSNP and the E-utilities skills inherit usable rate limits with no
  new configuration.

## Measured: skills on vs off, through the real simulation review

Three mechanisms, `deepseek-v4-flash` via OpenRouter, 2026-08-22, run three
times — as first wired, after removing the two overheads below, and after
moving retrieval to *after* the model's first run. 18 runs, 9 per arm.

| Round | Change under test | Baseline | Skills |
| --- | --- | --- | --- |
| 1 | as first wired | 3/3 | 2/3 |
| 2 | catalogue trimmed, licence toll seeded | 3/3 | 2/3 |
| 3 | retrieval moved after the first run | 3/3 | **3/3** |

Round 3 recovered reliability, and the reason is the finding. Split the skills
arm by whether the reviewer *actually engaged a skill*:

| | Runs | Produced an observation | Mean length |
| --- | --- | --- | --- |
| Baseline, no skills offered | 9 | **9/9** | 4,771 chars |
| Skills offered and **ignored** | 2 | 2/2 | 4,295 chars |
| Skills offered and **used** | 7 | 5/7 | 2,839 chars |

**Every time this reviewer engages a skill, its observation gets worse.** Two
of seven skill-engaged runs beat the baseline mean; two produced nothing at
all; the rest were stubs of 111 to 411 characters. The two runs that ignored
the skills entirely landed back at baseline. Round 3 did not fix the
integration — it made the model largely stop using it, and quality returned.

Three explanations were tested and rejected in order: budget (raising it
changed nothing), overhead (removing both changed nothing), and prompt
ordering (fixing it recovered reliability only by suppressing skill use).
What remains is a role conflict. The simulation review exists to build a model
of a mechanism and run it; retrieval competes with that job rather than
supporting it, and a reviewer that spends its turns querying databases has
nothing to report. Note the time column across every round: skill-engaged runs
are consistently *faster* than baseline while producing less. They are not
running out of room — they finish early with nothing to say.

**So the first consumer was the wrong one**, chosen because it already owned a
confined workspace and a bounded tool loop: convenience, not fit. Skills stay
**inert** — the api image ships the bundle and the interpreter but does not set
`COSCIENTIST_SKILLS_DIR`, the single gate the engine reads. The mechanism
measured sound and is reusable unchanged; the next integration belongs where
looking something up *is* the task: the literature review's research loop, or
draft generation.

The round-3 prompt ordering is kept regardless. Retrieval as a refinement of a
result rather than a precondition for one is the better instruction with or
without skills, and the baseline arm was unharmed by it (4,771 mean across all
rounds).

### The two overheads, removed regardless

Both were real, both are fixed, and both would have bitten any consumer:

1. **The catalogue was a per-turn tax.** 38 full descriptions re-sent on every
   turn of the loop — measured at ~2.4k tokens a turn, more than every tool
   result in the loop put together (17k chars across ten calls). Trimmed to
   routing sentences: 12,079 to 5,155 chars, 57% off every turn.
2. **35 of the 38 skills demand a licence notice before they will work.** Each
   requires `.licenses/<skill>_LICENSE.txt` to exist in the workspace root, and
   every review opens a fresh workspace, so it never pre-existed: the model
   paid `ls`, `mkdir`, `pwd` and `write_file` — four turns of fourteen — on
   first use of every skill. `skills/licences.py` seeds them at workspace open,
   which is also the more faithful reading of the obligation, since the harness
   writes the notice every time and a model writes it when it remembers.

Neither trades quality for cost; both give turns back. That they did not change
the outcome is what rules out the budget explanation.

### Still open

The licence obligation is *not* discharged by a file in a workspace that is
deleted — that reaches nobody. The duty is to tell a human, which means the
run's report. `skills.notified_sources()` exists for that surface; the report
plumbing does not.

## Decisions stage 2 must resolve

1. **Where the catalogue is injected, and how big it is.** 34 name+description
   pairs is on the order of 3–4k tokens. Which callers see it — the
   `draft_generation` tool loop only, or also the research loop and the deep
   reviews — and whether it is filtered by run focus rather than sent whole.
2. ~~What vendoring costs, now that it is chosen.~~ **Mostly done.** The tree
   lives at `vendor/science-skills/`, pinned to upstream v1.1.0. No gate
   exclusions were needed: `make lint` and `make typecheck` only ever run
   inside `engine/`, `app/` and `evaluations/`, and the source-hygiene gates
   walk an allowlist (`evaluations/tests/_source_tree.py::SOURCE_DIRS`), so a
   top-level directory is outside all of them by construction. The one thing
   that *did* need config is a root `.ruff.toml` excluding `vendor/` and
   `references/`, because a hand-run root-level `ruff format` had already
   rewritten 63 vendored files once. Still open: Apache-2.0 attribution in the
   root `NOTICE`.
3. ~~Network inside the sandbox, on the deploy host.~~ **Resolved, and the
   original worry was backwards.** Every backend implements the network as a
   *denial* applied only when the policy withholds it: seatbelt appends
   `(allow network-outbound)` when permitted, bwrap adds `--unshare-net` only
   when not, and on the Landlock+seccomp path `confine_exec` calls
   `seccomp.deny_network()` only when `allows_network` is false — so with it
   true, no filter is installed at all. The UDP/DNS gap seccomp exists to
   close is a gap in *denying* the network, not in allowing it. Measured
   locally through the real `WorkspaceSession`: `network_allowed=True` returns
   HTTP 200 from `rest.uniprot.org` inside the sandbox, `False` fails to
   connect. Production reports `code_execution_available: true`, and the
   container plainly has egress since it already calls PubMed and the model
   provider. The plumbing is threaded end to end — `open_run_workspace`,
   `open_review_workspace`, `open_variant_workspace` and
   `build_workspace_tools` all take `network_allowed`, defaulting to false,
   and **no production caller passes true today**. Enabling it is a call-site
   argument, not a sandbox change.
4. **The offline branch.** CI is hermetic: no network, no keys. Skill
   execution needs a deterministic refusal or replay path, following the
   existing sandbox-refusal and `offline_llm` patterns. Note the shape the
   image already forces: the dependency closure is resolved at build time
   into `/app/skills-venv` and nothing resolves packages at runtime, so the
   only thing a hermetic environment lacks is the *API* call — which is the
   part the refusal path has to cover.
5. **Which sources become first-class tools**, ordered by what this
   deployment's audience needs — systems-biology runs against the SBI corpus —
   rather than by the 2026-06-21 roadmap's original ordering.
6. **How a skill is gated per run.** Every other source obeys `disable_tools`
   and the audience/connector toggles (`app/app/engine_adapter/opts.py`). A
   skill surface that sits beside that model rather than inside it is a
   second gate to keep in step, and the one that gets forgotten is the one
   that leaks.
7. **Whether `paper_corpus_fetch` and the group's papers become a skill.** The
   bundle's meta-skill exists to turn a lab's own workflow into a reusable
   skill; this lab's methods document is already written and already injected.

## Host constraints any design must respect

Each is a documented past outage or data-loss bug — see `AGENTS.md` "Gotchas".

1. **Per-item LLM or tool passes multiply.** A per-candidate relevance pass
   added to a shared helper, times three per-hypothesis callers, is this
   repo's 299-call incident. Before a skill surface reaches a shared seam,
   count every caller's multiplicity.
2. **A tool loop re-sends its whole transcript every turn.** A skill that
   dumps a large JSON payload into the transcript is re-bought on every
   subsequent turn. The bundle's own rule 2 — file output, then query the
   file — is the correct shape and matches `workspace/output.py`.
3. **One SQLite writer, never held across network I/O.**
4. **No process-global asyncio primitives.** Each run cohort has its own loop.
5. **Only `UnsupportedTaskError` is a permanent task failure.** A skill that
   raises on a failed API call burns the retry budget and strands the run;
   failures are returned as results.
6. **Fidelity finding G13 is a recorded refusal, not an oversight.**
   AlphaFold-class structure retrieval was deliberately excluded, with the
   rationale written into `config/tools.yaml` and
   `docs/fidelity-audit/FINDINGS.md`. If it lands, both are consciously
   superseded.
