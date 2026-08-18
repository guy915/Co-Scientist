# Execution harness inside Co-Scientist — stage-2 plan

Supersedes the open questions in `SCOPE.md`. Grounded in the four teardowns in
`_analysis/`, and in claims re-verified against this repo (noted inline).

---

## Build status (2026-08-18)

Phase 0 and Phase 1 are complete; Phase 2 is partly built. Everything below
ships with tests, and where a test could pass against a broken implementation
the mutation was run to confirm it fails against one.

| Item | Phase | State | Where |
| --- | --- | --- | --- |
| Effect-typed tools + contiguous batching | 0 | **done** | `tool_effects.py`, `llm_tool_loop.py` |
| Iteration soft-handoff | 0 | **done** | `llm_tool_loop.py` |
| Interrupted-turn normalizer | 0 | **not built, deliberately** | see below |
| `SandboxPolicy` + `wrap_argv` | 1 | **done, macOS verified** | `sandbox/policy.py`, `sandbox/argv.py`, `sandbox/seatbelt.py` |
| bubblewrap backend | 1 | **done, Linux verified** | `sandbox/bwrap.py`, `make test-sandbox-linux` |
| `run_sandboxed` + real SIGKILL | 1 | **done** | `sandbox/runner.py` |
| Resource/pid limits | 1 | **out of scope by design** | container's job; see §3 |
| Trusted-command classifier | 2 | **done** | `sandbox/command_safety.py` |
| `apply_patch` V4A | 2 | **done** | `patch/` |
| Workspace session | 2 | **done** | `workspace/session.py` |
| Shadow-git snapshots | 2 | **done** | `workspace/snapshot.py` |
| Output redaction + spillover | 2 | **done** | `workspace/output.py` |
| Post-edit checks fed back | 2 | **done, parse checks only** | `workspace/checks.py` — a linter is absent from the prod image; see below |
| Long-running commands as sessions | 2 | not built | needs the app's durable task layer |
| Per-run session construction | 2 | **done** | `workspace/run_workspace.py` |
| Production exec topology | 1 | **open, and now the blocker** | see below |
| Tool registration (D5) | 2 | **done** | `workspace/tools.py` |
| Everything in Phase 3 and Phase 4 | 3, 4 | not built | |

### Three things to know before picking this up

**1. The agent can now reach the tools; nothing constructs a session yet.**
D5 is resolved as a local tool kind rather than a local MCP server:
`workspace/tools.py` declares `run_command`, `apply_patch`, `read_file` and
`list_files`, and `tool_effects.resolve_tool_effects` consults local
declarations before the MCP registry. `WorkspaceToolProvider` delegates every
other name to the run's `MCPToolProvider`, so the model sees one tool surface.
The MCP route was rejected on its timeout: `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS`
would bound the tool call and the command with one number, making a long
analysis and a hung provider the same event. What remains is the call site —
something has to build a `WorkspaceSession` per run and pass the provider into
a `ToolLoop`.

Two traps this area sets, both of which pass silently:

- *Effects.* Asserting `run_command` is a barrier proves nothing, because an
  unregistered tool is a barrier too. Only a local tool that **reads** can tell
  whether the declarations are consulted at all — hence
  `test_read_file_batches_with_sibling_reads`.
- *Caching.* `call_llm_with_tools` caches whole transcripts, tool results
  included. Replaying one that contains a `run_command` result hands the model
  output from another run's directory as though it had just executed there:
  plausible, correctly shaped, and describing files that do not exist.
  `_guard_cache_for_local_tools` disables the cache structurally rather than
  leaving it to each call site, because forgetting produces fabricated evidence
  rather than a crash.

**2. Linux confinement is verified; the production topology is not.**
`make test-sandbox-linux` builds a bubblewrap image and runs the escape tests
there (91 passed). It found five real faults macOS could not show, one of them
an actual escape: `--tmpfs /tmp` made every workspace under `/tmp` writable
while simultaneously masking the real `/tmp` from read-only sandboxes. It also
found that `.git` protection had no bwrap implementation at all.

The harness refuses to run without `--privileged`, and that is the finding.
Bubblewrap cannot create a namespace under a normal container profile —
`seccomp=unconfined`, `apparmor=unconfined` and `cap-add SYS_ADMIN` were each
tried and each failed. So bwrap inside the api container is very likely not
viable on Railway, and the production answer is `SandboxKind.EXTERNAL` with a
dedicated exec container, which is where F3 pointed anyway. Today production
fails closed: `Dockerfile.api` has no bwrap, `sandbox_backend()` returns None,
and `workspace_tool_schemas` withholds `run_command` rather than offering a
tool every call would refuse.

