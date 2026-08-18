# Pi Agent (Rust) — execution-harness analysis

**Target:** `/Users/guy/Code/co-scientist/references/harness/pi_agent_rust` @ `2861aa83e87d136837085fdee4e4f9694ca4ed6f`
**Host we are adapting toward:** `/Users/guy/Code/co-scientist` (Python, LangGraph engine + FastAPI/SQLite durable task queue)
**Scope:** what Pi's harness actually does, verified by reading source. Every claim carries `path:line`.
**Read strategy:** the repo is ~833k lines of Rust. I read `src/tools.rs` (18k lines), `src/agent.rs` (14.8k), `src/plan.rs`, `src/subagents.rs`, `src/session*.rs`, `src/compaction.rs`, `src/permissions.rs`, `src/workspace_trust.rs`, `src/cli.rs`, `src/app.rs` by outline + targeted ranges. I deliberately did not read `extensions_js.rs` (35k), `extension_dispatcher.rs`, `swarm_*`, `doctor.rs`, `auth.rs`, provider internals, or the TUI — none of them answer the seven questions.

---

## 0. Headline finding, stated up front

**Pi has no sandbox.** There is no seatbelt/`sandbox-exec`, no Landlock, no bubblewrap/nsjail, no namespaces, no container, no seccomp, and no `setrlimit`/cgroup applied to agent-authored code. `grep -rn "seatbelt|sandbox-exec|landlock|bubblewrap|nsjail|firejail" src/` returns zero hits; every `sandbox` hit in `src/` is either an OAuth hostname (`src/auth.rs:75`), a test fixture helper (`src/auth.rs:10872`), or the **QuickJS interpreter used for JS *extensions*** (`src/extensions_js.rs:15629`, `src/extension_preflight.rs:1154-2036`) — which is a plugin sandbox, not a sandbox for the agent's bash tool. `src/resource_governor.rs` sounds like a limiter but is admission control / concurrency capacity planning for multi-agent "swarm" runs (`src/resource_governor.rs:1105 SwarmAdmissionController`, `:44 HostResourceBudgets`); it observes cgroup values on Linux for *planning* (`src/doctor.rs:1850`) and never sets one.

The bash tool runs `/bin/bash -c <command>` as a direct child of the agent process, with the agent's full environment and full user privileges (`src/tools.rs:6144-6163`). The only isolation is a **process group** so the tree can be killed (`src/tools.rs:6159`), and a **path scope check applied to the file tools only, never to bash** (`src/tools.rs:2752`).

So for the stated goal — *give the scientific agent its own sandboxed terminal so it can run code against real data* — Pi supplies the **harness** (loop shape, tool contracts, iteration budgets, output spillover, effect-typed scheduling, session compaction). The **sandbox must come from somewhere else** (Docker/Firecracker/gVisor, or a remote exec service). Do not read this repo expecting to find one.

---

## 1. EXECUTION SUBSTRATE

### Process model

`run_bash_command` (`src/tools.rs:6107-6420`) is the whole substrate:

- **Shell selection** — `shell_path` from config, else first existing of `/bin/bash`, `/usr/bin/bash`, `/usr/local/bin/bash`, else `sh` (`src/tools.rs:6141-6147`).
- **Command wrapping** — an optional configured `command_prefix` is prepended, then the whole thing is wrapped in `trap 'code=$?; wait; exit $code' EXIT` (`src/tools.rs:6122-6126`). That `wait` is load-bearing: it makes the shell block on background children before exiting, so a `cmd &` doesn't orphan a process that keeps the pipe open.
- **Spawn** — `bash -c <command>`, `current_dir(cwd)`, `stdin(Stdio::null())`, stdout/stderr piped (`src/tools.rs:6149-6157`). stdin being null is why no agent command can ever hang on an interactive prompt.
- **Process group** — `isolate_command_process_group(&mut cmd)` (`src/tools.rs:6159`) puts the shell in its own pgid; `ProcessGuard::new(child, ProcessCleanupMode::ProcessGroupTree)` (`src/tools.rs:6178`) guarantees a **tree kill** on drop, timeout, or cancellation.

### Isolation / filesystem boundary

