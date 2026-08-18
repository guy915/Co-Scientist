# OpenHands as an execution harness — analysis for the Co-Scientist host

**Date:** 2026-08-18
**Analyst note on sources — read this first.**

Two repositories are cited. The convention is used on *every* citation:

| Prefix | Repository | Pin |
|---|---|---|
| `canvas/…` | `/Users/guy/Code/co-scientist/references/harness/OpenHands` (the repo handed to me) | `b25f9b3969f924f37440fee908ff35309ec6eea2` |
| `sdk/…` | `OpenHands/software-agent-sdk`, cloned to scratchpad, **read-only** | tag `v1.42.1`, commit `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497` |

## 0. The pinned checkout does not contain the harness

This is the single most important structural finding, and it invalidates any analysis written from memory of OpenHands.

The pinned checkout is **not** the Python agent monolith. It is `@openhands/agent-canvas` v1.14.0 — a React/TypeScript frontend plus an Electron desktop shell (`canvas/package.json:1-2`). It contains 125,404 lines of TS/TSX and exactly 8 Python files, none of which are harness code (two are GitHub Actions helper scripts, two are mock servers for e2e tests).

Its own architecture doc states the boundary explicitly — Agent Canvas is *not* responsible for "Executing agent actions directly" or "Providing the sandbox or workspace isolation layer" (`canvas/docs/architecture.md:15-20`). The backend is named: the OpenHands Agent Server, from the `software-agent-sdk` repo (`canvas/docs/architecture.md:24`).

The version contract is pinned in `canvas/config/defaults.json`: `versions.agentServer = "1.42.1"`, `compatibility.minimumAgentServer = "1.28.0"`, images `ghcr.io/openhands/agent-server`, ports `agentServer: 18000`. The launcher shells out to `uvx` to run the Python agent-server from PyPI (`canvas/scripts/dev-safe.mjs:400-516`). A CI job asserts that four PyPI packages — `openhands-sdk`, `openhands-tools`, `openhands-workspace`, `openhands-agent-server` — move in lockstep (`canvas/scripts/check-sdk-version-sync.mjs:11-20,101`).

I verified the version claim empirically rather than trusting the comments: the SDK tag `v1.42.1` exists and is the release commit, so the four packages genuinely are one repo at one version. (`canvas/config/defaults.json` carries a stale comment referencing "openhands-sdk 1.35.0" in the ACP constraint blurb; that is a note about an old bug, not a live version pin.)

**Consequence:** the harness is now shipped as an **embeddable Python SDK + a FastAPI agent-server on PyPI**. That reframes the whole "adopt vs. reimplement" question — see §7 and the executive summary. Everything below §0 cites the SDK.

Package sizes at v1.42.1:

| Package | Files | Lines | Role |
|---|---|---|---|
| `openhands-sdk` | 281 | 68,393 | agent loop, events, state, LLM, MCP client, security |
| `openhands-agent-server` | 70 | 25,047 | FastAPI server, REST+WS, persistence, routers |
| `openhands-tools` | 89 | 16,483 | terminal, file editor, grep/glob, browser, delegate |
| `openhands-workspace` | 10 | 2,489 | Docker / Apptainer / cloud sandbox launchers |

---

## 1. Execution substrate

### 1.1 The workspace interface is small and genuinely portable

`BaseWorkspace` (`sdk/openhands-sdk/openhands/sdk/workspace/base.py:25-261`) is an abstract Pydantic model with one config field (`working_dir`, line 40) and six abstract/overridable operations:

- `execute_command(command, cwd=None, timeout=30.0) -> CommandResult` (line 150)
- `file_upload(source, destination) -> FileOperationResult` (line 173)
- `file_download(source, destination) -> FileOperationResult` (line 193)
- `git_changes(path) -> list[GitChange]` (line 213)
- `git_diff(path) -> GitDiff` (line 227)
- `pause()` / `resume()` — default `NotImplementedError` (lines 241-261)

It is a context manager (`__enter__`/`__exit__`, lines 55-148). This is a ~40-line interface. **It is the most portable thing in the repo.**

One wart worth naming: `BaseWorkspace._send_completion_callback` (lines 85-135) POSTs run status to an `AUTOMATION_CALLBACK_URL` read from the environment. That is OpenHands' own hosted-automation product leaking into the base abstraction. It is inert when the env var is unset, but it is product surface in a class that otherwise has none.

### 1.2 Sandbox creation is `docker run` via subprocess — and the container runs the agent-server

`DockerWorkspace` (`sdk/openhands-workspace/openhands/workspace/docker/workspace.py:53-428`) does not use the Docker SDK for the run path; it shells out to the `docker` CLI (`execute_command(["docker", "version"])`, line 205; the run command, lines 241-259).

The important architectural point: **the container does not host a bare shell — it hosts the agent-server itself.** The run command ends `image, "--host", "0.0.0.0", "--port", "8000"` (lines 253-257), the container's 8000 is published to a host port (line 222), and `DockerWorkspace` subclasses `RemoteWorkspace`, so all subsequent operations are HTTP calls to that server (line 285, `super().model_post_init(context)`).

Lifecycle:
- Port chosen randomly in 30000-39999 via `find_available_tcp_port` (lines 37-50).
- `--rm` (line 247) — the container is ephemeral; nothing survives it except mounted volumes.
- Health gate: poll `GET {host}/health` up to `health_check_timeout` (default 120s), and abort early with container logs if the container has stopped (lines 314-349).
- Teardown: `docker stop`, optionally `docker rmi` (`cleanup()`, lines 367-390). Also wired to `__exit__` **and `__del__`** (lines 355-365) — GC-triggered teardown is fragile but it is what ships.
- `pause()`/`resume()` map to `docker pause` / `docker unpause` (lines 392-428), with a health re-check on resume. For a long research run this is a real cost lever.

### 1.3 Resource and network policy: essentially absent

I grepped the whole `openhands-workspace` package for container limits. The complete set of hits:

```
docker/workspace.py:238:  flags += ["--network", self.network]      # only if caller sets it
docker/workspace.py:249:  "nofile=65536:65536"                       # ulimit, raised not lowered
```

There is **no** `--memory`, `--cpus`, `--pids-limit`, `--read-only`, `--security-opt`, `--cap-drop`, or `--user`. `network` defaults to `None`, i.e. the container joins Docker's default bridge with **full outbound internet access** (line 119-122). `enable_gpu` adds `--gpus all` (lines 232-233).