The preflight exists because this class of failure passes. A probe reported
`OUTSIDE: denied (good)` while bwrap had never started — a suite can report
green while confining nothing.

The same shape then produced a second Linux-only escape, worth stating because
it is the one a reviewer will re-derive. `--ro-bind-try` **skips a path that
does not exist**, so on a fresh workspace `.cosci` was ordinary writable space
and the first confined command could replace it with a symlink; the spill then
ran in the *host* process, outside the sandbox, writing command-influenced
bytes into a command-chosen directory. Seatbelt's deny rule matches a path
whether or not it exists, so macOS could not show it. `WorkspaceSession` now
creates the directory up front and `OutputRecorder._spill` refuses a target
resolving outside the root — before the `mkdir`, since creating a directory and
then declining to write into it still lets a command make the host `mkdir`
wherever it likes. **A read-only bind protects a path that exists.**

**3. The normalizer was skipped on evidence, not forgotten.** Codex needs it
because it resumes mid-turn; this host restarts the whole task. Verified:
`message_history` is written only on success and read only on a cache hit, and
nothing reconstructs a partial tool transcript. It becomes necessary with
start-then-poll long-running commands, and belongs in that change where it can
be tested against a real interrupted command.

### One defect worth remembering

Writable roots were not resolved before reaching seatbelt. On macOS `/var` is a
symlink, so a granted directory came back *unwritable* — it fails closed, so it
reads as a broken sandbox rather than as a path bug. Every argv-shape test
passed throughout, including one named `test_write_inside_a_writable_root_
succeeds`, which passed only because pytest's `tmp_path` arrives already
resolved. It was caught by running commands by hand with `tempfile.mkdtemp()`.

The lesson generalizes to the whole area, and the teardowns kept saying it:
**a sandbox's tests must try to escape it.** Shape assertions confirm shape.

---

## 1. What the four sources actually settled

Five findings converged hard enough to treat as decided.

**F1 — Nobody has a sandbox except Codex.** OpenEvolve `exec`s candidate code
in-process. Pi's `bash` is `/bin/bash -c` with the full inherited environment
and no path scoping. opencode's `SECURITY.md` states outright that it does not
sandbox the agent and lists sandbox escapes as out of scope. OpenHands ships a
container but sets no `--memory`, `--cpus`, `--pids-limit`, `--read-only` or
`--cap-drop`, and defaults to full outbound network. **The execution boundary
is net-new work with one reference implementation, and we should stop looking
for a second.**

**F2 — Codex's confinement ports to Python unchanged, because it lives in the
argv.** `SandboxPolicy` is a serialized value object; enforcement is a transform
producing `sandbox-exec -p <SBPL> -D… -- cmd` on macOS or
`bwrap --unshare-user --unshare-pid --unshare-net --cap-drop ALL -- cmd` on
Linux. Nothing about that is Rust. The SBPL policy files are Apache-2.0 data and
copyable verbatim — they encode months of debugging we do not want to repeat.

**F3 — Execution must be out of process, for reasons that predate this work.**
The api service runs at exactly one replica because the store is single-writer
SQLite. Code execution is the most obvious reason anyone would want to scale
out and the one thing that cannot be, without a store migration. So the exec
workload leaves the serving process *before* it is even sandboxed — the process
boundary and the security boundary happen to be the same line.

**F4 — Start-then-poll-with-cursor makes long commands restartable.**
OpenHands' `POST start_bash_command → {id}`, then
`GET bash_events/search?order__gt=N`. Persist `command_id` + cursor on the
durable task row and a restarted worker *re-attaches* to a still-running command
instead of re-issuing it. This is the single design choice that reconciles
"a 40-minute simulation" with "workers get killed by lease expiry, `--reload`,
and healthchecks." It also sidesteps OpenHands' own at-least-once hazard, which
we are otherwise not copying.

**F5 — For Computational Discovery: generalize the plumbing, not the agents.**
Our durable queue, append-only-lineage/mutable-state table pair, checkpoints,
event log, ownership middleware and run-tab shell carry code variants unchanged.
Our evolve/rank/proximity agents must not be stretched to cover them — three
axes break: selection signal (LLM-debate Elo vs deterministic executed metric),
diversity policy (our gates *delete* near-duplicates; MAP-Elites deliberately
*keeps* low-fitness niche occupants), and execution (we have none).