- **bash: none.** No scope check is applied to the command string at all. `run_bash_command` sets `current_dir` and nothing more (`src/tools.rs:6153`). `cd /`, `rm -rf ~`, `curl | sh` are all reachable.
- **file tools: `enforce_cwd_scope`** (`src/tools.rs:2752-2763`) — canonicalize both path and cwd via `safe_canonicalize`, then `canonical_path.starts_with(canonical_cwd)`. Used by `edit` (`:7227`), `write` (`:7589`), `grep` (`:8321`), `hashline_edit` (`:11364`).
- **read is wider**: `enforce_read_scope` allows cwd **plus the global agent dir** (`src/tools.rs:4098-4123`), so the agent can read its own config/agent definitions.
- **Symlinks are resolved, not refused.** `safe_canonicalize` (`src/extensions.rs:1384-1409`) fully canonicalizes when the path exists; for a not-yet-existing path it anchors on the longest existing ancestor and normalizes `..`. So a symlink *inside* cwd pointing outside is correctly rejected (it canonicalizes out of scope) — this is the right design and worth copying.
- **TOCTOU hardening on the read path is unusually thorough** and is the single most over-engineered-looking piece that is actually correct: `open_regular_file_for_capped_read` (`src/tools.rs:1717-1793`) canonicalizes once, snapshots metadata, re-opens with `O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, then compares `(dev, ino)` between snapshot and opened handle and errors "changed while opening" on mismatch (`src/tools.rs:1683-1696`, `:1765-1771`). `NONBLOCK` specifically prevents a regular-file→FIFO swap from hanging the agent. Directory scans pin an fd (`ScopedScanRoot`, `src/tools.rs:2765-2801`) and on Linux do fd-relative IO through `/proc/self/fd/N` (`:2778-2786`), with an explicit comment that macOS/BSD `/dev/fd/N` cannot be traversed so it falls back to the logical path.

### Network policy

None at the process level. `web_search` declares `ToolEffects::network()` (`src/web_search.rs:1098`) and the `read` tool can fetch `http(s)` URLs (`src/tools.rs:5589-5592`) gated only by an `url_allow_private_targets` config flag (`src/tools.rs:5199-5204`) — i.e. SSRF-to-private-ranges is off by default for *that tool*. Bash has unrestricted network.

### Resource limits

- **Wall clock**: bash default timeout **120s** (`DEFAULT_BASH_TIMEOUT_SECS`, `src/tools.rs:258`), overridable per call, `timeout: 0` disables entirely (`src/tools.rs:6118-6122`). On timeout: `terminate_process_group_tree(pid)` then a **5s grace** (`BASH_TERMINATE_GRACE_SECS`, `src/tools.rs:260`) before hard kill (`src/tools.rs:6228-6243`).
- **Output**: truncated to last 2000 lines / 1MB (`DEFAULT_MAX_LINES`, `DEFAULT_MAX_BYTES`, `src/tools.rs:225`, `:228`); spill file hard-capped at **1 GiB** explicitly to prevent disk-exhaustion DoS (`BASH_FILE_LIMIT_BYTES`, `src/tools.rs:264`).
- **Memory**: no rlimit. Instead **backpressure**: a bounded `sync_channel(1024)` between the pipe-pump threads and the async drain loop, so when the agent can't keep up the pump blocks on `send()`, the OS pipe buffer fills, and the child's `write()` blocks — pausing the child rather than OOMing the agent (`src/tools.rs:6180-6187`, comment is explicit about this). This is a genuinely good technique.
- **Threads**: the pipe pumps are **dedicated OS threads, not the blocking pool** (`src/tools.rs:6189-6198`), with a documented rationale — a long-lived bash tool blocking forever on `read()` would otherwise exhaust the shared blocking pool and starve SQLite/FS work. Directly relevant to a Python host with a bounded executor.
- **Write/edit** capped at 100MB (`WRITE_TOOL_MAX_BYTES`, `src/tools.rs:252`); read at 100MB (`READ_TOOL_MAX_BYTES`, `src/tools.rs:249`).

### Lifecycle & state persistence between steps

There is **no session container**. `cwd` is fixed per `ToolRegistry` construction (`src/tools.rs:5185`) and per-process. Each bash call is a **fresh shell**: no env vars, no `cd`, no shell functions survive between tool calls. The only cross-call state is (a) the filesystem, and (b) the optional `shell_command_prefix` replayed into every invocation (`src/tools.rs:6122-6125`) — which is the sanctioned way to get "always `source venv/bin/activate` first" behaviour.

Subagents are the only other process model: `ChildRunner::run_child_process` (`src/subagents.rs:780-830`) spawns a **separate `pi` binary** with `current_dir(cwd)`, `stdin(null)`, piped stdout/stderr, inheriting the parent env (explicitly noted at `src/subagents.rs:817-819` — including API keys), plus `PI_SUBAGENT_DEPTH`. Depth capped at 3 (`src/subagents.rs:30`), parallel fan-out capped at 8 (`src/subagents.rs:28`), and children do **not** receive the `subagent` tool (`src/subagents.rs:239-243`).

---

## 2. AGENT LOOP

The core is `Agent::run_loop` (`src/agent.rs:1748-1940`). Structure, in order:

1. **`AgentStart` event**, then all prompt messages are pushed and echoed as `MessageStart`/`MessageEnd` (`src/agent.rs:1769-1785`).
2. **Steering drain at the turn boundary** (`src/agent.rs:1787`).
3. **Outer loop** = follow-up messages; **inner loop** runs `while has_more_tool_calls || !pending_messages.is_empty()` (`src/agent.rs:1789-1793`).
4. Per turn: emit `TurnStart`, flush pending messages into history, check abort, then `stream_assistant_response` (`src/agent.rs:1866`).
5. Extract tool calls (`src/agent.rs:1963`); if none, the turn ends and the loop breaks unless a follow-up is queued (`src/agent.rs:2158-2166`).

### Turn termination conditions

- No tool calls in the assistant message → inner loop exits (`has_more_tool_calls = false`, `src/agent.rs:1966-1968`).
- `StopReason::Error | StopReason::Aborted` → return immediately with `AgentEnd { error }` (`src/agent.rs:1930-1955`).
- **Iteration cap**: `max_tool_iterations`, default **50** (`MAX_TOOL_ITERATIONS_DEFAULT`, `src/agent.rs:532`), ceiling 1000 (`:539`), env override `PI_MAX_TOOL_ITERATIONS` (`src/agent.rs:566-575`), invalid values clamp rather than fail. Exceeding it converts the assistant message to `StopReason::Error` **and strips dangling `ToolCall` blocks** so the next user prompt doesn't hit a provider sequence mismatch (`src/agent.rs:2033-2036`) — a real bug class, worth copying.
- **`pause_turn` budget**: Anthropic's resumable server-tool stop is re-submitted verbatim (no synthetic user message) at most 3 times (`MAX_PAUSE_TURN_CONTINUATIONS`, `src/agent.rs:547`; logic `src/agent.rs:1969-1993`).

### The soft-handoff steering message — the best single idea in the loop

At **≥80% of the iteration cap** (`ITERATION_WARN_NUMERATOR/DENOMINATOR = 4/5`, `src/agent.rs:553-554`; suppressed below cap 5, `:559`), the runtime injects a **one-shot user-role steering message** telling the agent to stop starting new work and write a handoff envelope (`iteration_handoff_steering_text`, `src/agent.rs:648-659`; injection at `src/agent.rs:2004-2024`). It goes on the *steering queue*, so it is observed **before the agent's next assistant turn**, not after the cap fires. Instead of being silently killed at the ceiling, the agent gets to land the plane.

### Tool dispatch — effect-typed batching

Each `Tool` declares coarse effects (`src/tools.rs:42-158`): `READ|WRITE|APPEND|NETWORK|PROCESS` bitflags, with `BARRIER = WRITE|APPEND|PROCESS` (`src/tools.rs:47-52`). `parallel_safe()` is `bits != 0 && bits & BARRIER == 0` (`src/tools.rs:150`) — so **only read and network tools ever run concurrently**; anything mutating or spawning is a serialization barrier. Crucially the trait default is `ToolEffects::write()` (`src/tools.rs:191-194`) — **undeclared tools fail closed into serial execution**.

`plan_tool_effect_batches` (`src/agent.rs:442-467`) greedily groups *contiguous* calls whose effects are mutually compatible, preserving model-emitted order. `execute_tool_calls` (`src/agent.rs:3153-3305`) then:
- **Phase 1** emits `ToolExecutionStart` for *all* calls up front, before any run (`src/agent.rs:3163-3169`) — so the UI shows the full fan-out immediately.
- **Phase 2** runs batches; within a batch, `buffer_unordered(parallelism)` with a host-scaled cap (`compatible_tool_parallelism_limit`, `src/agent.rs:117-131`; `PI_MAX_CONCURRENT_COMPATIBLE_TOOLS` override, clamped, invalid values warn+ignore). **Results are re-sorted by original index** before recording (`src/agent.rs:3216`), so the transcript is deterministic regardless of completion order.
- **Phase 3** walks calls in order and materializes results, skips, or aborts.

`tool_effect_batch_plan_evidence` (`src/agent.rs:491-561`) emits the batch plan as versioned JSON with a per-batch `barrier_reason` string (`write_barrier`, `process_barrier`, `undeclared_effects_barrier`, …, `src/agent.rs:473-490`). The scheduler explains itself in machine-readable form. Tests assert the batched transcript equals a sequential oracle (`src/agent.rs:4933-5114`).

### Steering / interruption mid-fan-out

Between every batch, `drain_steering_messages()` is checked; if a user message arrived, **remaining tool calls are abandoned** and each gets a synthetic result `"Skipped due to queued user message."` marked `is_error: true` (`src/agent.rs:3186-3191`, `skip_tool_call` at `src/agent.rs:3772-3819`). The provider contract is never violated — every `tool_call_id` gets a result — but the agent immediately sees the user's redirection. `MessageQueue` (`src/agent.rs:867-947`) separates *steering* (delivered at the next boundary) from *follow-up* (delivered when idle), each with `OneAtATime`/`All` modes.

### Error / timeout / abort handling

- A tool that returns `Err` becomes a **tool result** with `content: "Error: {e}"` and `is_error: true` (`src/agent.rs:3651-3660`) — never an exception that kills the turn. Only a provider stream failure aborts (`src/agent.rs:1874-1918`).
- `AbortSignal` (`src/agent.rs:1113-1173`) is checked at the top of each turn, between batches, and `select`-raced against the whole batch future (`src/agent.rs:3133-3145`). Aborted calls still get a recorded result with structured `tool_cancellation_details` (`src/agent.rs:3674-3683`).
- Provider-level retry/failover is separate: `src/failover.rs` classifies 429/quota/overload (`:20-48`), maintains a credential ring with **per-credential exponential backoff** `base * 2^strikes` clamped to max (`src/failover.rs:168-232`), and walks a configured fallback chain.

### Context management

`build_context` (`src/agent.rs:1539`) assembles the request. Compaction is a **separate subsystem** — see §5.

---

## 3. TOOL SURFACE

Default enabled set (`src/cli.rs:468`):
`read, bash, edit, write, grep, find, ls, hashline_edit, web_search, ast_grep, ast_edit, lsp, ask, todo, submit_plan`.
`subagent` is opt-in only (`src/cli.rs:464`). Registry construction: `ToolRegistry::new` (`src/tools.rs:5185-5240`).

| Tool | Effects | Key schema | Guardrails |
|---|---|---|---|
| `read` (`src/tools.rs:5531`) | `read` | `path`, `offset`, `limit`, `hashline` | scope = cwd **+ agent dir** (`:4120`); 100MB cap; TOCTOU-hardened open; `http(s)` paths become reader-mode markdown fetches; images become attachments; truncated 2000 lines/1MB |
| `bash` (`src/tools.rs:6476`) | `process|write` | `command`, `timeout` | **no path scope**; 120s default timeout, `0` disables; 2000-line/1MB truncation with spill file; 1 GiB spill cap; pgroup tree kill |
| `edit` (`src/tools.rs:7175`) | default (`write`) | `path`, `oldText`, `newText` | `oldText` must match **uniquely**; matching normalizes CRLF, Unicode spaces/quotes/dashes, and ignores trailing whitespace (`:7183`); explicit `ensure_effective_mode_access` R+W check before touching (`:7228`); 100MB cap |
| `write` (`src/tools.rs:7542`) | default (`write`) | `path`, `content` | `enforce_cwd_scope`; refuses non-regular files (`:7590`); creates parents |
| `grep` (`src/tools.rs:8225`) | `read` | `pattern`, `path`, `glob`, `ignoreCase`, `literal`, `context`, `limit`, `hashline` | ripgrep backend (or in-process); respects `.gitignore`; 100 matches (`:234`) / 1MB / 500-char lines (`:231`); pinned scan root fd |
| `find` (`src/tools.rs:9015`) | `read` | `pattern`, `path`, `limit` | glob; gitignore-aware; sorted mtime-desc; 1000 results (`:237`), 20k hard scan cap (`:240`) |
| `ls` (`src/tools.rs:9766`) | `read` | — | 500 results (`:243`), 20k hard scan cap (`:246`) |
| `hashline_edit` (`src/tools.rs:11290`) | default (`write`) | `path`, `edits[{op: replace/prepend/append, pos: "N#AB", end, lines}]` | see below |
| `ast_grep` (`src/ast_tools.rs:550`) | — | tree-sitter pattern, `$X` / `$$$X` metavars, `lang` | matches AST not text; 500-char match cap |
| `ast_edit` (`src/ast_tools.rs:1088`) | — | `ops[{pat,out}]`, `action: stage/resolve/reject`, `proposalId`, `reason` | see below |
| `lsp` (`src/lsp.rs:967`) | — | `action` ∈ diagnostics/definition/references/hover/symbols/rename/rename_file/code_actions/… | project-wide lookups **error** rather than guess when `symbol` is omitted |
| `web_search` (`src/web_search.rs:1071`) | `network` | `query`, `provider`, `site`, `after`, `limit` | ranked provider chain with circuit breaker, keyless fallbacks |
| `todo` (`src/todo.rs:480`) | `read` (session-state only) | `op` ∈ init/start/done/drop/block/unblock/rm/append/view | tasks addressed by **exact content string, no ids**; completing auto-promotes earliest open; completed never revert; persists with session and forks with branches |
| `ask` (`src/ask.rs:478`) | — | 2–5 mutually-exclusive options, `recommended` index | non-interactive sessions auto-select the recommended option (or error, per `ask_policy`) |
| `subagent` (`src/subagents.rs:191`) | `process` | `agent`+`task`, or `tasks[]` (parallel ≤8), or `chain[]` with `{previous}` / `{{previous.data.<path>}}`, `outputSchema`, `schemaMode: permissive/strict` | depth ≤3; children lack `subagent` |

### Three non-obvious implementations that matter

**(a) Hashline addressing** (`src/tools.rs:11010-11070`). `read`/`grep` with `hashline: true` prefix every line with `N#AB` — 1-indexed line number plus a 2-char tag. The tag is `xxh32(line_with_all_whitespace_removed) & 0xFF`, nibble-encoded; the seed is `0` when the line contains any alphanumeric, else the **line index** (so blank and punctuation-only lines still disambiguate) (`src/tools.rs:11030-11046`). `hashline_edit` then addresses edits by anchor, **re-validates every anchor against the current file hashes**, and applies **bottom-up so earlier indices stay valid** (`src/tools.rs:11290-11303`, `:11191-11256`). This is a cheap, whitespace-insensitive optimistic-concurrency token for line-addressed editing — no diff, no fuzzy matching, and it catches "the file changed under me."