So "sandbox" here means *container-level isolation from the host filesystem*, not resource containment and not egress control. For a scientific agent that will run untrusted generated code against real data, this is the layer you must add yourself. It is a handful of extra flags, but nobody has added them upstream.

Host filesystem exposure is opt-in through `volumes` (lines 97-100, 218-220); a prior `mount_dir` convenience field was removed and now raises a validation error steering callers to explicit `volumes` (lines 134-142).

### 1.4 Alternative substrates

- `ApptainerWorkspace` (`sdk/openhands-workspace/openhands/workspace/apptainer/workspace.py`, 413 lines) — Apptainer/Singularity, the HPC-cluster container runtime. **Directly relevant to a scientific host**: this is the runtime you get on a shared university cluster where Docker is unavailable.
- `APIRemoteWorkspace` (`remote_api/workspace.py`, 426 lines) and `OpenHandsCloudWorkspace` (`cloud/workspace.py`, 999 lines) — the latter is hosted-product surface (git provider clone mappings, org workflows) and is not worth extracting.
- No Kubernetes substrate exists in this package.

Note `openhands-workspace/pyproject.toml` declares a dependency on `openhands-agent-server`. The sandbox launchers are *not* separable from the server.

### 1.5 The agent↔sandbox wire protocol

`RemoteWorkspaceMixin` (`sdk/openhands-sdk/openhands/sdk/workspace/remote/remote_workspace_mixin.py`) is written in a **sans-I/O generator style**: each method is a generator that `yield`s a request dict and receives an `httpx.Response` (`_execute_command_generator`, lines 67-207). This lets sync and async transports share one body — the docstring says so at line 36. It is a tidy pattern worth stealing independently of OpenHands.

Remote command execution is **start-then-poll**, not a blocking call (lines 88-172):

1. `POST /api/bash/start_bash_command` with `{command, timeout, cwd?}` → returns `{id}`.
2. Loop: `GET /api/bash/bash_events/search` with `command_id__eq`, `kind__eq=BashOutput`, `sort_order=TIMESTAMP`, `limit=100`, and a cursor `order__gt=<last_order>`.
3. Accumulate `stdout`/`stderr` fragments; stop when an event carries a non-null `exit_code`; sleep 0.1s between polls (line 172).
4. On timeout, synthesize `exit_code=-1` and append a timeout note to stderr (lines 174-182).

The cursor is a monotonic `order` field, and the client hard-fails on a duplicate event id as a protocol-violation assertion (lines 146-152). Auth is a single header, `X-Session-API-Key` (line 64).

**This start-then-poll-with-cursor shape is exactly what a durable, restartable host wants** — a crashed poller can resume from `order__gt` without losing output. Contrast with a blocking HTTP call, which loses everything on disconnect. See §8.

Server side, the endpoints are `sdk/openhands-agent-server/openhands/agent_server/bash_router.py`: `GET /bash/bash_events/search` (line 34), `GET /bash/bash_events/{id}` (line 78), `GET /bash/bash_events/` (line 89), `POST /bash/start_bash_command` (line 100), `POST /bash/execute_bash_command` (line 111, the blocking variant), `DELETE /bash/bash_events` (line 125).

**Important distinction:** this `/api/bash` surface is a *side channel for the host program*. It is not how the agent's own `terminal` tool runs — that executes in-process inside the agent-server (§3.1). Two different paths to a shell.

---

## 2. Agent loop

### 2.1 Event / action / observation model

Events are Pydantic models under `sdk/openhands-sdk/openhands/sdk/event/`. The relevant subtypes seen in the matching logic are `ActionEvent`, `ObservationEvent`, `UserRejectObservation`, `AgentErrorEvent`, `MessageEvent`, `Condensation`, `CondensationRequest`, `ConversationErrorEvent`.

Two properties matter for a reimplementer:

- **Events form a tree, not a list.** Each event carries `parent_id`; the log exposes `path_to_root(leaf_id, limit)` returning the active branch root-first (`sdk/openhands-sdk/openhands/sdk/conversation/event_store.py:103-120`). Legacy events without `parent_id` fall back to the linear chain `idx-1` so old conversations load unbranched with no disk rewrite (`_effective_parent_id`, lines 88-101). This exists to support conversation branching/forking.
- **An action is paired to its observation by id.** `ObservationEvent`/`UserRejectObservation` match on `action_id`; `AgentErrorEvent` has no `action_id` and matches on `tool_call_id` instead (`sdk/openhands-sdk/openhands/sdk/conversation/state.py:680-697`). The docstring calls out why: crash recovery, where the error event is emitted after a restart (lines 669-671).

### 2.2 One turn = `Agent.step()`

`sdk/openhands-sdk/openhands/sdk/agent/agent.py:637-1030`. Order of operations:

1. **Re-execute unmatched actions first.** `ConversationState.get_unmatched_actions(state.active_branch())` (line 645); if any, execute them and return without sampling (lines 646-653). This one branch serves double duty as confirmation-mode resume *and* crash recovery.
2. Hook gate: if the last user message was blocked by a `UserPromptSubmit` hook, finish (lines 656-667).
3. Build LLM messages from the incrementally-maintained view, applying the condenser: `prepare_llm_messages(state.view, condenser=self.condenser, llm=self.llm)` (lines 674-676). If this returns a `Condensation`, emit it and return — condensation consumes a turn (lines 678-681).
4. Non-multimodal image handling: either swap images for references and expose a vision tool, or finish with an explanatory message (lines 685-707).
5. `make_llm_completion(...)` with the tool list (lines 712-718).
6. Classify and dispatch the response.

### 2.3 Tool dispatch: sequential by default, resource-locked when parallel

`_execute_actions` (`sdk/openhands-sdk/openhands/sdk/agent/agent.py:571-599`) builds an `_ActionBatch` (class at line 186) from the action events and drives it in three phases — `prepare` → `emit` → `finalize`. The separation matters: tools run first, **events are emitted afterwards in order**, and terminal transitions happen last via callbacks (`mark_finished` sets `FINISHED`, lines 594-598). An async twin exists (`_aexecute_actions`, lines 601-634) whose only difference is an `await` boundary between tool invocations.

A single tool call is `_execute_action_event` (lines 1334-1396). Its contract is stated in the docstring (lines 1339-1352) and is the part worth copying:

- It is **called from parallel threads** and **must not mutate shared conversation state**; `blocked_actions` and `execution_status` transitions are the caller's job on the main thread.
- It **does not emit events** — it returns `list[Event]` and the caller emits them in order. This is what keeps the persisted log deterministic even when execution is concurrent.
- Thread safety of an individual tool is explicitly the tool's own responsibility.