## 2. Two claims re-verified in this repo

Both underpin phases below, so I checked them rather than trusting the reports.

- **`_execute_tool_calls` gathers every tool call unconditionally**
  (`engine/src/co_scientist/llm_tool_loop.py:167`). Confirmed — the body is a
  bare `asyncio.gather` over all calls. Harmless while every tool is read-only
  MCP literature search; a latent correctness bug the moment one tool writes a
  file or spawns a process.
- **No code-execution infrastructure exists.** A repo-wide grep for
  `subprocess|Popen|os.system|runpy|docker|sandbox` across `engine/src` and
  `app/app` returns exactly one real hit: the fixed document converter at
  `app/app/document_ingest.py:255`. Everything else is `re.compile` or
  `StateGraph.compile()`.

## 3. Phasing

Phases 0–2 are common to both capabilities. Phase 3 is the Computational
Discovery half and is the part the D8 scope call governs.

### Phase 0 — Make the tool loop safe to put an exec tool into

**Must land before any exec tool exists.** Small now, a rewrite later.

| Item | Source | Notes |
|---|---|---|
| Effect-typed tool declarations | Pi | Every tool declares `READ\|WRITE\|APPEND\|NETWORK\|PROCESS`; `BARRIER = WRITE\|APPEND\|PROCESS`. Add an `effects` field to `config/tools.yaml`. |
| Contiguous compatible-effect batching | Pi | Group before `gather`; re-sort results into model-emitted order so transcripts stay deterministic. |
| **Fail-closed default** | Pi | An undeclared tool defaults to `write` (serial). Getting this default wrong re-creates the exact bug being prevented. |
| Interrupted-turn normalizer | Codex | Synthesize an `aborted` result for any tool call missing its result, delete orphan outputs. We restart workers mid-task *by design*, so a half-written tool exchange is the normal resume state; without this the provider rejects the rebuilt conversation and it reads as a model error. |
| Iteration soft-handoff | Pi | Inject a one-shot user-role message at 80% of `max_iterations` instead of raising at 100% (`llm_tool_loop.py:355`). "Handoff" here means writing a partial result to `scientific_tasks.result_json`. |

One effect vocabulary then drives three enforcement points: parallelism,
plan-mode gating, and approvals.

### Phase 1 — The execution service

The piece with no reference implementation. A separate container, no DB and no
provider credentials, `env_clear()` plus an explicit allowlist.

Contract: `(code, dataset_ref, evaluator_spec) → {metrics, artifacts, status}`.

| Item | Source | Notes |
|---|---|---|
| `SandboxPolicy` value object + `wrap_argv()` transform | Codex | Frozen dataclass; one backend function per platform. `DangerFullAccess` and `ExternalSandbox` as the two escape hatches. |
| SBPL policy files | Codex | Copy verbatim (Apache-2.0 data). |
| `-D` parameter substitution | Codex | Never interpolate paths into policy text. |
| Pin `/usr/bin/sandbox-exec` | Codex | Do not resolve via `PATH`. |
| Force `.git` read-only inside writable roots | Codex | |
| **Fail closed on unsupported platform** | Codex | Their agent path fails *open* (silently degrades to no sandbox); their CLI hard-fails. Take the CLI's behavior. |
| Runtime hygiene | Codex | `PR_SET_DUMPABLE=0`, scrub `LD_*`/`DYLD_*`, `RLIMIT_CORE=0`. |
| Real `SIGKILL` on timeout | OpenEvolve (as anti-pattern) | Their `asyncio.wait_for` over a thread-pool executor **cannot kill** a runaway candidate. Their `memory_limit_mb`/`cpu_limit` are config fields carrying the comment "not implemented". |
| Resource + egress limits | — | `--memory`, `--cpus`, `--pids-limit`, deny-by-default network. Nobody we studied does this; it is cheap and not optional. |

**Four host rules a naive implementation violates immediately** (each is a
documented past incident in `AGENTS.md`):

1. Never hold the SQLite write lock across the subprocess call. Structure it as
   `claim_grounding.py` does provider work: claim → release → execute → re-open
   a transaction to persist.
2. Never write on a poll tick. Stream output to memory/tmp, persist on
   completion or a bounded schedule. `task_worker.py`'s heartbeat is the model.