**(b) Staged structural rewrite** (`src/ast_tools.rs:1096`). `ast_edit action=stage` writes **nothing** — it returns a `proposalId`, a replacement count, and per-file diff previews. `action=resolve` re-hashes every file at apply time; **any** change since staging rejects the **whole** proposal naming the offending file; writes are temp-file + rename per file with rollback on mid-failure. A two-phase commit for model-authored edits.

**(c) Tool-output artifact spillover with redaction** (`src/tools.rs:266-274`, `:1044`, `:1175-1290`, `:1647-1676`). Output past the preview threshold is written to a session-scoped artifact (`pi.tool_output_artifact.v1`, retention class `session_scoped_temp_evidence`), the model sees a preview plus a pointer, and the artifact is **redacted before persisting**: `key=value` secrets, `Bearer` tokens, and bare token-shaped values are replaced with `[REDACTED]`, producing a structured summary `{policy, status: clean|redacted|unsafe, redacted_count, fields[], raw_secret_bytes_emitted}` (`src/tools.rs:1224-1244`). If `raw_secret_bytes_emitted > 0` the write is **refused with an error** rather than persisted (`src/tools.rs:1277-1281`). Redaction caps at 64MB, artifacts at 1GB (`src/tools.rs:271-274`).

**(d) Content-fingerprinted tool-output cache** (`src/tools.rs:1678-1683`, `:2140-2170`). Key is `tool\0cwd\0input_json` (`:2140`); an entry is only served if its recorded **file dependencies** still fingerprint identically (`:2150-2153`). Outputs carrying an artifact are never cached (`:2159-2165`). 128 entries / 8MB. Side-effect tools (`write`, `edit`, `bash`) are structurally excluded (`:2146-2148`).

---

### Tool-schema tiering (`src/xdev.rs`) — relevant to the host's token budget

Because "sending every tool's full JSON schema on every provider request costs thousands of tokens per turn and measurably degrades model tool-selection" (`src/xdev.rs:3-6`), tools are split into **Essential** (always in the schema — read/write/edit/bash/grep/find/ls/hashline_edit/ask/todo/xdev/web_search/submit_plan, `src/xdev.rs:59-75`) and **Discoverable** (out of the schema entirely; advertised only as a one-line index in the system prompt and reached through a single `xdev` dispatcher tool that can `list`/`describe`/`run`/`promote`, `src/xdev.rs:8-16`). `xdev run` delegates through the normal execution path so effects, approval and logging are preserved (`src/agent.rs:3600-3607`, `src/xdev.rs:13-14`); `promote` moves a tool into the live schema **mid-session without a restart**. `subagent` is `OPT_IN_ONLY` — never default, never discoverable — precisely because it spawns processes (`src/xdev.rs:77-79`).

## 4. PERMISSION / SAFETY MODEL

There are **two disjoint systems**, and the one you would expect — a Claude-Code-style allow/deny/ask rule engine over tool calls — **does not exist**.

### 4.1 Extension capability policy (a real engine, wrong subject)

`ExtensionPolicy` (`src/extensions.rs:2055-2073`): mode `Strict|Prompt|Permissive` (`:2040-2044`), global `default_caps`/`deny_caps`, plus `per_extension` overrides (`:2016-2032`). Precedence, implemented in `evaluate_for` (`src/extensions.rs:9137-9227`) and documented at `:9105-9123`:

1. per-extension `deny` → Deny (`:9150-9162`)
2. global `deny_caps` → Deny (`:9163-9174`)
3. per-extension `allow` → Allow (`:9176-9188`)
4. global `default_caps` → Allow (`:9190-9194`)
5. mode fallback: Strict→Deny, Prompt→Prompt, Permissive→Allow (`:9198-9226`)

Matching is **exact, case-insensitive string equality** on the capability name (`:9157`, `:9168`, `:9183`) — no globs, no regex, no wildcards. Empty capability fails closed (`:9142-9149`).

**This gates extension hostcalls (`pi.exec`, `pi.env`, `pi.http`) only. It does not touch the agent's own `bash`/`edit`/`write` tools.**

`src/permissions.rs` (1494 lines) is, despite the name, purely a **persisted decision cache** for extension capability prompts: `(extension_id, capability) → PersistedDecision {allow, decided_at, expires_at, version_range}` (`src/permissions.rs:1-6`, `:30-49`), stored at `<global_dir>/extension-permissions.json` (`src/config.rs:628-630`), written atomically at `0o600` under a process mutex plus an `fs4` file lock (`src/permissions.rs:219-308`).

### 4.2 Agent tool approval — a hook that nothing wires up in the CLI

`ToolApprovalDecision` is **binary**: `Allow | Deny { reason }` (`src/agent.rs:704-707`). No "ask", no rules, no `always`/`session` scopes at this layer. The gate is the first `await` inside `execute_tool` (`src/agent.rs:3375-3377` → `request_tool_approval`, `:3419-3455`):

- Handler is `None` → returns `None` immediately and the tool runs. **Absence of a handler is allow** (`src/agent.rs:3424-3426`).
- `Deny` → a synthetic `is_error: true` tool result `"Tool execution denied: {reason}"` (`src/agent.rs:3728-3747`), and extension `tool_call` hooks are skipped (`:3389-3391`).