Error handling mirrors §2.4's philosophy: a `ValueError` from a tool is converted into an `AgentErrorEvent` carrying `tool_name` and `tool_call_id` so the agent can self-correct (lines 1379-1391), rather than propagating. A missing tool raises `RuntimeError` as a should-never-happen (lines 1358-1362), and a non-`Observation` return trips an assertion (lines 1374-1376). Note the `AgentErrorEvent` path is exactly what makes an errored action count as "matched" in §5.4's replay logic.

`ParallelToolExecutor` (`sdk/openhands-sdk/openhands/sdk/agent/parallel_executor.py`, 357 lines) defaults to **`max_workers=1`** (line 61), and short-circuits to inline execution when there is one action or one worker (lines 98, 161). So **the shipped default is sequential**; parallelism is opt-in via `tool_concurrency_limit`. When enabled, a `ResourceLockManager` serializes tools that declare the same resource while letting tools on different resources overlap (module docstring, lines 6-8) — each tool advertises what it touches via `declared_resources()`, and the docstring warns the mechanism is only as good as those declarations (lines 10-16). Each executor owns its own thread pool and lock manager so nested sub-agent execution cannot deadlock the parent (lines 52-56).

For the host, the useful takeaway is the phase split (run → emit in order → transition), not the concurrency: a research agent's tool calls are long and side-effecting, and `max_workers=1` is the right default there too.

### 2.4 Error handling is mostly in-band nudging, not exceptions

This is the design decision most worth copying. In `step()`:

- `FunctionCallValidationError` → inject the error text as a **user message** and return; the loop retries naturally (lines 719-730).
- `LLMContentPolicyViolationError` → inject a "your response was blocked, rephrase" user message (lines 731-750). The comment notes these blocks are deterministic, so a bare retry would loop forever.
- `LLMMalformedConversationHistoryError` → `state.rebuild_view()` then emit `CondensationRequest()`; if no condenser can handle it, **re-raise** and let it be visible, because it usually indicates an event-stream or resume bug (lines 751-781).
- `LLMContextWindowExceedError` → emit `CondensationRequest()` if a condenser handles requests, else raise after logging a long remediation message (lines 782-795, and `_log_context_window_exceeded_warning` at 1414-1486).

The principle: **recoverable model failures become events in the conversation; structural failures raise.** That maps cleanly onto the host's existing philosophy of turning failures into retryable task state.

### 2.5 The run loop and its termination conditions

`LocalConversation.run()` (`sdk/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py:1857-1990+`). It re-enters `RUNNING` from IDLE/PAUSED/ERROR/STUCK (lines 1874-1881), then loops on `agent.step()` under the state lock. Exits:

| Condition | Line | Notes |
|---|---|---|
| `PAUSED` or `STUCK` | 1888-1894 | checked while holding the lock |
| `FINISHED` | 1896-1922 | **vetoable** — a stop hook can deny stopping, inject feedback, and flip back to RUNNING |
| `WAITING_FOR_CONFIRMATION` | 1933-1940, 1960-1965 | breaks out to await approval |
| budget exceeded | 1967-1972 | emits `MaxBudgetReached` |
| `iteration >= max_iteration_per_run` | 1974-1989 | **default 500** (line 210); sets ERROR unless the agent finished on the final iteration |
| stuck detected | 1927-1929 | `_check_stuck_or_nudge()` nudges once before giving up |

`ConversationExecutionStatus` (`state.py:48-79`) is IDLE / RUNNING / PAUSED / WAITING_FOR_CONFIRMATION / FINISHED / ERROR / STUCK / DELETING, with `is_terminal()` = {FINISHED, ERROR, STUCK}. The docstring explains IDLE is deliberately excluded to avoid a false positive when a WebSocket delivers the initial state (lines 68-70).