3. No process-global asyncio primitives. Each cohort runs `asyncio.run` on its
   own thread, so a module-level `Semaphore` bounding concurrent subprocesses
   binds to the first loop and raises from every other — the exact failure that
   killed a production ranking task.
4. Sandbox warm-up must not be awaited in the lifespan hook, or every deploy
   fails its healthcheck and each retry starts further behind.

Also: multi-megabyte outputs go to the off-volume tmp path with only a pointer +
digest in SQLite. `checkpoints` already reached 97% of the production DB once,
and `_reclaim_disk_space()` cannot VACUUM.

### Phase 2 — The terminal tool surface (capability A)

| Item | Source | Notes |
|---|---|---|
| Start-then-poll-with-cursor | OpenHands | F4. The durable task row holds `command_id` + cursor. |
| PS1-JSON sentinel | OpenHands | The shell's own prompt emits `{exit_code, pid, cwd, py_interpreter_path}` as JSON between markers, recovered from a pane capture. Survives `cd` and venv activation with no wrapper process. ~100 lines, zero coupling. |
| Long-running commands as sessions | Codex + OpenHands | `yield_time_ms`/`write_stdin`; `is_input` + control keys + empty-command-to-poll. "Still running" is a *successful* return with a session id, not a timeout error. For us this is the normal case, not the exception. |
| `apply_patch` V4A as the only edit tool | Codex | Context-anchored, no line numbers, multi-file add/update/delete/move. ~300 lines of Python. Needs no read-before-write bookkeeping — the context match *is* the drift detection. Strongest signal available: opencode ships both editors and gives `apply_patch` to its strongest models while denying them `edit`/`write` entirely. |
| Trusted-command allowlist | Codex | ~60 lines. The easy-to-miss parts: `find` is unsafe with `-exec`/`-delete`, and `bash -lc "a && b"` is safe only if every constituent is. **`python` must not be on the list.** |
| Bash AST decomposition + arity prefixes | opencode | `tree_sitter` exists for Python. Makes "always allow" mean `git checkout *` rather than `git`. |
| Approval axis ⟂ sandbox axis | Codex | Never let an escalation silently drop a restriction. ~20 lines; the reasoning is the value. |
| Output spillover + redaction | Pi | Bounded preview + pointer; redact **before** persisting; refuse if raw secret bytes would survive. Close Pi's own gap: they redact artifacts but not the inline output, so `bash env` leaks credentials into the transcript. Do both. |
| Secret registry | OpenHands | Scan command → inject only the needed vars → mask exported values even if the source later fails. **Built as the masking half** (`SecretRegistry`, registered once and masked forever after); injection has no caller yet. |
| Post-edit checks fed back | opencode | Not LSP. Built as **deterministic parse checks** (Python/JSON/YAML, stdlib, in-process) rather than shelling out to `ruff`/`mypy`: both are dev dependencies absent from the production image, so an automatic linter pass would be a subprocess per edit that silently does nothing exactly where the model most needs it — the missing-backend-reads-as-clean-result failure again. A linter is one `run_command` away, where the model can see for itself whether it exists. |
| Shadow-git snapshots | opencode | Bare tree hash in a separate git dir with `objects/info/alternates` into the real repo. No commits, no refs, invisible in `git log`. **For hypothesis testing this is provenance, not undo:** "this hypothesis was tested against this exact worktree state." |

**Attachment shape:** the model-facing tool call enqueues a durable task and
returns a handle; a later poll returns the result. That keeps the LLM loop's
iteration budget from being consumed by wall-clock waiting. The tool itself is
the first non-MCP tool in the registry — either it becomes an MCP tool on a
local server (keeps one registration path, but adds an HTTP hop and inherits the
300 s `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS`) or `ToolRegistry` grows a second
kind. **Open — see §5.**

### Phase 3 — Computational Discovery (capability B)

New agent, new tables, reused substrate.

- **New engine agent** `agents/code_evolve/` — a sibling of `agents/evolution/`,
  registered in `NODE_REGISTRY`, owning parent sampling, prompt assembly, diff
  application, cell/archive bookkeeping. Keep our **operator deck** idea: our
  seven named operators beat OpenEvolve's single implicit "make it better," and
  named code operators (vectorize, add feature, change model family, tune
  hyperparameters, simplify) give the lineage graph legible edge labels.