**Every install site passes `None` except ACP**: `src/main.rs:1677` (CLI, feeding both interactive and print mode at `:2123`/`:2141`), `src/sdk.rs:1870`, `:2273`, `:2439`. Only `src/acp.rs:1376-1377` installs a real handler, driven by an editor over JSON-RPC `session/request_permission` with exactly two options, `allow-once` / `reject-once` (`src/acp.rs:153-154`, `:1029-1062`). That path is rigorously **fail-closed**: reject, unknown optionId, missing optionId, cancellation, malformed response, timeout, closed channel, client disconnect, and even a poisoned registry lock all map to `Deny` (`src/acp.rs:1065-1086`, `:261`, `:270`, `:281-283`).

The four-mode prompt (`AllowOnce/AllowAlways/Deny/DenyAlways`, `src/interactive/state.rs:551-582`) with a 30-second auto-deny countdown (`:628`) exists — **for extension capabilities only**, persisting through `PermissionStore::record` when `is_persistent()` (`src/interactive/keybindings.rs:99-115`).

### 4.3 What is actually blocked by default: essentially nothing

The startup default profile is **permissive** (`src/config.rs:1044-1049`, `:1073`; stated explicitly at `src/main.rs:944-948` with the rationale "Fresh installs favor extension compatibility and custom UI out of the box"). `PolicyProfile::Permissive.to_policy()` is `deny_caps: []` (`src/extensions.rs:1993-2001`) — so `exec` and `env` are allowed and nothing prompts.

The only default block list anywhere is exec-mediation's **Critical tier** — `RecursiveDelete, DeviceWrite, ForkBomb, DiskWipe, ReverseShell` (`src/extensions/exec_mediation.rs:29-42`, threshold at `:70-80`) — and it applies to **extension `pi.exec`, not the agent's `bash`**. High tier (`PipeToShell`, `SystemShutdown`, `PermissionEscalation`, …) is allowed silently at the default threshold.

Non-default profiles do more: `safe` = Strict + `deny_caps: ["exec","env"]` + High threshold (`src/extensions.rs:1975-1991`, `src/extensions/exec_mediation.rs:60-68`); `balanced` = Prompt + same deny caps + `audit_all_classified: true` (`src/extensions.rs:2075-2092`). `allow_dangerous` strips `exec`/`env` from the deny list with a warning and an audit record (`src/config.rs:1113-1153`).

### 4.4 The exec classifier is prefix/substring matching, and it does not parse shells

`evaluate_exec_mediation` (`src/extensions.rs:998-1063`): `allow_patterns` (case-insensitive **prefix**) beats `deny_patterns` (same) beats the built-in classifier. `normalize_command_for_classification` (`src/extensions/exec_mediation.rs:95-173`) collapses whitespace, rewrites `$IFS`, strips quotes (explicitly to defeat `r"m" -rf /`, comment at `:125`), and unescapes — but there is **no splitting on `&&`, `||`, `;`, `|`, `$()`, or backticks**. Classifiers are `contains`/`starts_with` over the whole normalized string (`:175-329`). Consequences, both structural:

- a head-anchored `allow_patterns` entry allows everything after `&&`;
- a head-anchored `deny_patterns` entry is evaded by `true && <denied>`;
- classifier patterns are literal-fragile — `classify_recursive_delete` requires the substrings `" /"`, `" ~/"` (`:190-191`), and `classify_pipe_to_shell` requires a literal `curl `/`wget ` plus one of 16 hardcoded pipe strings (`:236-255`), so `aria2c`, `fetch`, or a novel pipe spelling is unmatched.

Extension exec at least spawns **without a shell** (`Command::new(&cmd).args(&args)`, `src/extensions.rs:17279`, `:17444`), so metacharacters inside one arg are inert. The agent's `bash` tool spawns *with* a shell and no classifier at all.

### 4.5 Path restrictions

Covered in §1. Summary: `enforce_cwd_scope` canonicalize-then-prefix for `edit`/`write`/`grep`/`find`/`ls`/`hashline_edit` (`src/tools.rs:2752-2761`, callers `:7227`, `:7589`, `:8321`, `:9084`, `:9830`, `:11364`); `enforce_read_scope` widens `read` to cwd **or** the agent dir, with the tradeoff argued in the doc comment at `src/tools.rs:4083-4096` — *"broadening write access would let a misbehaving model persist instructions into the agent dir."* Symlinks resolve before the check, so symlink escape is closed. `resolve_read_path`'s macOS filename-variant probing only touches the filesystem when the path is already inside cwd (`src/tools.rs:2707-2711`) — an explicit anti-probe measure. **`bash` is exempt from all of it.**

### 4.6 Workspace trust — the best-designed gate here, and it is not about the model

`src/workspace_trust.rs:1-25` is explicit that this gates **deterministic configuration execution controlled by whoever authored the repository**, not model output. It scans `.pi/settings.json` plus everything under `.pi/extensions/` (`:70-134`, `:145-178`), computes a SHA-256 over a canonical sorted `path\tsha256(content)` manifest (`:104-132`), and keys the decision on `(canonical workspace path, digest)` so **any content change re-prompts** (`:306-311`, test `:653-684`). Resolution order (`establish`, `:315-397`): env var `PI_WORKSPACE_TRUST` (wins even over `--trust`, never persisted) > `--trust` (persisted) > `trustAllWorkspaces` **from global settings only** > stored decision with matching digest > interactive prompt > **non-interactive fails closed, nothing persisted**. The global-only rule is enforced at `src/main.rs:1240-1244` with the reason spelled out: *"a project file granting itself trust would defeat the gate."* A corrupt trust store is treated as empty so it can never grant trust (`:210-222`). Untrusted → `load_global_only()`, project settings and project packages skipped (`src/main.rs:1257-1270`, `src/config.rs:702-721`).

### 4.7 Secret handling

- **`SecretBrokerPolicy`** (`src/extensions.rs:283-298`, defaults `src/extensions/exec_mediation.rs:348-391`): suffix list (`_KEY`, `_SECRET`, `_TOKEN`, `_PASSWORD`, `_CREDENTIAL(S)`, `_API_KEY`, `_PRIVATE_KEY`, …), prefix list (`SECRET_`, `AUTH_`, `CREDENTIAL_`), 16 exact names, `[REDACTED]` placeholder; `is_secret` at `:396-434`. Applied to extension `pi.env` reads (`src/extensions.rs:16921`) — with an acknowledged gap: **no per-extension env allowlist yet** (`src/extensions.rs:16906-16908`).
- **Command logging**: `redact_command_for_logging` (`src/extensions.rs:1073-1116`) strips `-p/--password <val>` and `KEY=VALUE` where `is_secret(KEY)`; commands are then stored only as a SHA-256 (`:16712`), with the ledger field doc stating *"never log raw command"* (`:307-308`).
- **Artifact redaction** (`src/tools.rs:1147-1173`, `:1185-1245`): three regexes (sensitive `key=value`, `Bearer <token>`, `sk-…`/`gh[pousr]_…`/`AKIA…`), and `redact_tool_output_artifact_bytes` **fails closed** — residual secret bytes return `InvalidData` instead of writing (`:1273-1288`).

**Critical caveat:** none of this touches the **inline tool output returned to the model**. `BashTool::execute` returns `result.output` unmodified (`src/tools.rs:6560-6566`). `bash env` or `cat .env` hands the model every credential verbatim. Redaction protects the artifact store and the logs, not the transcript.

## 5. SESSION & STATE

### 5.1 Format and layout

**JSONL is authoritative**, version 3, and any other version is hard-rejected on open (`SESSION_VERSION`, `src/session.rs:43`; `validate()` at `:5959-5967`). Line 1 is a `SessionHeader` (`src/session.rs:5877-5905`): `id`, `timestamp`, **`cwd`**, `provider`/`modelId`/`thinkingLevel` (plus a fallback triple), **`leafId`** (the active branch tip), and `branchedFrom`. Every subsequent line is a `SessionEntry` (`src/session.rs:6001-6010`), internally tagged on `type`: `message`, `model_change`, `thinking_level_change`, `compaction`, `branch_summary`, `label`, `session_info`, `custom`.

Every entry flattens `EntryBase { id, parentId, timestamp }` (`src/session.rs:6047-6053`). **`parentId` makes the session a tree, not a list** — that single field is the entire branching/fork mechanism, and `leafId` selects the active path.

`SessionMessage` variants (`src/session.rs:6081-6132`): `user`, `assistant` (carries `usage` and `stopReason`), `toolResult { toolCallId, toolName, content, details, isError }`, `custom { customType, … }`, `bashExecution { command, output, exitCode, cancelled, truncated, fullOutputPath }`, `branchSummary`, `compactionSummary`. **There is no separate tool-call record** — calls live inside the assistant message's content blocks and the result is a separate entry joined by `toolCallId`.