Two subtleties I'd have got wrong by guessing:
- The loop deliberately does **not** break on FINISHED at the bottom of the iteration, so a concurrent `send_message()` can flip status to IDLE and keep the run alive rather than losing the message. The five-step rationale is in a comment at lines 1953-1959.
- `_step_holds_state_lock` is set around `agent.step()` so state-mutating tools running on worker threads skip re-acquiring the lock instead of deadlocking (lines 1941-1951, referencing issue #3485).

### 2.6 Stuck detection

`StuckDetector` (`sdk/openhands-sdk/openhands/sdk/conversation/stuck_detector.py:24-156+`) checks four configurable patterns: repeating action→observation, repeating action→error, agent monologue (repeated messages without user input), and an alternating pattern. `is_stuck()` short-circuits if the event count is below the minimum threshold (lines 104-114). Enabled by default (`stuck_detection: bool = True`, `local_conversation.py:211`). The nudge-once-then-fail policy is in `_check_stuck_or_nudge` (lines 660-684).

For a research agent that legitimately repeats similar computations, these thresholds would need re-tuning — the defaults assume software-engineering behaviour.

### 2.7 Context condensation

`sdk/openhands-sdk/openhands/sdk/context/condenser/`: `base.py`, `llm_summarizing_condenser.py`, `no_op_condenser.py`, `pipeline_condenser.py`.

`LLMSummarizingCondenser` (`llm_summarizing_condenser.py:37-80+`) is a `RollingCondenser` with:
- `max_size: int = 240` events, `max_tokens: int | None`
- `keep_first: int = 2` — the first N events are never condensed
- `minimum_progress: float = 0.1` — a condensation that would forget <10% of events is treated as an error
- `hard_context_reset_max_retries: int = 5` and `hard_context_reset_context_scaling: float = 0.8` — on summarization failure, shrink each event's string budget by 20% and retry
- validator: `keep_first < max_size // 2` (lines 74-80)
- condensation reasons are enumerated: REQUEST / TOKENS / EVENTS (lines 30-35)

It uses an **independent LLM instance** from the agent's, and the docstring explicitly warns not to assume they're the same (lines 38-44). The default preset gives the condenser a copy of the agent LLM tagged `usage_id="condenser"` so costs are attributed separately (`sdk/openhands-tools/openhands/tools/preset/default.py:85-87`).

The `View` machinery (`sdk/openhands-sdk/openhands/sdk/context/view/`) enforces invariants as named properties — `tool_call_matching.py`, `observation_uniqueness.py`, `batch_atomicity.py`, `tool_loop_atomicity.py`. That is, the message list handed to the LLM is validated against structural properties rather than assembled ad hoc. This is the machinery that makes `rebuild_view()` a safe recovery action.

---

## 3. Tool surface

Tools are registered by name into a registry (`register_tool(name, factory)`, `sdk/openhands-sdk/openhands/sdk/tool/registry.py:113-138`), accepting either a `ToolDefinition` instance carrying an `.executor` or a `ToolDefinition` subclass with `.create(**params)` (lines 120-130). A `Tool(name=...)` spec is then resolved at agent construction.

**Default tool set is small** (`sdk/openhands-tools/openhands/tools/preset/default.py:34-65`): `TerminalTool`, `FileEditorTool`, `TaskTrackerTool`, plus `BrowserToolSet` when `enable_browser` (default True), plus `TaskToolSet` only when `enable_sub_agents` (default False). Presets exist per model family: `default.py`, `gpt5.py`, `gemini.py`, `planning.py`.

The SDK injects two meta-fields into every tool schema — `security_risk` and `summary` — reserved at `sdk/openhands-sdk/openhands/sdk/tool/tool.py:65` and rendered with priority ordering at lines 692-710, 871-875. See §4.

### 3.1 `terminal` — the piece most worth taking

Files: `sdk/openhands-tools/openhands/tools/terminal/` (4,052 lines across definition, impl, metadata, timeout policy, and five backend implementations).

**Schema** (`TerminalAction`, `definition.py:86-115`):

| Field | Type | Default | Purpose |
|---|---|---|---|
| `command` | `str` | required | one shell command; or a key name when `is_input=True` |
| `is_input` | `bool` | `False` | send input to the *running* process instead of executing |
| `timeout` | `float \| None` (≥0) | `None` | hard limit; when unset, falls back to a no-new-output pause |
| `reset` | `bool` | `False` | tear down and recreate the session; cannot combine with `is_input` |

`command` accepts special key names when `is_input=True`: `C-c`, `C-d`, `C-z`, any `C-<letter>`, plus `UP`/`DOWN`/`LEFT`/`RIGHT`/`HOME`/`END`/`PGUP`/`PGDN`/`TAB`/`ESC`/`BS`/`ENTER` (lines 88-100). An **empty string** re-reads output from a still-running command (line 90) — that is how the agent waits on a long job.

**Backends** (`terminal/terminal/`): `tmux_terminal.py` (247), `subprocess_terminal.py` (525), `windows_terminal.py` (465), coordinated by `factory.py` and `terminal_session.py` (638), with a `tmux_pane_pool.py` (306) for pane reuse. `openhands-tools` depends on `libtmux>=0.53.0`.

**The completion-detection mechanism is the clever part.** `CmdOutputMetadata.to_ps1_prompt()` (`terminal/metadata.py:44-63`) builds a PS1 that emits a JSON blob between sentinels:

```
\n###PS1JSON###\n {"pid":"$!","exit_code":"$?","username":"\u","hostname":"\h",
                   "working_dir":"$(pwd)","py_interpreter_path":"$(command -v python || echo \"\")"} \n###PS1END###
```

Constants at `terminal/constants.py:5-13`. The runner captures the pane and regex-scans for the *last* `###PS1JSON###` before each `###PS1END###` — a negative lookahead specifically to survive nested/corrupted markers from concurrent output (lines 7-13). Each match is JSON-validated before acceptance, and malformed blocks are skipped rather than fatal (`matches_ps1_metadata`, `metadata.py:65-79`). Numeric coercion is defensive: unparseable `exit_code` becomes `-1` (lines 93-101).

So the shell itself reports exit code, pid, cwd, and active Python interpreter on every prompt — no wrapper process, no exit-code file, and it survives `cd`, `venv activate`, and interactive programs. **This is the highest-value single idea in the repository for the Co-Scientist host.**

**Operational constants** (`terminal/constants.py:18-44`): `MAX_CMD_OUTPUT_SIZE = 30000` chars (deliberately matched to the LLM's `max_message_chars`), `NO_CHANGE_TIMEOUT_SECONDS = 30`, `POLL_INTERVAL = 0.5`, `HISTORY_LIMIT = 10_000`, tmux socket `openhands`, pane `256x200` (the comment notes this replaced an oversized 1000x1000 virtual grid).

The timeout message handed to the model is itself a small piece of prompt engineering (`constants.py:22-28`): it tells the model it may send `''` to wait longer, send other commands, send `C-c`/`C-z`/`C-d`, or raise `timeout` next time. **This is precisely the interaction a long-running scientific computation needs**, and it is the reason a naive `subprocess.run(timeout=N)` tool is inadequate.

One guardrail worth noting as a model-behaviour patch: `looks_like_python_literal_argument()` (`definition.py:56-84`) detects when the model has stuffed a Python/JSON list or dict into `command`, and returns a targeted error telling it to write a script with `file_editor` or use a heredoc (`_LITERAL_ARG_HINT_TEMPLATE`, lines 36-53). It carefully distinguishes bash `[[ -f x ]]` (whitespace after `[[`) from a nested list literal. That's an empirically-earned fix, not a theoretical one.

### 3.2 Other tools

- **`file_editor`** (`tools/file_editor/`, with `utils/` for diff, encoding, history, file_cache, shell) — the view/create/str_replace/insert/undo family, with an undo history store.
- **`apply_patch`** (`tools/apply_patch/`) — a separate patch-application tool coexisting with `file_editor`.
- **`glob`** / **`grep`** — dedicated search tools rather than making the model shell out.
- **`task_tracker`** — in the default set; a to-do list the agent maintains.
- **`browser_use`** (`tools/browser_use/`, incl. `server.py`, `recording.py`) — wraps the `browser-use` package. Heavy: it drags Playwright into the dependency tree.
- **`delegate`** / **`task`** (`TaskToolSet`) — sub-agent spawning; off by default.
- **`planning_file_editor`**, **`gemini/*`** (read_file/write_file/edit/list_directory) — model-family-specific variants.

Presets ship per model family because tool *schemas* need to differ per model — a detail easy to miss.

---

## 4. Permission / safety model

### 4.1 Risk is a field the model fills in

`SecurityRisk` (`sdk/openhands-sdk/openhands/sdk/security/risk.py:13-21+`) is `UNKNOWN | LOW | MEDIUM | HIGH`.

The SDK **injects `security_risk` into every non-read-only tool's JSON schema** (`sdk/openhands-sdk/openhands/sdk/tool/tool.py:871-875`, gated by `add_security_risk_prediction`, lines 692-710). The system prompt teaches the tiers, and the tier definitions **swap depending on whether the agent is sandboxed** (`sdk/openhands-sdk/openhands/sdk/context/prompts/sections/static.py:299-319`): in CLI mode HIGH means "system settings, global installs, sudo, deleting critical files"; in sandbox mode HIGH means "data exfiltration or privilege breaks — sending secrets out, connecting to host filesystem, privileged container ops". Same word, different meaning by deployment. That is a thoughtful detail.

Crucially, the LLM's self-assessment is **discarded unless a security analyzer is configured**: `_extract_security_risk` pops the field and returns `UNKNOWN` when `security_analyzer is None` (`sdk/openhands-sdk/openhands/sdk/agent/agent.py:1057-1075`). So the schema field is inert by default — a fact easy to misread as "OpenHands has LLM risk gating on by default". It does not.

### 4.2 Confirmation policy

`sdk/openhands-sdk/openhands/sdk/security/confirmation_policy.py:9-61` — three policies:

- `AlwaysConfirm` — always (lines 27-32)
- `NeverConfirm` — never (lines 35-40)
- `ConfirmRisky(threshold=HIGH, confirm_unknown=True)` — confirm at or above threshold; `UNKNOWN` is confirmed by default; a validator forbids `threshold=UNKNOWN` (lines 43-61)

The gate: analyzer produces risks (or all-`UNKNOWN` when absent), and `if any(policy.should_confirm(r) for r in risks)` flips state to `WAITING_FOR_CONFIRMATION` (`agent.py:1037-1056`). Approval is **implicit**: the next `run()` finds unmatched actions and executes them (`agent.py:643-653`). Rejection is recorded as a `UserRejectObservation`, which counts as "matched" and thus suppresses re-execution (`state.py:685-686`).

This is an elegant reuse — one mechanism (unmatched-action replay) serves confirmation, resume, and crash recovery. It is also the source of the at-least-once hazard in §5.4.

Additional analyzers exist beyond the base: `llm_analyzer.py`, `toolshield_llm_analyzer.py`, `ensemble.py`, `grayswan/`, `defense_in_depth/policy_rails.py`, plus a bash AST parser (`_shell_ast.py`, `shell_parser.py`) — so a policy can reason about the parsed command rather than a regex.

### 4.3 Secret scoping — the best idea in this section

`SecretRegistry` (`sdk/openhands-sdk/openhands/sdk/conversation/secret_registry.py:21-60+`) maps keys to `SecretSource` objects (static or callable). The docstring states the mechanism: "When a bash command is about to be executed, it scans the command for any secret keys and injects the corresponding environment variables" (lines 24-27).

So secrets are **injected on demand, per command, only when the command text mentions the key** — never blanket-exported into the session and never placed in the prompt. Exported values are then tracked (`track_exported_values`, lines 44-47) so output can be masked *even if a callable secret later fails*, which is the failure mode a naive masker misses. Failed lookups back off for 60s (line 19).

Serialization is context-driven (lines 29-34): with a `cipher` in context, secrets are encrypted; with `expose_secrets=True`, plaintext; otherwise redacted to `**********`. `ConversationState._save_base_state` warns loudly when secrets exist without a cipher, because they will be redacted and **lost on restore** (`state.py:421-441`).

Server-side redaction is separate: `_secret_redaction.py` and `_secrets_exposure.py` in the agent-server.

### 4.4 Egress control

None at the sandbox layer (§1.3). The only network control is the optional `--network` flag. Any egress policy is the integrator's job. The prompt *tells* the model that exfiltration is HIGH risk; nothing *prevents* it.

---

## 5. Session & state — the section that matters most to the host

### 5.1 On-disk layout

`sdk/openhands-sdk/openhands/sdk/conversation/persistence_const.py` (the whole file):

```python
BASE_STATE = "base_state.json"
EVENTS_DIR = "events"
EVENT_NAME_RE = re.compile(r"^event-(?P<idx>\d{5,})-(?P<event_id>[0-9a-fA-F\-]{8,})\.json$")
EVENT_FILE_PATTERN = "event-{idx:05d}-{event_id}.json"
```

So a conversation is a directory containing **one JSON file per event**, zero-padded to 5 digits (uncapped — the regex accepts more), plus a single `base_state.json` snapshot. Also `observations/` for environment observation files (`state.py:398-402`).

**There is no SQLite anywhere in the SDK or agent-server.** I grepped case-insensitively across both packages: the only hit for `sqlite|sqlalchemy|alembic` is in `openhands-agent-server/pyproject.toml`, which declares `aiosqlite>=0.19`, `alembic>=1.13`, and `sqlalchemy>=2` as dependencies that **no module imports**. They are vestigial. The agent-server's own stores are file-based JSON with `fcntl`/`msvcrt` locking and `0o700`/`0o600` permissions (`sdk/openhands-agent-server/openhands/agent_server/persistence/store.py:1-55`).

### 5.2 State is a hybrid: snapshot + event log, not pure event sourcing

Verified rather than assumed. `ConversationState` is a Pydantic model whose **public fields autosave to `base_state.json` on mutation** — `__setattr__` writes when the attribute is a public model field and autosave is enabled (`state.py:580-610`), with writes deferred to `__exit__` when inside the state context manager so a burst of mutations produces one I/O write (lines 596-606, and the note at 732).

Events are **not** in that snapshot — `_save_base_state`'s docstring says "no events; events are file-backed" (`state.py:421-423`).

The derived conversational `View` is explicitly *never persisted* (comment at `state.py:236`) and is rebuilt from events.

### 5.3 Open-or-create is the resume path

`ConversationState.create()` (`state.py:446-580`) is a single factory with two branches keyed on whether `base_state.json` exists:

- **Resume** (lines 516-553): validate the JSON into a `ConversationState` (with cipher context for secrets), assert the conversation id matches or raise, attach the `EventLog`, then `state.rebuild_view()` — described as a cold-load rebuild "with full property enforcement" because "persisted events may come from an older code version or be corrupted" (lines 535-539). Then `agent.verify(state.agent, events=state._events)` checks the supplied agent/tools against the persisted ones (line 542). Stats are deliberately *not* reset (comment, lines 548-549).
- **Fresh** (lines 555-578): construct, attach event log, write the initial snapshot, enable autosave.

Without a `persistence_dir` it silently falls back to `InMemoryFileStore` with a warning that data will not persist (lines 505-512).

### 5.4 What happens to an in-flight tool call — and the honest caveat

There is no explicit "recover interrupted run" routine. Recovery is emergent: on the next `step()`, `get_unmatched_actions()` returns any `ActionEvent` lacking a matching `ObservationEvent` / `UserRejectObservation` / `AgentErrorEvent`, and **those actions are executed** (`agent.py:643-653`, `state.py:662-697`). The docstring confirms this is intended for "crash recovery scenarios where an error event is emitted after a server restart" (`state.py:669-671`).

**The consequence must be stated plainly: tool execution is at-least-once, not exactly-once.** If the process dies after a command has started but before its observation is persisted, the command runs again on resume. For OpenHands' domain (re-running `pytest`, re-reading a file) that is benign. For the Co-Scientist host — where a tool call might launch an expensive computation, mutate a dataset, or consume a metered external API — **it is not**. Any port must add an idempotency key or a "started" marker event. This is the single most important caveat in this document for the host.

### 5.5 Concurrency: file lease + FIFO lock

Two distinct mechanisms.

**Cross-process ownership** — `sdk/openhands-agent-server/openhands/agent_server/conversation_lease.py`. An `owner_lease.json` guarded by a `filelock` `.owner_lease.lock`, with `DEFAULT_LEASE_TTL_SECONDS = 45.0` (line 20). The payload carries `owner_instance_id`, a monotonic `generation`, `expires_at`, and optionally `owner_host` / `owner_pid` for crash detection (`LeasePayload`, lines 29-37). Takeover uses `_is_pid_alive()` via `os.kill(pid, 0)`, and is **deliberately conservative**: `PermissionError` and unknown `OSError` both report "alive" so a live lease is never stolen (lines 45-67). `LeaseClaim` carries a `takeover` flag (lines 23-26).

This is the direct analogue of the host's `scientific_tasks` lease columns — same problem, file-based rather than row-based solution. The host's version is strictly better (see §8).

**In-process serialization** — `fifo_lock.py` and `resource_lock_manager.py`, plus the `EventLog` write lock (`.eventlog.lock`, `LOCK_TIMEOUT_SECONDS = 30`, `event_store.py:22-23`). The `EventLog` docstring carries a warning worth repeating: `flock()` "does NOT work reliably on NFS mounts or network filesystems" and shared-storage deployments need other coordination (`event_store.py:36-40`). **That is disqualifying for a clustered deployment on shared storage.**

`EventLog` maintains in-memory `_id_to_idx` / `_idx_to_id` / `_event_cache` maps, built by `_scan_and_build_index()` at construction (lines 50-56) — so opening a conversation is a **directory scan**, O(events). Fine at hundreds of events; a cold-start cost at hundreds of thousands.

### 5.6 Live streaming and replay

`pub_sub.py`, `event_service.py`, `event_router.py`, `sockets.py` in the agent-server. The client-visible contract is the one the workspace mixin uses: a search endpoint with a monotonic `order` cursor and `order__gt` filtering (§1.5), which is exactly what a reconnecting client needs to replay only what it missed. `ConversationStateUpdateEvent` is broadcast via a state-change callback (`state.py:398-411`); a comment at lines 610-612 notes the view is deliberately excluded from broadcast because it changes on every event and would roughly double the persisted log.

Server-side status can be read cheaply without loading a whole conversation: `_read_execution_status_sync` pulls just `execution_status` out of the persisted JSON (`conversation_service.py:556-568`), with a signature-based cache to avoid re-reads (lines 576-577, 828-899).

---

## 6. Extensibility

### 6.1 MCP — the definitive answer

**The SDK is an MCP *client* only. It does not expose the sandbox as an MCP server.**

I verified this negatively and positively:

- Client side exists and is substantial: `sdk/openhands-sdk/openhands/sdk/mcp/` — `client.py`, `config.py`, `definition.py`, `tool.py`, `utils.py`, `exceptions.py`. It is built on **`fastmcp>=3.0.0`** (`openhands-sdk/pyproject.toml`), and config normalizes through `fastmcp.mcp_config.MCPConfig` (`mcp/config.py:11`). MCP tools are merged into the agent's tool list via `create_mcp_tools` (imported at `mcp_router.py:45`).
- Server side does not exist: `grep -rn "FastMCP("` across the entire SDK (excluding tests) returns **zero** results. Nothing instantiates an MCP server.
- The agent-server's `mcp_router` exposes exactly one endpoint — `POST /api/mcp/test`, a connectivity/OAuth probe for validating a user's MCP server config (`mcp_router.py:1-3`, router at line 60). It is configuration tooling, not tool exposure.
- `tool_router` exposes only `GET /api/tools/` returning `list[str]` of tool names (`tool_router.py:22-23`).
- The full router list is at `api.py:403-465`: event, conversation, credential_binding, tool, bash, git, file, vscode, desktop, skills, sub_agents, plugins, hooks, llm, mcp, settings, workspaces, profiles, agent_profiles, auth, plus an OpenAI-compatible router (line 453) and sockets (line 466). No MCP mount.

**Could you expose the sandbox as an MCP server?** Yes, easily — but you would be writing it, not adopting it. The agent-server already exposes the primitives over REST behind a single `X-Session-API-Key` header: `POST /api/bash/start_bash_command`, `GET /api/bash/bash_events/search`, `POST /api/file/upload`, `GET /api/file/download`, `GET /api/git/changes`, `GET /api/git/diff`. A ~200-line MCP server wrapping those six calls would give the host's existing LangGraph agents a sandboxed shell over a protocol they already speak. That is the shortest path from here to the stated goal, and it is spelled out in §8.

Note also the reverse direction is already free: because the SDK is a `fastmcp` client, an OpenHands agent could consume the host's existing `engine/mcp_server/` literature tools with no new code.

### 6.2 Skills

`sdk/openhands-sdk/openhands/sdk/skills/` — `skill.py`, `trigger.py`, `installed.py`, `fetch.py`, `execute.py`, `types.py`, `utils.py`. Skills are markdown with YAML front-matter (`import frontmatter`, `skill.py:13`). `SkillInfo` carries `name`, `content`, `triggers: list[str]`, `description` (lines 97-109).

The injection model is a three-way policy documented at `skill.py:178-203`:
- **agentskills format**: listed in `<available_skills>`; the agent reads full content on demand (progressive disclosure); if it also has triggers, content is auto-injected when triggered.
- **legacy with triggers**: listed, content injected on trigger.
- **legacy without triggers**: full content always in `<REPO_CONTEXT>`.

There is a builtin tool `invoke_skill` (`sdk/openhands-sdk/openhands/sdk/tool/builtins/invoke_skill.py`). Sub-agents are themselves defined as loadable definitions from a directory (`load_agents_from_dir`, `preset/default.py:104-105`).

### 6.3 Plugins, hooks, custom tools

- **Plugins**: `plugins_service.py`, `plugins_router.py`, `canvas_extensions/{installed,manifest}.py` — the manifest naming ties this to the Canvas product surface.
- **Hooks**: `hooks_service.py`, `hooks_router.py`. Two hook points are visible in the loop: `UserPromptSubmit` can block a user message (`agent.py:656-667`) and a **stop hook can veto the agent finishing**, injecting feedback and forcing another iteration (`local_conversation.py:1896-1922`). The feedback is prefixed with `ACP_STOP_HOOK_FEEDBACK_PREFIX` and injected as an `environment`-sourced message.
- **Custom tools**: `register_tool(name, factory)` (`registry.py:113-138`) — an in-process registry keyed by name, tracking module qualname (lines 132-137). Registration happens as an import side effect (`preset/default.py:18-19` comments "Tools are now automatically registered when imported"). There is no entry-point/plugin-discovery mechanism for tools; you import to register.

### 6.4 ACP — a third option worth naming

`canvas/docs/ACP_AGENTS.md` documents the Agent Client Protocol: the Agent Server spawns an external coding agent's CLI as a subprocess and relays turns over JSON-RPC on stdio. Supported: Claude Code (`npx -y @agentclientprotocol/claude-agent-acp`), Codex (`npx -y @agentclientprotocol/codex-acp`), Gemini CLI (`npx -y @google/gemini-cli --acp`). The SDK side is `sdk/openhands-sdk/openhands/sdk/agent/acp_agent.py` — **4,279 lines**, the single largest file in the SDK.

So OpenHands is also a *host* for other agents. For the Co-Scientist goal, that means a fourth option beyond port/depend/reimplement: drive an existing coding agent via ACP. Verdict in §7.

Caveat found in the pin: `canvas/config/defaults.json` constrains `agent-client-protocol<0.11` because 0.11.0 reordered `prompt()` arguments and breaks the SDK's ACP client with a `PromptRequest` validation error. The ACP surface is not yet stable.

---

## 7. What is worth taking — ranked

| # | Item | Verdict | Why |
|---|---|---|---|
| 1 | **PS1-JSON sentinel for command completion** (`terminal/metadata.py:44-101`, `constants.py:5-13`) | **[PORT]** | ~100 lines, zero OpenHands coupling. Gives exit code, pid, cwd, and interpreter path from a pane capture, surviving `cd`, venv activation, and interactive programs. Directly solves the hardest part of building a terminal tool. |
| 2 | **Interaction model for long-running commands** (`definition.py:86-115`, `constants.py:22-31`) | **[PORT]** | `is_input` + control keys + empty-command-to-poll + no-change-timeout. This is what makes an agent able to babysit a 40-minute simulation instead of timing out. A scientific host needs this more than OpenHands does. |
| 3 | **`BaseWorkspace` interface** (`workspace/base.py:25-261`) | **[PORT]** | ~40-line abstraction over execute/upload/download/git/pause/resume. Copy the shape, not the code (drop `_send_completion_callback`). |
| 4 | **Start-then-poll-with-cursor command protocol** (`remote_workspace_mixin.py:88-172`; `bash_router.py`) | **[PORT]** | A crashed poller resumes from `order__gt` with no output loss. This is the single design choice that makes remote execution restartable, and it maps onto the host's durable-task model exactly. |
| 5 | **Unmatched-action replay as the universal resume primitive** (`state.py:662-697`, `agent.py:643-653`) | **[STUDY]** | Beautiful economy — one mechanism serves confirmation, resume, and crash recovery. But it is at-least-once (§5.4). Take the idea, add idempotency. |
| 6 | **Secret registry: scan-command-then-inject + exported-value masking** (`secret_registry.py:21-60`) | **[PORT]** | Small, self-contained, and solves a problem the host will hit the moment a sandboxed script needs an API key. The "mask values we exported even if the source later fails" detail is the non-obvious part. |
| 7 | **`security_risk` as an injected schema field + separable confirmation policy** (`tool.py:871-875`, `confirmation_policy.py`) | **[STUDY]** | The clean split (model predicts, policy decides, sandbox-vs-CLI tier definitions swap) is worth imitating. Note it is inert without an analyzer. |
| 8 | **Condenser contract** (`llm_summarizing_condenser.py:37-80`) | **[STUDY]** | `keep_first`, `minimum_progress`, retry-with-shrinking-budget, separate LLM with its own `usage_id`. The host already has its own context discipline; take the parameters, not the class. |
| 9 | **`ApptainerWorkspace`** (`apptainer/workspace.py`) | **[STUDY]** | Only if Co-Scientist needs to run on an HPC cluster where Docker is unavailable. Then it is the reference implementation. |
| 10 | **Agent-server, Canvas, cloud workspace, ACP agent, browser tool** | **[SKIP]** | See below. |

**Blunt on what not to take:**

- **The agent-server as a whole** — 25k lines, and it is a product: VSCode router, desktop/VNC router, PostHog telemetry (`telemetry/posthog_exporter.py`), OAuth stores, agent profiles, workspaces, canvas extensions, an OpenAI-compatible shim. You want ~6 endpoints out of ~20 routers.
- **`OpenHandsCloudWorkspace`** (999 lines) — hosted-product surface: git provider clone mappings, repo sources, org workflows. Nothing generic.
- **`acp_agent.py`** (4,279 lines) — enormous, and the protocol is unstable enough at this pin that the repo carries a hard `<0.11` version pin to work around a breaking change.
- **`browser_use` tool** — drags Playwright and the `browser-use` package in. A hypothesis-testing agent needs a shell and files, not a browser.
- **Agent Canvas** — a React app for a chat-with-coding-agent product. The host already has a React UI with its own run-detail model.
- **File-per-event storage + `flock`** — see §8.

---

## 8. Integration notes for a Python / LangGraph / SQLite host

### 8.1 The recommended shape: a sandbox MCP server

The host already has an MCP client (`engine/src/co_scientist/mcp_client.py`) and a reference MCP server (`engine/mcp_server/`), and `docs/ARCHITECTURE.md:56-62` shows MCP as an established optional edge of the engine. The lowest-friction path to "the scientific agent gets a terminal" is therefore:

1. Run `ghcr.io/openhands/agent-server` in Docker (or build a slimmer image) as the sandbox.
2. Write a thin MCP server — modeled on `engine/mcp_server/` — exposing `run_command`, `read_file`, `write_file`, `list_dir` and proxying to `/api/bash/*` and `/api/file/*` with the `X-Session-API-Key` header.
3. Register it in the existing tools config (`TOOLS_CONFIG`), so engine nodes get it through the machinery that already exists.

This gets items 3, 4, and 6 from §7 without importing a single OpenHands Python package. **It is the recommendation.**

The alternative — `pip install openhands-sdk openhands-tools openhands-workspace` and use `BaseWorkspace` directly in-process — is viable and gives you the terminal tool for free, but see the dependency weight below.

### 8.2 Where each [PORT] item attaches

| Item | Attachment point | Friction |
|---|---|---|
| PS1-JSON sentinel | Inside the sandbox MCP server, or a new `engine/src/co_scientist/tools/terminal.py` | Needs a persistent shell. tmux (as OpenHands does) or a long-lived `pty` in the sandbox container. Not hard, but it is a stateful resource whose lifetime must be tied to a run. |
| Long-command interaction | The MCP tool schema | Pure schema + prompt work. The host's existing tool-registry pattern accommodates it. |
| `BaseWorkspace` shape | New module beside `mcp_client.py` | None. It is an interface. |
| Start-then-poll cursor | `app/app/store/` + a new table, or reuse `run_events` | **This is the real integration work.** See §8.3. |
| Secret registry | `app/app/` alongside existing config/secret handling | Low. Self-contained. |

### 8.3 The impedance mismatch: two persistence models

The host is SQLite/WAL, single-writer, with leased task rows carrying `attempt`, `max_attempts`, `lease_owner`, `lease_expires_at`, and an `idempotency_key` (`app/app/store/tasks.py:69-72,107-118,149`), plus expired-lease rescue (`_rescue_expired_leases`, line 329) and `BEGIN IMMEDIATE` leasing (`_try_lease_task`, line 350).

OpenHands is one-JSON-file-per-event plus `flock`, with a 45s TTL file lease.

**The host's model is strictly better for its constraints, and should not be replaced.** Concretely:

- **Do not port `EventLog`.** File-per-event plus a directory scan on open (`event_store.py:50-56`) is worse than the host's existing `run_events` table, and `flock`-on-NFS is explicitly documented as unreliable (`event_store.py:36-40`).
- **Do not port `conversation_lease.py`.** The host's row-level lease with retry budget already subsumes it, and does so transactionally rather than via a TTL file plus a `kill(pid,0)` liveness guess.
- **Map instead.** A sandbox command becomes a durable task row. `start_bash_command` returns a `command_id` → persist it in the task's payload. The worker polls `bash_events/search?order__gt=N` and persists `N` as it advances. On restart, the task resumes from the stored `command_id` and cursor — no output lost, no re-execution.

That last point is the payoff, and it is why item 4 is a [PORT] rather than a [STUDY]: it converts "long-running command" from something that dies with the process into something the host's existing durable queue already knows how to survive. It also **sidesteps the at-least-once hazard of §5.4** — because the host re-attaches to the running command by id rather than re-issuing it.

### 8.4 Honest friction points

1. **At-least-once execution (§5.4).** If you adopt the SDK wholesale, an interrupted tool call re-runs. For a research agent whose tool calls may be expensive or data-mutating, this is a correctness issue, not a performance one. The `command_id` re-attachment in §8.3 is the fix, and it requires not using the SDK's own conversation loop.

2. **Dependency weight.** `openhands-sdk` pulls `litellm`, `fastmcp>=3.0.0`, `agent-client-protocol`, `tree-sitter` + `tree-sitter-bash`, `pillow`, `joserfc`, `lmnr` (Laminar observability), and **`fakeredis[lua]`** — the last as an explicit dependency for "docket/fastmcp background tasks". `openhands-tools` adds `browser-use>=0.8.0` (Playwright), `libtmux`, `func-timeout`, `tom-swe`, `binaryornot`, `cachetools`. `openhands-workspace` depends on `openhands-agent-server`, which itself declares `docker`, `fastapi`, `openai`, `sqlalchemy`, `alembic`, `aiosqlite` (the last three unused — §5.1).

   **This is a lot of surface for a host that today needs a shell.** The MCP-server approach (§8.1) confines all of it to a container image.

3. **One genuine compatibility win: LiteLLM.** The SDK dispatches through `litellm.completion` / `litellm.acompletion` (`sdk/openhands-sdk/openhands/sdk/llm/llm.py:44-52,2153,2181`) — the same layer as the host (`AGENTS.md`, "Both projects use LiteLLM for model dispatch"). Provider config, model naming, and cost accounting would line up rather than fight. If the host ever *did* adopt the SDK's agent loop, this removes what would otherwise be the biggest obstacle.

4. **No resource or egress limits (§1.3).** Whatever path you choose, you add `--memory`, `--cpus`, `--pids-limit`, and a network policy yourself. For a sandbox running LLM-generated code against real data, this is not optional. It is also cheap — a few flags in whatever launches the container.

5. **Churn risk is real.** The repo split (monolith → SDK + canvas) happened recently enough that the pinned canvas README still coexists with a `minimumAgentServer` of 1.28.0 while pinning 1.42.1 — a 14-minor-version compatibility window. `agent-client-protocol` needed an emergency `<0.11` pin. Treat any OpenHands API as unstable across minor versions, and prefer copying ~100-line mechanisms (items 1, 2, 6) over depending on packages.

6. **Stuck-detection defaults assume software engineering** (§2.6). A research agent that runs the same fit across 20 parameter sets looks "stuck" by the repeating-action heuristic. Re-tune or disable.

---

## Verification notes

- Every claim above cites a file I opened at the stated pin. Where I could not confirm something, I said so.
- Not examined in depth (out of scope for the questions asked, flagged rather than guessed): the internals of `file_editor`'s history/undo store, `apply_patch`'s patch format, the `browser_use` tool, the `openai/` compatibility router, `telemetry/*`, `desktop_service.py`/`vscode_service.py`, and the `defense_in_depth` / `grayswan` analyzers beyond their existence and role. The `event/` package's discriminated-union serialization details were inferred from usage in `event_store.py` and `state.py` rather than read exhaustively.
- Tool dispatch (§2.3) was read at `agent.py:571-634`, `agent.py:1334-1396`, and `parallel_executor.py:1-70,98-174`. The `_ActionBatch` helper (`agent.py:186`) was read only through its call sites, not line by line.
- The SDK clone lives in the **session scratchpad and is ephemeral** — it will not survive this session. To reproduce any `sdk/…` citation: `git clone https://github.com/OpenHands/software-agent-sdk && git checkout v1.42.1` (commit `167c1f92`). Neither the target repo nor the host repo was modified; `git status` in the target checkout is clean.