- **New tables** `code_variants` / `code_variant_state` / `code_variant_metrics`
  / `code_variant_artifacts`, mirroring the `hypotheses`/`hypothesis_state`
  split rather than widening it. `hypotheses.statement`/`mechanism`/
  `expected_effect` and `hypothesis_state.novelty_score`/`verification_verdict`
  have no meaning for a program; widening leaves every column nullable and every
  consumer branching on run type.
- **New task types** reusing the queue verbatim:
  `engine.fanout.variant.propose|evaluate|aggregate`. Our retry rule applies
  unchanged — only `UnsupportedTaskError` is permanent — so **a crashing variant
  evaluation must return a scored result, not raise.**
- **Ports:** SEARCH/REPLACE diff protocol (fix on the way in: reject a child
  whose blocks did not all apply — theirs swallows misses); the **artifacts
  side-channel** (failed-run stderr/traceback injected into the next prompt —
  this is what turns a crash into a signal); **cascade evaluation** with
  per-stage thresholds, which is the cost control for a 306-variant run.
- **Sign convention:** OpenEvolve maximizes unconditionally; the Google worked
  example minimizes MAE. Negate at the boundary or this is a silent inversion.
- **Skip:** their `ProcessPoolExecutor` with a full-DB snapshot pickled per
  iteration — actively harmful at 306 variants, and our queue is strictly better.

### Phase 4 — Surface

The one place the "it's the same object" argument does hold. Code Variants /
Visualizations / Run Specifications is the same information architecture as our
ideas / learning / details tabs, and the lineage graph is `parent_id` edges
either way. Build it once over an abstract "run item with a parent and a score."

New: the **Breakthrough Plot** (running max over fitness ordered by ordinal) —
the one chart OpenEvolve lacks. Plus dense 1..N variant numbering that
**includes error rows** (OpenEvolve never allocates an id for a parse failure;
Google's numbering is dense, so every attempt gets one), per-variant status, and
per-variant LLM "insights" generated on demand.

## 4. Sequencing and risk

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 4 (terminal surface)
                 │
                 └────► Phase 3 ──► Phase 4 (discovery surface)
```

Phase 0 is the cheapest and most urgent: it is a latent bug fix today and a
prerequisite tomorrow. Phase 1 is the long pole and carries essentially all the
security risk. Phase 3 depends on Phase 1 but *not* on Phase 2 — the discovery
loop needs an execution service, not a terminal.

**Biggest risks, honestly:**

1. **The sandbox is the whole job.** Every polished harness we studied is
   polished *around* an execution boundary it does not have. Budget accordingly
   and do not let Phase 2's long port list disguise where the difficulty is.
2. **Trust boundary change.** Today no untrusted code executes anywhere in this
   system. This is the largest single change to its threat model.
3. **The data plane is a new storage class.** Google's surface offers a 200 GB
   shared source library; we cap uploads at 25 MB and store *extracted text
   only*. Not a config change.
4. **Single-writer contention.** A 306-variant run writes a lot. Every write
   must be off the execution path.

## 5. Decided and still open

**D8 — scope: DECIDED. Full sequence, terminal before discovery.**
`0 → 1 → 2 → 3 → 4`. The discovery loop is therefore built on an execution
surface already proven by real terminal use rather than in parallel with it.
The cost is that the parity gap stays open longer; the benefit is that Phase 3
inherits a Phase-1 sandbox that has been exercised by Phase 2 against real work,
which is the phase most likely to be wrong in ways only usage reveals.

Still open:

- **D9 — production exec topology.** The new blocker, promoted from D5's
  second half. Bubblewrap needs `--privileged`, which Railway does not give an
  app container, so the choice is a dedicated exec service reached over the
  private network (`SandboxKind.EXTERNAL`, the seam already exists) or a
  different confinement primitive. Until it is answered, `run_command` is a
  development-only tool: correct, tested, and withheld in production.
- **D10 — which agent gets the workspace.** The *resolution* half is settled:
  `open_run_workspace(run_id)` is idempotent, off-volume, and treats the run id
  as untrusted input, so a restarted worker reopens the directory the killed one
  wrote rather than starting again beside it. What is still open is which node
  is handed `build_workspace_tools(...)`. Not the draft-generation loop —
  reading literature does not need a terminal — so on the current phasing the
  first caller is Phase 3's evaluator.
- **D6 — dataset storage.** Blocked on how large "large" needs to be for the
  first real use case.
- **`docs/FIDELITY.md:93`** currently records Computational Discovery as an
  accepted divergence. Revise when Phase 3 is committed to, not before.