Paths: global dir `$PI_CODING_AGENT_DIR` or `~/.pi/agent` (`src/config.rs:1357-1369`); sessions root `$PI_SESSIONS_DIR` or `<global>/sessions` (`src/config.rs:1372-1377`); per-project subdirectory `--Users-guy-Code-foo--` from the encoded cwd (`src/session.rs:6259-6264`); filename `<ts>_<id8>.jsonl` (`src/session.rs:4313-4341`). Sessions are therefore **keyed to the workspace path**. Max line 100MB, validated before write (`src/session.rs:44`, `:177-190`).

Two SQLite users exist and must not be conflated:
- **`src/session_sqlite.rs`** — an *opt-in* alternative session backend behind the `sqlite-sessions` feature (`src/session.rs:2276-2317`). Schema is three tables and **no explicit indexes**: `pi_session_header(id PK, json)`, `pi_session_entries(seq INTEGER PRIMARY KEY, json)`, `pi_session_meta(key PK, value)` (`src/session_sqlite.rs:106-125`) — entries are stored as the same opaque `SessionEntry` JSON, so the record schema is backend-independent. `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000` (`:106-110`, `:61`); all mutations in `BEGIN IMMEDIATE` … `COMMIT` (`:2075`, `:2135`, `:2179`); `close()` checkpoints the WAL (`:99-104`). Runs on a dedicated 16MB-stack thread because the connection futures are `!Send` (`:28-46`).
- **`src/session_index.rs`** — an always-on *derived* index over the JSONL: `sessions(path PK, id, cwd, timestamp, message_count, last_modified_ms, size_bytes, name)` + `meta` (`:471-492`), WAL + `wal_autocheckpoint=1000` (`:374-381`). Updates are **best-effort and never fail the session write** (`:442-467`).

**No versioned migration ladder in either.** No `PRAGMA user_version`; `INIT_SQL` with `CREATE TABLE IF NOT EXISTS` is re-executed on every open specifically so older DBs gain `pi_session_meta` (`src/session_sqlite.rs:2174-2176`), and a missing meta table falls back to computing from entries (`:414-427`). `src/migrations.rs` handles *layout* migrations only (moving stray `.jsonl` into the per-project dir, `:300-350`).

A third, opt-in **V2 sidecar** (`<stem>.v2/` — `segments/`, `index/offsets.jsonl`, `manifest.json`, `checkpoints/`, `migrations/ledger.jsonl`) exists purely as a read accelerator with a SHA-256 hash chain over frames (`src/session_store_v2.rs:1563-1727`, `:1246`). It is fingerprinted against the source JSONL and **marked dirty before any JSONL mutation** (`src/session.rs:1130-1192`, called at `:1335` and `:1506`); stale or corrupt → warn and fall back to a full JSONL parse (`src/session.rs:3418-3448`). Above 10,000 entries it hydrates only the active path (`DEFAULT_V2_LAZY_HYDRATION_THRESHOLD`, `src/session.rs:2820-2871`).

### 5.2 Write model and durability

**Hybrid: incremental append by default, periodic full rewrite.** `should_full_rewrite()` (`src/session.rs:4210-4239`) triggers a snapshot when nothing is persisted yet, the file vanished, the header changed, or **`appends_since_checkpoint >= 50`** (`compaction_checkpoint_interval`, `PI_SESSION_COMPACTION_INTERVAL`, `src/session.rs:2332-2340`). Otherwise only `entries[persisted_entry_count..]` is appended (`:4383-4413`). *(Naming trap: this "checkpoint" is persistence hygiene, unrelated to LLM compaction and unrelated to the V2 `Checkpoint` record.)*

- **Append path** (`src/session.rs:1468-1518`): `O_APPEND` on a verified regular file, `write_all`, then `file.sync_all()` (`:1510`).
- **Snapshot path** (`persist_jsonl_snapshot_locked`, `src/session.rs:1304-1337`): `NamedTempFile` in the same directory, original permissions restored, `sync_all()`, mark V2 sidecar dirty, atomic `persist()` (rename), then **`sync_parent_dir`** (`:1337`, helper at `:213-219`). The parent-directory fsync is the part most implementations omit.
- **Durability is a three-way tunable** — `strict | balanced | throughput`, default `balanced`, from `PI_SESSION_DURABILITY_MODE` / config / CLI (`src/session.rs:2344-2395`) — controlling only whether a shutdown flush happens and whether its failure is fatal. Autosave reports `{flush_started, flush_succeeded, flush_failed, last_flush_batch_size, last_flush_duration_ms, last_flush_trigger}` (`:2427-2444`): the policy is observable, not just configurable.

**When flushes actually happen matters more than the mode.** The user prompt is flushed immediately at turn start (`AutosaveFlushTrigger::Manual`, `src/agent.rs:10856`, `:10945`, `:11028`); assistant messages and tool results are persisted **only at turn end** (`persist_new_messages` → `flush_autosave(Periodic)`, `src/agent.rs:10887`, `:11114-11132`). So a hard crash mid-turn loses the in-flight turn back to the user prompt. **This is the single biggest structural mismatch with the host**, whose whole design commits per node boundary so a restart resumes rather than replays.

**Two different locks for two different jobs.** Per-session files use `flock(2)` on `<file>.lock`, opened `O_NOFOLLOW|O_CREAT` with a dev/ino identity re-check, released on guard drop (`src/session.rs:1526-1530`, `:1593-1705`); both JSONL and SQLite paths take it (`:1355`, `:1476`, `src/session_sqlite.rs:2070`, `:2170`). *Shared* files (session index, `auth.json`, `settings.json`) use a `mkdir`-based **directory lock** implementing Node `proper-lockfile`'s protocol so the Rust and TypeScript implementations interoperate — 10s stale / 5s heartbeat, with a background thread refreshing the lock-dir mtime and marking the lock `compromised` if its identity changes underneath (`src/file_lock.rs:49-52`, `:311-421`; used at `src/session_index.rs:365-366`).

On top of the lock, **both backends re-read and reconcile by entry ID** so a concurrent writer's rows aren't lost: `plan_jsonl_incremental_append` re-opens the file, builds an ID→bytes map, skips already-present entries, **errors on the same ID with a conflicting payload**, merges, and re-sorts parent-before-child (`src/session.rs:1382-1462`, `:1855`). SQLite does the same and verifies `seq` contiguity (`src/session_sqlite.rs:469-519`, `:378-403`).

### 5.3 Crash recovery

- **Unparseable lines are tolerated, not fatal**: each becomes `SessionOpenSkippedEntry { line_number, error }` (`src/session.rs:2688`, populated `:6746-6752`).
- **Orphaned parent links** become `SessionOpenOrphanedParentLink { entry_id, missing_parent_id }` (`:2695-2698`, `:6838-6845`) and surface as user-visible warnings (`:2890-2901`).
- **Torn final line**: on the next append, if the file doesn't end in `\n` (`:1253-1262`), the writer does *not* concatenate. `validate_unterminated_jsonl_rewrite_scope` permits repair **only if corruption is confined to the final line**, else fails closed with *"refusing to rewrite unterminated JSONL … because corruption is not confined to its final line"* (`:1283-1299`); repair is a full atomic snapshot (`:1499-1501`). A complete-but-unterminated record is preserved; one torn record is dropped.
- **There is no orphaned-tool-call repair at session open.** The nearest thing is `revert_incomplete_response()` (`src/session.rs:5185-5220`), which walks back from the leaf and reverts **only trailing assistant entries whose `stop_reason` is `Error` or `Aborted`**, stopping at the first user prompt, completed tool result, or successful assistant. It is called from same-process retry paths (`src/main.rs:7735`, `:7757`, `:7819`, `:7849`; `src/rpc.rs:2609`), always followed by `run_continue_with_abort`, which re-hydrates history from the session path and re-issues **only the failed provider request** — no tool re-execution, no re-billing (`src/agent.rs:11060-11111`). The doc comment frames this precisely: **resume, not replay**.

### 5.4 Compaction

**Trigger.** `maybe_compact` runs at the start of every turn (`src/agent.rs:10834`, `:10906`, `:10989`); `should_compact` is `context_tokens >= context_window - reserve_tokens` (`src/compaction.rs:1028-1039`). Token accounting prefers the provider's **real `usage`** from the most recent non-aborted assistant message and only char-estimates messages after it (`src/compaction.rs:960-1001`; `get_assistant_usage` skips `Aborted`/`Error` at `:942-952`; heuristic is 3 chars/token, images 1200 tokens, `:28-34`). Effective settings come from config plus the selected model's real context window (`src/main.rs:1682-1687`, `src/acp.rs:1382`): `reserve_tokens` default **16384** (`src/config.rs:921-926`), `keep_recent_tokens` default **20000** (`:928-933`). The library-level `ResolvedCompactionSettings::default()` (128k/10240/12800, `src/compaction.rs:70-89`) is only a conservative fallback, with a comment that erring early is safer than erring late (`:76-80`). `/compact` forces it synchronously (`src/agent.rs:9341-9346`, `:9744-9845`); an extension `before_compact` hook may cancel it or supply its own summary, recorded `fromHook: true` (`:9471-9508`).

**Cut-point selection is the part worth stealing.** `find_valid_cut_points` (`src/compaction.rs:1159-1175`) enumerates legal boundaries and **excludes every `toolResult` entry**, so a tool result can never be orphaned from its call. `find_cut_point` (`:1209-1265`) walks backwards accumulating estimated tokens until `keep_recent_tokens` is satisfied, binary-searches (`partition_point`) for the largest valid cut point at or before that index, then walks left to the nearest message-like or compaction boundary. If the cut still lands mid-turn — `is_user_turn_start` accepts a `user` message, a `bashExecution`, or a `branchSummary` (`:1188-1197`) — it is treated as a **split turn** and the turn's prefix is summarized separately with a dedicated prompt and appended as "Turn Context (split turn)" (`:1283`, `:1938-1960`).

**Method: structured LLM summary, folded forward.** `SUMMARIZATION_PROMPT` (`src/compaction.rs:1279`) produces a fixed shape — Goal / Constraints & Preferences / Progress{Done, In Progress, Blocked} / Key Decisions / Next Steps / Critical Context. When a prior summary exists, `UPDATE_SUMMARIZATION_PROMPT` folds it forward with explicit "PRESERVE all existing information" rules (`:1281`, applied `:1851-1856`). `tokens_before` is measured over the *already-compacted* history so compaction never re-triggers on its own summary (`:1795-1807`).

**Nothing is deleted from disk.** The result is a `CompactionEntry { summary, firstKeptEntryId, tokensBefore, details, fromHook }` appended to the tree (`src/session.rs:6196-6206`, `:4784-4809`). Filtering happens at **context-build time**: `to_messages_from_path` finds the last `Compaction` on the path, emits a synthetic user message wrapping the summary in `<summary>` tags, then skips everything until `firstKeptEntryId` (`src/session.rs:5334-5398`). A missing `firstKeptEntryId` warns and keeps everything (`:5378-5384`). The full history stays replayable forever.

**What is deliberately preserved across a compaction:**
- Everything from `firstKeptEntryId` forward, verbatim (`src/session.rs:5361-5389`).
- The prior summary, folded into the new one.
- **Cumulative file-operation state** — `FileOperations { read, written, edited }` (`src/compaction.rs:798-802`), harvested from *successful* tool calls only (`read|grep|find|ls` → read, `write` → written, `edit|hashline_edit` → edited, `:826-866`), carried forward by re-ingesting the previous entry's `readFiles`/`modifiedFiles` (`:1858-1874`), stored in `CompactionEntry.details` and rendered into the summary as `<read-files>` / `<modified-files>` blocks (`:1975-1993`). **This is the mechanism that stops a compacted agent from re-reading files it already read.**
- **The todo list**, structurally: it is a `Custom` entry with `customType = "todo_list.v1"` (`src/todo.rs:14-15`) read from the **full current path** rather than the post-compaction slice (`:429-447`, call site `:540`), and `Custom` entries never enter provider context at all (`src/session.rs:5314-5331`). Task state is immune to compaction by construction, not by special-casing.
- **The system prompt**, because it is agent config re-applied per turn, not a session entry (`src/agent.rs:663`, `:1530-1535`).

**Fallback.** `build_fallback_summary` (`src/compaction.rs:1704-1762`) emits a deterministic, provider-free "Context Checkpoint" of head/tail-truncated excerpts (400 chars each via `truncate_middle` on char boundaries, `:1648`, `:1669-1690`), budgeted to about half the reserve. `compact()` only degrades to it once past the forced threshold; below it the error propagates so a transient rate limit can be retried (`:2005-2042`). `requires_forced_local_compaction` fires at **2× the context window** (`FORCED_LOCAL_COMPACTION_WINDOW_FACTOR`, `:1650-1666`) so a quota outage degrades context quality instead of letting the session grow unbounded (`src/agent.rs:9433-9437`, `:9555-9607`).

**The out-of-band worker** (`src/compaction_worker.rs:1-4`) keeps LLM compaction off the foreground turn path. `maybe_compact` is **two-phase and never blocks** (`src/agent.rs:9401-9537`): phase 1 `try_recv()`s a finished background compaction and applies it now (`:9413-9429`); phase 2, if quotas allow, prepares and `start()`s a new one (`:9431-9535`). Hand-back is a `JoinHandle` awaited only once `is_finished()` (`src/compaction_worker.rs:279-311`). Quotas: 60s cooldown, 120s timeout, 100 attempts per session, counter reset on success, pending task aborted on drop (`:22-38`, `:279-311`, `:389-395`). Admission decisions are serialized as `pi.compaction.admission.v1` with reasons `allowed | pending | session_attempt_limit | cooldown | no_preparation | memory_pressure | provider_degraded | queue_saturated` (`:18`, `:117-155`) — and the memory/provider/queue signals are **passed in by the caller, never probed by the worker** (`:101-107`).

### 5.5 Fork, branch, rewind, "checkpoint"

- **Fork: present.** `plan_fork_from_user_message` (`src/session.rs:4929-4975`) sets the new leaf to the **parent** of the selected user message and returns the selected text for editor pre-fill, so re-submitting produces one branch rather than two consecutive user messages (`:2640-2654`). Exposed via SDK `fork()` (`src/sdk.rs:1035`), RPC (`src/rpc.rs:2111`), and the interactive tree (`src/interactive/tree.rs:242`); provenance lands in the header's `branchedFrom`.
- **Branch: first-class.** `create_branch_from` / `navigate_to` / `reset_leaf` (`src/session.rs:5229-5241`), `sibling_branches` returning `(fork_point_id, Vec<SiblingBranch>)` (`:5407-5425`), and `BranchSummaryEntry` for summarizing a branch you navigated away from, injected into context in `<summary>` tags (`:6211-6220`, `:6344-6364`).
- **Rewind: not present.** `grep -rn "rewind" src/` is empty. The analogs are `revert_last_user_message` (`:5138`), `revert_incomplete_response` (`:5185`), and leaf navigation.
- **"Checkpoint" means three unrelated things**, none of them a user-facing snapshot/restore: JSONL persistence hygiene (full rewrite every 50 appends, `src/session.rs:2331-2340`); the V2 store's integrity `Checkpoint` record used for migration rollback (`src/session_store_v2.rs:1634-1668`); and prose — the compaction summary is *described* to the model as a "context checkpoint summary" (`src/compaction.rs:1279`).

---

## 6. WHAT IS WORTH TAKING — ranked

Ranked by value **to this host**: a Python/LangGraph/SQLite research system that today has essentially no code execution at all — the only `subprocess` call in the entire repo is a fixed Tesseract OCR invocation (`app/app/document_ingest.py:255`).

### 1. [PORT] Effect-typed tool declarations + contiguous batch scheduling
`src/tools.rs:42-158`, `src/agent.rs:442-467`, `:3153-3305`.
Every tool declares `READ|WRITE|APPEND|NETWORK|PROCESS`; only non-barrier effects batch concurrently; **undeclared defaults to `write`, i.e. serial** (`src/tools.rs:191-194`); results are re-sorted into model-emitted order so the transcript is deterministic regardless of completion order (`src/agent.rs:3216`); the plan is emitted as versioned machine-readable evidence with a named `barrier_reason` (`src/agent.rs:473-561`). The host's loop `asyncio.gather`s **all** tool calls unconditionally (`engine/src/co_scientist/llm_tool_loop.py:167`) — fine while every tool is a read-only MCP search, wrong the moment one of them is `bash`. This is the single most important thing to port, and it must land *before* an exec tool does.

### 2. [PORT] Iteration budget with an 80% soft-handoff steering injection
`src/agent.rs:532-559`, `:640-659`, `:2004-2024`.
A hard cap alone produces truncated, wasted work. Injecting a one-shot *user-role* message at 80% of the cap — delivered before the agent's next assistant turn, not after the kill — converts a hard stop into a graceful handoff. The dangling-`ToolCall`-stripping on the stop path (`src/agent.rs:2033-2036`) is part of the same idea and prevents a provider sequence mismatch on the next prompt. The host's loop today raises `RuntimeError` at `max_iterations` (`engine/src/co_scientist/llm_tool_loop.py:355-358`).

### 3. [PORT] Tool-output spillover to a redacted, run-scoped artifact
`src/tools.rs:266-274`, `:1147-1173`, `:1185-1290`, `:1647-1676`.
Model sees a bounded preview (2000 lines / 1MB) plus a pointer; the full output is written to an artifact that is secret-redacted **before** persisting, carries a structured `{policy, status, redacted_count, fields[], raw_secret_bytes_emitted}` summary, and is **refused entirely** if any raw secret bytes would survive (`:1273-1288`). A host running pandas/scanpy against real data will produce megabyte tracebacks and dataframes. Note the gap to close in the port: Pi redacts *artifacts and logs*, not the inline output handed to the model (`src/tools.rs:6560-6566`), so `bash env` leaks every credential into the transcript. Do both.

### 4. [PORT] Compaction that preserves cumulative file-operation state
`src/compaction.rs:798-802`, `:826-866`, `:1858-1874`, `:1975-1993`.
`FileOperations { read, written, edited }` is harvested from **successful tool calls only**, carried forward across every compaction by re-ingesting the previous summary's `readFiles`/`modifiedFiles`, and rendered into the new summary as `<read-files>` / `<modified-files>` blocks. This is what stops a compacted agent from re-reading everything it already read — the difference between compaction that saves tokens and compaction that costs more than it saves. Directly applicable to a host whose per-item LLM costs already multiplied once through an unnoticed fan-out.

### 5. [PORT] Compaction cut-point rules + non-destructive filtering
`src/compaction.rs:1159-1175`, `:1209-1265`, `:1188-1197`, `:1650-1666`; `src/session.rs:5334-5398`.
Four rules worth taking verbatim: (a) `toolResult` entries are **never** valid cut points, so a result can never be orphaned from its call; (b) after satisfying `keep_recent_tokens`, walk back further to a real turn start (a `user` message, a `bashExecution`, or a branch summary) and summarize a split turn's prefix separately; (c) past 2× the context window, fall back to a **provider-free deterministic summary** so a quota outage degrades quality instead of wedging the session; (d) **delete nothing** — write a `CompactionEntry` with a `firstKeptEntryId` and filter at context-build time, so history stays replayable. Also: measure `tokens_before` over the *already-compacted* history so compaction can't re-trigger on its own summary (`:1795-1807`), and prefer the provider's real `usage` over a char heuristic where available (`:960-1001`).

### 6. [PORT] Hashline addressing for file edits
`src/tools.rs:11010-11070`, `:11191-11303`.
`N#AB` = line number + a 2-char whitespace-insensitive `xxh32` tag. Edits are validated against current hashes and applied **bottom-up** so earlier indices stay valid. Optimistic concurrency for model-authored edits in roughly thirty lines of Python, detecting "the file changed under me" without diffing.

### 7. [PORT] Two-phase staged edit (`stage` → `resolve` with re-hash, all-or-nothing)
`src/ast_tools.rs:1096-1098`.
`stage` writes nothing and returns a proposal id plus per-file diff previews; `resolve` re-hashes every file at apply time and rejects the **whole** proposal naming the offending file if anything changed; writes are temp-file + rename per file with rollback on mid-failure. For a research host where a code change gates a hypothesis verdict, an atomic and reviewable apply is worth more than in a normal coding agent. Port the protocol, not the tree-sitter part.

### 8. [PORT] Bounded-channel backpressure + dedicated threads for subprocess output
`src/tools.rs:6180-6198`, and the session-file/durability discipline at `src/session.rs:1304-1337`.
A bounded queue between reader and consumer means an over-productive child blocks on `write()` rather than OOMing the harness. The comment at `src/tools.rs:6189-6198` is the exact warning this host needs: a long-lived blocking read must **not** sit on the shared blocking pool, or it starves the pool SQLite work depends on. Take the atomic-rewrite discipline too — temp file in the same directory, `sync_all`, rename, then **fsync the parent directory** (`src/session.rs:1327-1337`).

### 9. [PORT] Plan mode as an effect gate, not a prompt convention
`src/plan.rs:1-12`, `:257-278`, `src/agent.rs:3584-3597`.
`Planning`/`PendingApproval` reject any tool whose effects intersect the barrier set, returning a structured `[PLAN_MODE_BLOCKED]` message the model can act on. The elegant part is that **one** effect vocabulary drives parallelism, plan-mode gating, and (in a host port) the approval gate — one declaration, three enforcement points.

### 10. [PORT] Tool-schema tiering (Essential / Discoverable / Off)
`src/xdev.rs:1-100`.
Keep the provider schema small; advertise the rest as a one-line index behind a single dispatcher tool that can `list`/`describe`/`run`/`promote` — with `run` delegating through the normal execution path so effects and approval still apply. The host has documented history of blowing token budgets on oversized schemas; this is a direct mitigation. And `OPT_IN_ONLY` for process-spawning tools (`src/xdev.rs:77-79`) is the right default posture for an exec tool.

### 11. [STUDY] Out-of-band compaction with an admission-decision record
`src/compaction_worker.rs:1-4`, `:18`, `:22-38`, `:101-155`, `:279-311`; `src/agent.rs:9401-9537`.
Compaction runs on a background task; the turn loop only ever `try_recv()`s a *finished* result and applies it, then optionally starts a new one — so no turn ever blocks on summarization. Quotas (60s cooldown, 120s timeout, 100 attempts/session, counter reset on success, task aborted on drop) and a serialized `pi.compaction.admission.v1` decision with named refusal reasons make the scheduler auditable. Crucially, **memory/provider/queue pressure signals are passed in by the caller, never probed by the worker** (`:101-107`) — the right seam. STUDY rather than PORT only because the host's equivalent would naturally be another durable task row rather than a `JoinHandle`; the *shape* is directly reusable.

### 12. [STUDY] Keep task state out of provider context by construction
`src/todo.rs:14-15`, `:429-447`; `src/session.rs:5314-5331`.
The todo list is a `Custom` session entry read from the **full current path**, and `Custom` entries never enter the provider transcript at all. Task state therefore survives compaction with no special-casing — it was never in the thing being compacted. The generalizable rule: durable agent state belongs in a record class the context builder structurally ignores, not in a message you remember to preserve.

### 13. [STUDY] Workspace trust: TOFU keyed on `(canonical path, content digest)`
`src/workspace_trust.rs:1-25`, `:104-132`, `:315-397`; `src/main.rs:1240-1244`.
Not directly portable — the host has no `.pi` directory and no interactive prompt — but the shape transfers to any "may this run's inputs execute code" question: hash the exact surface that could execute, key the decision on it so any edit re-prompts, refuse to let the trusted artifact grant itself trust (global settings only), fail closed when non-interactive, and treat a corrupt trust store as empty. The template to reach for if the host ever accepts user-supplied analysis scripts or datasets carrying code.

### 14. [STUDY] Steering queues with named delivery boundaries, and the "every tool_call_id gets a result" invariant
`src/agent.rs:827-947`, `:3186-3191`, `:3772-3819`.
Two queues (steering, follow-up) with distinct delivery points — turn start, between tool batches, idle — and an abandoned tool call still emits a well-formed `is_error` result so the provider contract never breaks. The host already has run steering at a different layer (durable `messages` rows), so this is insight rather than code; the invariant is the part to enforce.

### 15. [STUDY] TOCTOU-hardened file access
`src/tools.rs:1717-1793`, `:2765-2801`; `src/extensions.rs:1384-1409`.
`O_NOFOLLOW|O_NONBLOCK`, `(dev, ino)` re-verification after open, pinned scan-root fds, `/proc/self/fd` relative IO on Linux. Correct and instructive; Python can express only a fraction of it (`os.open(..., O_NOFOLLOW)` + `os.fstat` gets the dev/ino check and little else). **Do** port `safe_canonicalize` semantics (`src/extensions.rs:1384-1409`) — resolve symlinks *then* prefix-check, anchoring not-yet-existing paths on the longest existing ancestor. That is ~15 lines of `pathlib` and it closes the obvious escape.

### 16. [SKIP] Rust- or CLI-specific, or actively wrong to copy
- `extensions_js.rs` (35k lines), `extension_dispatcher.rs`, `extension_preflight.rs`, `hostcall_*.rs` — a QuickJS plugin runtime with a static JS deny-list. Enormous; the host has no plugin story.
- `swarm_*.rs`, `resource_governor.rs` — capacity planning and flight recording for a fleet of CLI processes. The host's scheduler is already the durable task queue; this would be a competing one.
- `tui.rs`, `interactive*`, `theme.rs`, `keybindings.rs`, `doctor.rs`, `auth.rs`, `providers/*` — terminal UI, OAuth, provider dialects. The host has React and LiteLLM.
- **The subagent model** (`src/subagents.rs`) — a second copy of the binary with the parent's full env including API keys (`:817-819`), depth-capped at 3. The host's durable leased task rows are a strictly better primitive for the same job.
- **The exec classifier** (`src/extensions/exec_mediation.rs:175-329`) — substring/prefix matching with no shell parsing. It is evaded by `true && <denied>` and by any command spelling outside its literal fragment list. Copying it would produce the appearance of a safety control without the substance.
- **The flush-at-turn-end persistence model** (`src/agent.rs:10887`, `:11114-11132`). A crash mid-turn loses the whole in-flight turn. That is acceptable for a CLI and unacceptable for a host whose runs last minutes to hours and whose entire design premise is surviving restarts.
- **The sandbox.** There isn't one.

---

## 7. INTEGRATION NOTES — attaching each [PORT] to this host

### Where an exec tool would live
The host's tool surface is MCP-only, declared in `engine/src/co_scientist/config/tools.yaml` and dispatched through `call_llm_with_tools` (`engine/src/co_scientist/llm_tool_loop.py:330-358`). Two viable attachment points:

- **(a) As an MCP tool** on the reference server (`engine/mcp_server/`). Cleanest boundary — the exec service becomes a network endpoint, sandboxing is *its* problem, and the engine keeps its existing tool-call plumbing and `COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` bound. Downside: MCP tool calls already have divergent timeout semantics at the two call sites (`call_tool` raises, `execute_tool_call` returns the timeout as the result), and a long-running notebook execution does not fit a 300s default.
- **(b) As a new durable task type** in `app/app/store/tasks.py` / `task_worker.py`. Better fit for work measured in minutes, since the lease/heartbeat/retry machinery already exists. This is the honest answer for "run this analysis against a 4GB dataset."

Recommend **(b) for execution, (a) for the model-facing tool call** — the tool call enqueues a task and returns a handle; a later poll returns the result. That keeps the LLM loop's iteration budget from being consumed by wall-clock waits.

### Friction, per item

**Effect-typed batching (#1)** — the host loop `asyncio.gather`s every tool call (`llm_tool_loop.py:167`). Adding an `effects` field to the YAML tool declarations (`config/tools.yaml`) and grouping before gather is a contained change. Friction: `tool_schema.py` would need a new field with a **fail-closed default** (`write`), and existing declarations must not silently inherit `read`. Get that default wrong and you re-create the bug you were preventing.

**Iteration soft-handoff (#2)** — trivial mechanically (inject a user message at 80% of `max_iterations` in `llm_tool_loop.py:340`). Real friction: the host's loop is *inside* a LangGraph node inside a durable task, so "handoff" has to mean something — writing a partial result into `scientific_tasks.result_json` rather than the CLI's "commit and post a status note."

**Output spillover + redaction (#3)** — the artifact store must **not** be a SQLite blob. The host's `checkpoints` table already grew to 97% of the production DB, the volume is 0.5GB, and `COSCIENTIST_CACHE_DIR` is deliberately kept off the volume. Multi-megabyte tool outputs belong on the same off-volume tmp path, with only a pointer + digest + redaction summary in SQLite. Getting this wrong reproduces the disk-exhaustion incident the repo already documents. Second friction: `_reclaim_disk_space()` prunes checkpoints and cannot VACUUM, so artifact rows must be prunable by the same non-VACUUM path.

**Compaction: file-op carry-forward and cut-point rules (#4, #5)** — the host's conversation state is not one JSONL tree; it is `messages` rows plus a per-node `WorkflowState` checkpoint. So the port is not "copy `compaction.rs`" but "apply its three rules where the host already assembles a prompt." Concretely: (a) in `llm_tool_loop`, never truncate between an assistant message carrying `tool_calls` and its `tool` responses — the host already had to preserve `tool_calls` on the assistant dict or the next iteration 400s (`llm_tool_loop.py:129`), which is the same invariant one step earlier; (b) accumulate a `{read, written, edited}` set from *successful* tool results and re-inject it as a compact block rather than letting the model rediscover it; (c) never delete — write a summary record with a "first kept" marker and filter at prompt-build time, since `messages` is append-only by design and the host's reporting reads that table. Friction: the host has **no single place** where the model's context is assembled — `llm_tool_loop` builds one, each agent prompt template builds another — so the cut-point rule has to be enforced at the loop and the summary carried in `WorkflowState`, which is the checkpointed object and therefore also the thing whose size already caused a volume incident. Keep the carry-forward block small and capped.

**Hashline (#6) and staged apply (#7)** — no host friction; these are pure functions over text plus a proposal table. The only decision is where proposals live: a dedicated table is cleaner than reusing `checkpoints`, and it must be pruned with the run.

**Subprocess backpressure + dedicated threads (#8)** — this is the sharpest friction point and it is a *known* host hazard, not a hypothetical. Rules from `CLAUDE.md` that a naive port violates immediately:
- **Never hold the SQLite write lock across the subprocess call.** Structure exec exactly like `claim_grounding.py` does provider work: claim → release → execute → re-open a transaction to persist. A transaction spanning a 10-minute simulation freezes every writer in the process.
- **Never write on a poll tick.** Stream subprocess output into memory/tmp file and persist on completion or on a bounded schedule — not per chunk. `task_worker.py`'s heartbeat is the model: wake often, write rarely.
- **No process-global asyncio primitives.** Each run's worker cohort runs `asyncio.run` on its own thread (`task_worker.run_run_worker_pool_sync`), so a module-level `asyncio.Semaphore` bounding concurrent subprocesses will bind to the first loop and raise from every other — the exact failure that killed a production ranking task. Bound concurrency per loop (weak per-loop map) or via `worker_pool_size`.
- Use `asyncio.create_subprocess_exec` with piped stdout/stderr and a **bounded** read loop; do not `subprocess.run` on the event loop, and do not put the blocking read on the default executor.

**Plan mode as an effect gate (#9)** — the host has no interactive approver in the run path. The transferable half is the *gate*, not the approval UX: a run-level mode where barrier-effect tools return a structured refusal. Natural home is the Supervisor, which already makes per-cycle scheduling decisions. Friction: the Supervisor is advisory in this system, so a gate it owns needs a real enforcement point in `engine_tasks.py`, not a prompt instruction.

**Schema tiering (#10)** — `tools.yaml` already has per-workflow whitelists, so tiering is close to free. Friction: the host's production DeepSeek path uses `json_object` mode with **no schema enforcement**, so a "promote a tool mid-run" action must be validated defensively; an unenforced schema is how raw JSON ended up in overview string fields before.

### Two host-specific constraints that dominate all of the above

1. **The api service runs at exactly one replica because the store is single-writer SQLite.** Agent-authored code execution is the most obvious reason someone would want to scale out, and it is the one thing that cannot be scaled out without a store migration. Execution must therefore run *out of process* (separate container/service) even before it runs *sandboxed*, or the exec workload and the serving workload contend for one writer.
2. **Startup work runs before uvicorn binds a port.** Any exec-sandbox warm-up (pulling an image, booting a VM) must not be awaited in the lifespan hook, or every deploy fails its healthcheck and each retry starts further behind. Follow the existing pattern: `asyncio.create_task` alongside startup, never inline.

### The thing Pi does not give you
A sandbox. Pi's bash tool is `bash -c` with the agent's full privileges (`src/tools.rs:6149-6163`). For a system whose whole point is running model-authored code against real scientific data, the isolation layer — container per run, read-only mounts for source data, a writable scratch volume, no ambient credentials, egress deny-by-default — is net-new work with no reference implementation in this repo. Budget for it separately; do not let Pi's polish on everything *around* execution disguise the fact that the execution boundary itself is missing.
