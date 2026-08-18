# opencode vs. OpenAI Codex CLI — execution-harness teardown

Target of adaptation: `/Users/guy/Code/co-scientist` (Python, LangGraph engine + FastAPI/SQLite
durable task queue), which needs to give a scientific agent a sandboxed terminal so it can write
code, run it, and test hypotheses against real data.

Checkouts analysed (read-only, nothing modified):

| Project | Path | Commit | Language | Licence |
|---|---|---|---|---|
| opencode | `references/harness/opencode` | `4e81a0b73f6e614afebf9c7ff8862904a3674455` | TypeScript / Bun | MIT |
| Codex CLI | `references/harness/codex` (`codex-rs/`) | `a397079287e6638b39dda329835350d93222681f` | Rust | Apache-2.0 |

---

## 0. Orientation — what these checkouts actually are

**Codex** is a Rust cargo workspace of ~130 crates under `codex-rs/`. The pieces that matter here:
`core/` (turn loop, tools, approvals), `sandboxing/` (policy → OS primitive), `linux-sandbox/`
(the re-exec'd Linux helper), `apply-patch/` (the patch format), `execpolicy/` (a Starlark command
policy DSL), `protocol/` (the wire types, including every enum below), `rollout/` + `thread-store/`
(session persistence), `exec-server/` (a process-execution service the tools go through).

**opencode is two agents in one repo**, and this matters for every claim about it:

| | package | binary | version | status |
|---|---|---|---|---|
| **V1** | `packages/opencode/` | `opencode` | 1.18.18 | **the shipping agent** — root `bun dev` runs `packages/opencode/src/index.ts` (`package.json:10`) |
| **V2** | `packages/core/` + `packages/cli/` + `packages/server/` | `lildax` (`packages/cli/package.json:6`) | 1.18.18 | an Effect-TS rewrite in progress |

The V2 tools are deliberately reduced pending ports — e.g. `packages/core/src/tool/edit.ts:84`
carries `TODO: Port V1 fuzzy correction strategies…`, and `packages/core/src/tool/bash.ts:66-68`
carries `TODO: Port tree-sitter bash / PowerShell parser-based approval reduction`. **Anything
interesting about opencode's harness is in `packages/opencode/`.** Reading only `packages/core/`
gives a systematically weaker picture of the project.

---

## 1. SANDBOXING

### 1.1 Headline

**Codex confines command execution with real OS primitives on all three desktop platforms.
opencode does not confine it at all, and says so.**

### 1.2 opencode — no sandbox, by stated policy

Repo-wide search for `sandbox-exec`, `seatbelt`, `sbpl`, `landlock`, `seccomp`, `bwrap`,
`bubblewrap`, `unshare`, `AppContainer`, `firejail` returns **zero hits in any source file**
(verified independently; the only `unshare` matches are `session.unshare()`, i.e. revoking a share
link). The project states the position in `opencode/SECURITY.md:15-19`:

```
### No Sandbox

OpenCode does **not** sandbox the agent. The permission system exists as a UX
feature to help users stay aware of what actions the agent is taking … it is
not designed to provide security isolation.

If you need true isolation, run OpenCode inside a Docker container or VM.
```

`SECURITY.md:30` lists "Sandbox escapes" as **out of scope**. The V2 bash tool's own model-facing
description says the same thing in the tool schema
(`packages/core/src/tool/bash.ts:109`): *"Execute one shell command string with the host user's
filesystem, process, and network authority."*

Commands are spawned directly — `packages/core/src/tool/bash.ts:158-164`
(`ChildProcess.make(input.command, [], { cwd, shell, … })`), V1 equivalent at
`packages/opencode/src/tool/shell.ts:293-310`. No wrapper, no profile, no namespace.

Two things that *look* like sandboxing and are not:

* `packages/containers/` is **CI build images** for GitHub Actions
  (`packages/containers/README.md:1-11`: base / bun-node / rust / tauri-linux / publish). No agent
  runtime, no devcontainer support, no `docker exec` of tool calls anywhere.
* The `project.sandboxes` SQLite column (`packages/core/src/project/sql.ts:16`,
  `packages/core/src/database/schema.gen.ts:123`) is **vestigial** — the only writer is
  `packages/core/src/session.ts:215`, which always writes `sandboxes: []`. Nothing reads it.

What opencode has instead is (a) a **path-string filesystem confinement** for the file tools and
(b) a **permission-prompt layer**. Both are covered in §4.

* Reads/lists are hard-confined to the workspace, checking both the lexical path **and**
  `realPath`, so symlink escapes are caught — `packages/core/src/filesystem.ts:65-72`
  (`Effect.die(new Error("Path escapes the location"))`).
* Mutations outside the workspace are permitted but require an `external_directory` approval —
  `packages/core/src/location-mutation.ts:120-146`. A *relative* path may never escape; an
  *absolute* outside path prompts.
* **Bash bypasses both.** Confinement applies to the `workdir` argument only. V2 scans the command
  text with a regex tokenizer and emits *advisory warnings, not a gate*
  (`packages/core/src/tool/bash.ts:79-95`, `:138-141` — the warning text literally says "this scan
  is advisory only"). `cd ../.. && rm -rf x` produces neither warning nor prompt. V1 is stronger
  (tree-sitter AST path extraction, `packages/opencode/src/tool/shell.ts:392-411`) but still not a
  boundary — it only decides *whether to ask*.
* Network has no confinement: `webfetch` validates the URL scheme only
  (`packages/core/src/tool/webfetch.ts:83-85`), with no host allowlist, denylist, or private-IP /
  SSRF check. Bash and MCP servers are unrestricted.

### 1.3 Codex — policy type

The policy is a protocol-level enum, `codex-rs/protocol/src/protocol.rs:1002-1050`:

```rust
pub enum SandboxPolicy {
    #[serde(rename = "danger-full-access")]
    DangerFullAccess,
    #[serde(rename = "read-only")]
    ReadOnly { network_access: bool },
    /// Indicates the process is already in an external sandbox.
    #[serde(rename = "external-sandbox")]
    ExternalSandbox { network_access: NetworkAccess },
    #[serde(rename = "workspace-write")]
    WorkspaceWrite {
        writable_roots: Vec<AbsolutePathBuf>,
        network_access: bool,
        exclude_tmpdir_env_var: bool,
        exclude_slash_tmp: bool,
    },
}
```

Note `ExternalSandbox` — an explicit "I am already inside a container, do not double-sandbox"
state, distinct from `DangerFullAccess`. That distinction is exactly what a server-side deployment
needs.

`WritableRoot` (`protocol.rs:1057-1062`) carries `read_only_subpaths` alongside each writable root.
The doc comment (`:1052-1056`) states the reason: to stop the agent editing files that would
escalate its own privileges. The three protected basenames are
`PROTECTED_METADATA_PATH_NAMES = [".git", ".agents", ".codex"]`
(`codex-rs/protocol/src/permissions.rs:29-33`), applied to *every* writable root by
`default_read_only_subpaths_for_writable_root` (`:1757-1794`), with a pre-execution check
`forbidden_agent_metadata_write` at `:44`.

**`SandboxPolicy` is a compatibility projection, not the runtime model.** The type everything
actually flows through is `PermissionProfile` (`codex-rs/protocol/src/models.rs:411-425`):

```rust
pub enum PermissionProfile {
    Managed { file_system: FileSystemSandboxPolicy, network: NetworkSandboxPolicy },
    Disabled,
    External { network: NetworkSandboxPolicy },
}
```

with `FileSystemSandboxPolicy` (`protocol/src/permissions.rs:234-239`), `FileSystemSandboxKind`
(`:227-232`), `FileSystemAccessMode` (`:114-120`), `ReadDenyMatcher` (`:272`) for glob-based read
denial, and a small vocabulary of **symbolic path tokens** rather than raw paths
(`FileSystemSpecialPath`, `:135-160`): `Root`, `Minimal`, `ProjectRoots`, `Tmpdir`, `SlashTmp`.
That indirection is what lets one policy value mean the right thing on three OSes, and it is the
single most copyable structural idea in the sandbox layer.

### 1.4 Codex — platform selection

`codex-rs/sandboxing/src/manager.rs:37-42` and `:62-76`:

```rust
pub enum SandboxType { None, MacosSeatbelt, LinuxSeccomp, WindowsRestrictedToken }

pub fn get_platform_sandbox(windows_sandbox_enabled: bool) -> Option<SandboxType> {
    if cfg!(target_os = "macos")      { Some(SandboxType::MacosSeatbelt) }
    else if cfg!(target_os = "linux") { Some(SandboxType::LinuxSeccomp) }
    else if cfg!(target_os = "windows") {
        if windows_sandbox_enabled { Some(SandboxType::WindowsRestrictedToken) } else { None }
    } else { None }
}
```

So: macOS and Linux always have a backend; **Windows sandboxing is opt-in**; everything else
returns `None`.

**This fails open on the agent path, and that is the one thing to change when copying it.**
`SandboxManager::select_initial` (`sandboxing/src/manager.rs:292-297`) does:

```rust
if self.should_sandbox(permission_profile, pref, has_managed_network_requirements) {
    get_platform_sandbox(windows_sandbox_level != WindowsSandboxLevel::Disabled)
        .unwrap_or(SandboxType::None)
} else { SandboxType::None }
```

A *requested* sandbox on an unknown platform (or Windows with the sandbox disabled) silently
degrades to `SandboxType::None` — no error, no warning at this seam, and no downstream gate turns
it back into one. By contrast the interactive `codex sandbox` CLI subcommand hard-fails on
unsupported platforms (`cli/src/main.rs:1628-1632`). For a hosted system running model-authored
code, the agent path must behave like the CLI path, not like this.

Whether a sandbox is required at all is `should_require_platform_sandbox`
(`sandboxing/src/policy_transforms.rs:526-546`): managed network ⇒ always; restricted network ⇒
unless `ExternalSandbox`; enabled network ⇒ only for a `Restricted`-kind FS policy without
full-disk write.

### 1.5 Codex on macOS — Seatbelt (`sandbox-exec`)

Executable is pinned, not resolved through `PATH`
(`codex-rs/sandboxing/src/seatbelt.rs:35-39`):

```rust
/// When working with `sandbox-exec`, only consider `sandbox-exec` in `/usr/bin`
/// to defend against an attacker trying to inject a malicious version on the
/// PATH. …
pub const MACOS_PATH_TO_SEATBELT_EXECUTABLE: &str = "/usr/bin/sandbox-exec";
```

The policy is **assembled per command** and passed as `-p <policy>` plus `-D KEY=path` parameter
definitions — `seatbelt.rs:757-789`:

```rust
let mut policy_sections = vec![
    MACOS_SEATBELT_BASE_POLICY.to_string(),
    file_read_policy,
    file_write_policy,
    deny_read_policy,
    network_policy,
];
if include_platform_defaults {
    policy_sections.push(MACOS_RESTRICTED_READ_ONLY_PLATFORM_DEFAULTS.to_string());
    if profile == MacosSeatbeltProfile::Process {
        policy_sections.push(MACOS_PROCESS_APPLICATIONS_READ_POLICY.to_string());
    }
}
let full_policy = policy_sections.join("\n");
…
let mut seatbelt_args: Vec<String> = vec!["-p".to_string(), full_policy];
```

Policy surface, in layers:

* **Base** (`sandbox_base_policy.sbpl` → `seatbelt_base_policy.sbpl:8`) is `(deny default)` —
  closed by default, modelled on Chrome's renderer profile (comment at `:3-5`). It re-allows only
  what a build toolchain needs: `process-exec`/`process-fork` so children inherit the profile
  (`:11-12`), a fixed sysctl allowlist (`:24-75`), `ipc-posix-sem` for Python multiprocessing
  (`:93`), a `__KMP_REGISTERED_LIB_` shm regex for PyTorch/libomp (`:96-99`), and pty plumbing
  (`:106-114`).
* **Reads** are a computed `(allow file-read* …)` clause. Full-read policies with no deny-globs
  collapse to the literal `(allow file-read*)` (`seatbelt.rs:697-701`); restricted policies emit
  per-root rules built by `build_seatbelt_access_policy` (`:718-734`).
* **Writes** likewise (`seatbelt.rs:656-693`); full-write emits `(allow file-write* (regex #"^/"))`
  with a comment noting it is more permissive than `(allow file-write*)` (`:659-661`).
* **Deny-globs** become anchored regex deny rules for *both* read and unlink
  (`seatbelt.rs:476-477`).
* **Network** is off unless the policy enables it; `seatbelt_network_policy.sbpl` then re-allows
  only AF_SYSTEM protocol 2 sockets (`:6-11`) and the Mach services needed for DNS and TLS trust
  (`:13-27`). Proxy-specific allow rules are injected by the core based on environment (`:2`).
* **`restricted_read_only_platform_defaults.sbpl`** is a 198-line "minimal readable OS" profile
  used when the filesystem policy asks for `:minimal` — system frameworks, `/bin`,`/usr/bin`,
  `/etc`, `/dev` handles, `/tmp` scratch, plus a curated Mach-lookup allowlist.

Two implementation details worth stealing outright:

* **Paths never enter the policy text.** They are passed as `-DREADABLE_ROOT_0=/path` /
  `-DWRITABLE_ROOT_1=/path` definitions and referenced symbolically inside the SBPL
  (`seatbelt.rs:780-786`). A path containing `"` or `)` therefore cannot break out of the policy.
  Any Python reimplementation that string-formats paths into an SBPL blob has an injection bug.
* **Carve-outs emit *two* clauses, `require-not (literal …)` **and** `require-not (subpath …)`
  (`seatbelt.rs:390-398`) — because `subpath` alone left a gap in which the sandbox could `mkdir
  .codex` and then write inside it.

**What escapes on macOS:** child processes inherit the profile (`base:11-12`), so no fork escape —
but there is also **no PID isolation** (macOS has no `--unshare-pid` equivalent here; signals are
limited to `same-sandbox` at `:13`). `$HOME` is readable in every non-`:minimal` full-read policy
— both `read_only` and `workspace_write` grant `Special::Root = Read`
(`protocol/src/permissions.rs:543-550`, `:731-776`), which compiles to a bare `(allow file-read*)`
(`seatbelt.rs:699`), so **`~/.ssh`, `~/.aws` and shell history are readable by default** unless a
deny-glob is configured. `/tmp`, `/private/tmp`, `/var/tmp` are read-write in the platform defaults
(`:94-97`), opt-out via `exclude_slash_tmp` / `exclude_tmpdir_env_var`. No rlimits beyond
`RLIMIT_CORE=0`. And with a managed proxy, the allowed loopback port is reachable by anything in
the sandbox.

### 1.6 Codex on Linux — bubblewrap + seccomp (Landlock is legacy)

This is the biggest divergence from the widely-repeated description of Codex. At this commit,
Landlock is **not** the primary mechanism. `codex-rs/linux-sandbox/src/landlock.rs:1-4`:

```rust
//! In-process Linux sandbox primitives: `no_new_privs` and seccomp.
//!
//! Filesystem restrictions are enforced by bubblewrap in `linux_run_main`.
//! Landlock helpers remain available here as legacy/backup utilities.
```

and `codex-rs/sandboxing/src/landlock.rs:18-21`:

```rust
/// The helper performs the actual sandboxing (bubblewrap by default + seccomp)
```

Mechanism, in order:

1. **Re-exec as a helper.** The Codex binary self-invokes under argv[0]
   `codex-linux-sandbox` (`codex-rs/sandboxing/src/landlock.rs:6`,
   `CODEX_LINUX_SANDBOX_ARG0`), receiving `--sandbox-policy-cwd`, `--command-cwd`,
   `--permission-profile <json>` and optional `--use-legacy-landlock` /
   `--allow-network-for-proxy` (`landlock.rs:42-58`).
2. **Filesystem via bubblewrap.** Args are built in `codex-rs/linux-sandbox/src/bwrap.rs`; the
   full-filesystem shape is `--new-session --die-with-parent --bind / / --dev /dev --bind-try
   /dev/shm /dev/shm --unshare-user --unshare-pid [--unshare-net] [--proc /proc] --cap-drop ALL`
   (`bwrap.rs:267-296`). Restricted policies additionally emit `--ro-bind`, `--tmpfs`,
   `--remount-ro`, `--ro-bind-data`, `--perms`, `--dir` masks (`bwrap.rs:458-520`, `:1030-1230`).
3. **bwrap binary resolution.** System `bwrap` on `PATH` is preferred; a **bundled**
   `codex-resources/bwrap` next to the executable is the fallback
   (`codex-rs/linux-sandbox/src/launcher.rs:53-70`, `bundled_bwrap.rs`). If neither exists the
   helper aborts with an explicit message (`launcher.rs:46-47`). A `bwrap` found *inside the cwd*
   is deliberately ignored (`codex-rs/sandboxing/src/bwrap.rs:185-186`) — a nice supply-chain
   detail.
4. **Network via seccomp**, applied to the current thread so only the child inherits it
   (`codex-rs/linux-sandbox/src/landlock.rs:41-86`, `:164-260`). Two modes:
   * `Restricted`: deny `connect`, `accept`, `accept4`, `bind`, `listen`, `getpeername`,
     `getsockname`, `shutdown`, `sendto`, `sendmmsg`, `recvmmsg`, `getsockopt`, `setsockopt`;
     `socket`/`socketpair` are allowed **only** for `AF_UNIX` via an arg0 comparison
     (`:206-217`). `recvfrom` is deliberately left allowed with a comment explaining that
     `cargo clippy` needs it for socketpair child management (`:200-202`).
   * `ProxyRouted`: invert it — allow `AF_INET`/`AF_INET6` inside the isolated netns so the child
     can reach a local TCP bridge, deny everything else including `AF_UNIX` `socket()`
     (`:220-246`).
   Unconditionally denied in both modes: `ptrace`, `process_vm_readv`, `process_vm_writev`,
   `io_uring_setup`, `io_uring_enter`, `io_uring_register` (`:178-183`) — i.e. the classic
   seccomp-bypass and cross-process-memory escapes.
   Default action is `Allow`, matched rules return `EPERM` (`:249-252`). Arch support is
   x86_64 and aarch64 only, `unimplemented!()` otherwise (`:253-259`).
5. `PR_SET_NO_NEW_PRIVS` is set only when seccomp or legacy-Landlock is actually needed, because
   many `bwrap` deployments rely on setuid (`landlock.rs:56-64`) — a real, documented tension.

**Fallbacks and failure modes:** WSL1 cannot create the namespaces and is refused outright with a
dedicated message (`codex-rs/sandboxing/src/bwrap.rs:25-29`, mapped to
`CodexErr::UnsupportedOperation` at `codex-rs/sandboxing/src/lib.rs:71-74`). Missing `bwrap` or a
user-namespace denial produces a warning string chosen by probing `bwrap --unshare-user
--unshare-net --ro-bind / / /bin/true` with a 500 ms timeout
(`codex-rs/sandboxing/src/bwrap.rs:74-136`); the probe **fails open** (returns `true`) on spawn
error or timeout.

The legacy Landlock path, when explicitly requested, uses ABI `V5`, `CompatLevel::BestEffort`,
read-everywhere + write to `/dev/null` and the writable roots, and errors if the ruleset ends up
`NotEnforced` (`codex-rs/linux-sandbox/src/landlock.rs:137-162`). It **cannot express restricted
reads** and says so (`:71-76`).

### 1.7 Codex on Windows

`SandboxType::WindowsRestrictedToken`, gated behind `windows_sandbox_enabled`
(`manager.rs:62-76`), implemented in `codex-rs/windows-sandbox-rs/`. **It is not AppContainer** — a
grep for `AppContainer|LowBox|CreateAppContainerProfile|SECURITY_CAPABILITIES` over that crate
returns nothing; its "capability SIDs" are randomly minted `S-1-5-21-*` principals used in ACLs
(`windows-sandbox-rs/src/cap.rs:39-46`). Two backends exist (`WindowsSandboxLevel ∈ {Disabled,
RestrictedToken, Elevated}`, `wrapper.rs:334-341`):

* **Restricted token** — `CreateRestrictedToken` with `DISABLE_MAX_PRIVILEGE | LUA_TOKEN |
  WRITE_RESTRICTED` (`token.rs:42-44`), then only `SeChangeNotifyPrivilege` re-enabled
  (`token.rs:492-505`). Filesystem control is by ACL, with inheritable deny-write ACEs on the
  protected carve-outs (`acl.rs:593-601`) — and missing carve-outs are **materialized as
  directories first** so they cannot later be created writable (`spawn_prep.rs:280-288`).
* **Job objects** — every spawn joins a job *atomically at creation* via
  `PROC_THREAD_ATTRIBUTE_JOB_LIST`, and the spawn is failed rather than briefly running
  uncontained (`proc_thread_attr.rs:70-81`).
* **Network** — not WFP primarily: the egress block is a set of Windows Defender Firewall COM
  rules scoped by SDDL to a dedicated offline account SID
  (`bin/setup_main/win/firewall.rs:32-43`, `:184-197`, `:363-388`), with WFP adding 12 targeted
  `FWP_ACTION_BLOCK` filters for ICMP/DNS/DoT/SMB (`wfp/filter_specs.rs:25-124`). The account is
  chosen by policy (`setup.rs:705-720`); the `CodexSandboxOnline` account has no rules at all.
* The legacy backend's "network block" is **environment variables only** — proxy vars pointed at
  `http://127.0.0.1:9`, `PIP_NO_INDEX`, `CARGO_NET_OFFLINE`, a `~/.sbx-denybin` of `ssh.bat` stubs
  (`env.rs:126-177`). Any process that ignores proxy env has full network. Managed networking is
  therefore **refused** on that backend rather than silently degraded
  (`unified_exec/mod.rs:74-79`), and restricted *reads* are refused too
  (`windows-sandbox-rs/src/lib.rs:539-548`). Refusing rather than degrading is the right instinct.

### 1.7b Network confinement is really done by a managed proxy

`codex-rs/network-proxy/` is the modern mechanism on all three platforms: an HTTP forward +
`CONNECT` + SOCKS5 proxy with optional MITM TLS termination using a **process-local ECDSA P-256 CA
minted at runtime** (`network-proxy/src/certs.rs:157-169`; config `src/config.rs:19-38`, runtime
`src/runtime.rs:549-602`). The OS layer's only job is to make the proxy the *sole* route:
SBPL `(allow network-outbound (remote ip "localhost:{port}"))` on macOS
(`seatbelt.rs:283-345`); a netns plus a TCP→UDS→TCP bridge carrying attribution frames on Linux
(`linux-sandbox/src/proxy_routing.rs`, `proxy_lifecycle.rs`); per-process SID attribution via
`GetExtendedTcpTable` plus firewall loopback allows on Windows (`firewall.rs:113-145`).

It is **fail-closed**: with no proxy endpoint configured the macOS allowlist collapses to an empty
policy string (`seatbelt.rs:321-331`), Linux keeps `--unshare-net`, Windows keeps the blanket
block. That is the correct default and the opposite of the bwrap probe's fail-open behaviour.

### 1.7c Process hardening — cheap, portable, and not really about the sandbox

`codex-rs/process-hardening/src/lib.rs:12-25` runs before `main` and hardens the *agent process
itself*: `prctl(PR_SET_DUMPABLE, 0)` on Linux (`:46`, exit code 5 on failure) and
`ptrace(PT_DENY_ATTACH)` on macOS (`:85`, exit code 6), then scrubs `LD_*` (`:60`) and `DYLD_*`
(`:99`) from the environment, and sets `RLIMIT_CORE = 0` (`:103-110`).

Equally cheap and equally worth copying: the child gets **`env_clear()` plus an explicit
allowlist** (`core/src/spawn.rs:83-88`), not the parent's environment. Note the accompanying
warning that the informational vars are not a control surface
(`core/src/exec_env.rs:16-18`: *"Child processes can overwrite this value, so it must not be
treated as proof of enforcement."*).

### 1.7d Detecting that the sandbox is what failed

`codex-rs/sandboxing/src/denial.rs` is explicitly heuristic:
`QUICK_REJECT_EXIT_CODES = [2, 126, 127]` (`:25`), a `128 + SIGSYS` check for `LinuxSeccomp`
(`:34-38` — the only *reliable* signal), and a keyword scan for "operation not permitted",
"permission denied", "read-only file system", "seccomp", "sandbox", "landlock",
"failed to write file" (`:50-58`). Structured violations are recorded via
`sandboxing/src/violation.rs` (`SandboxViolationBackend` at `:48-53`,
`FileSystemSandboxViolationReason` at `:77-84`).

The honest reading: *even Codex cannot reliably tell a sandbox denial from an ordinary failure*
outside the seccomp case. Any "retry without sandbox on denial" logic inherits that uncertainty.

### 1.8 Codex — command policy layer (`execpolicy`), independent of the OS sandbox

Separate from the kernel confinement, Codex ships a Starlark-syntax **command allow/deny DSL**
(`codex-rs/execpolicy/README.md`):

```starlark
prefix_rule(
    pattern = ["git", "reset", "--hard"],
    decision = "forbidden",
    justification = "destructive operation",
    match     = [["git", "reset", "--hard"]],
    not_match = [["git", "reset", "--keep"], "git reset --merge"],
)
```

Decisions are `allow | prompt | forbidden`, default `allow`; tokens match in order and any element
may be a list of alternatives (README "Overview"). `match`/`not_match` are **load-time-validated
examples** — unit tests embedded in the policy, which is an unusually good idea. Example policy:
`codex-rs/execpolicy/examples/example.codexpolicy`. `host_executable(name=…, paths=[…])` constrains
which absolute paths may fall back to a basename rule, so `/opt/evil/git` does not inherit the
`git` rules. Core integration is `codex-rs/core/src/exec_policy.rs` (1156 lines).

This is the piece that most directly answers "how do I let the science agent run `python`,
`Rscript`, `git diff` without a prompt, and never `curl | sh`".

### 1.9 Codex — the LLM approval reviewer ("guardian")

`codex-rs/core/src/guardian/mod.rs:1-13` describes an approval-time LLM judge:

```
//! Guardian review decides whether an `on-request` approval should be granted
//! automatically instead of shown to the user.
//! 1. Reconstruct a compact transcript that preserves user intent plus the most
//!    relevant recent assistant and tool context.
//! 2. Ask a dedicated guardian review session to assess the exact planned
//!    action and return strict JSON.
//! 3. Fail closed on timeout, execution failure, or malformed output.
```

The rubric is a checked-in 65-line prose policy, `codex-rs/core/src/guardian/policy.md`, bundled
via `include_str!` (`guardian/prompt.rs:819`). It defines four risk domains — Data Exfiltration,
Credential Probing, Persistent Security Weakening, Destructive Actions — each with explicit
"Outcome rule: deny …" / "Outcome rule: allow …" lines, plus a Low-Risk section that exists
purely to suppress false positives (`policy.md:62-65`: *"Do not treat a sandbox retry/escalation as
suspicious by itself"*). Risk levels are `GuardianRiskLevel { Low, Medium, High, Critical }`
(`codex-rs/protocol/src/approvals.rs:87-92`) crossed with
`GuardianUserAuthorization { Unknown, Low, Medium, … }` (`:96-99`).

### 1.10 Sandboxing verdict for the host

For a Python host that must run *untrusted model-authored analysis code against real data*, the
honest ranking is:

1. **Container/VM per run** — not implemented by either project first-party, but it is what
   opencode's own `SECURITY.md:19` recommends and what Codex's `ExternalSandbox` policy variant
   exists to describe. On Railway/Docker this is the only thing that is both strong and portable
   from Python.
2. **Codex's model, re-implemented in Python**: a `SandboxPolicy` value object → a per-platform
   argv transform (`sandbox-exec -p …` on macOS, `bwrap …` on Linux) around a plain
   `asyncio.create_subprocess_exec`. This is genuinely portable because the confinement lives in
   the *argv*, not in the language — see §8.
3. **opencode's model** — a permission prompt — is not a security control and should not be
   presented as one. It is a good *UX* model and a good *audit* model, and worth taking for those
   reasons only.

---

## 2. AGENT LOOP

### 2.1 Who owns the loop

Both projects **own their own multi-step loop** and use the provider SDK for a single assistant
turn only. This convergence is worth noting because it is the opposite of the naive
"`maxSteps: 25`" pattern.

**opencode V1** — `packages/opencode/src/session/prompt.ts:1081-1341`, a plain `while (true)`:

```ts
while (true) {
  yield* status.set(sessionID, { type: "busy" })
  yield* Effect.logInfo("loop", { "session.id": sessionID, step })

  let msgs = yield* MessageV2.filterCompactedEffect(sessionID).pipe(
    Effect.provideService(Database.Service, database),
  )
  const { user: lastUser, assistant: lastAssistant, finished: lastFinished, tasks } = MessageV2.latest(msgs)
```

**Each iteration re-reads the conversation from SQLite** (`prompt.ts:1092`). There is no in-memory
message array carried across steps — the database is the conversation. That is the single most
directly transferable idea in the whole comparison for a durable-queue host.

The provider call is Vercel AI SDK `streamText` (`packages/opencode/src/session/llm.ts:280-324`)
with tools carrying `execute`, so the SDK dispatches the calls *within* one turn — but there is no
`maxSteps` / `stopWhen` anywhere in the repo, so continuation across turns is opencode's loop.
`maxRetries: input.retries ?? 0` (`llm.ts:323`) deliberately disables the SDK's own retry so
opencode's policy governs.

**Codex** drives the OpenAI Responses API directly through its own client. The loop is **not** in
`codex_thread.rs` or `client.rs` — it is `run_turn` at `codex-rs/core/src/session/turn.rs:153`,
with the outer per-turn loop at `:281`. Its contract is stated in the doc comment (`:136-152`):

```rust
/// Takes initial turn input and runs a loop where, at each sampling request,
/// the model replies with either:
///   - requested function calls
///   - an assistant message
/// - If the model requests a function call, we execute it and send the output
///   back to the model in the next sampling request.
/// - If the model sends only an assistant message, we record it in the
///   conversation history and consider the turn complete.
```

There are in fact **two** nested loops: `RegularTask::run` (`core/src/tasks/regular.rs:39`) re-enters
`run_turn` while queued user input remains (`:76-90`), which is how *steering mid-turn* works —
`Op::TurnInput` on an active turn pushes into a pending queue rather than starting a new task
(`core/src/session/turn_input.rs:167`, `:242`).

Two mechanics are worth lifting:

* **Tool futures start before the stream ends.** `handle_output_item_done`
  (`core/src/stream_events_utils.rs:288`) records the call item into history *immediately* and
  pushes the execution future onto a `FuturesOrdered` (`core/src/session/turn.rs:2205-2206`,
  `:2371`), drained after the stream terminates (`drain_in_flight`, `:2111`, called at `:2730`).
  Tools therefore run concurrently with the remainder of the model's output.
* **Parallelism is a per-tool declaration enforced by an RwLock.** `core/src/tools/parallel.rs:153-157`
  takes a *read* guard for parallel-capable tools and a *write* guard for the rest, so a
  non-parallel tool (e.g. `apply_patch`) automatically excludes everything else without any
  scheduler logic. For MCP tools the flag is derived from the server's `read_only_hint`
  (`core/src/tools/handlers/mcp.rs:124-135`).

Tool failures are **not** errors: they become `FunctionCallOutput` with `success: Some(false)`
(`core/src/tools/parallel.rs:230-255`); only `FunctionCallError::Fatal` aborts
(`core/src/stream_events_utils.rs:375-377`).

### 2.2 Termination

opencode V1 (`prompt.ts:1111-1130`) — with an explicit defence against providers that report
`stop` while still emitting tool calls (`:1103-1105`):

```ts
if (lastAssistant?.finish
    && !["tool-calls"].includes(lastAssistant.finish)
    && !hasToolCalls
    && lastAssistant.parentID === lastUser.id) { … break }
```

Step cap is per-agent and **soft**: `const maxSteps = agent.steps ?? Infinity`
(`prompt.ts:1178`), and on the last step it injects a prose `MAX_STEPS_PROMPT`
(`packages/core/src/session/runner/max-steps.ts:1-16` — "Tools are disabled until next user input.
Respond with text only.") rather than removing the tools.

### 2.3 Loop detection

**opencode V1 has an explicit doom-loop guard; Codex has none that I found.**
`packages/opencode/src/session/processor.ts:29` (`DOOM_LOOP_THRESHOLD = 3`) and `:353-373`: three
consecutive calls to the *same tool with byte-identical input* escalate to a user permission
prompt keyed `doom_loop`. V2 defers it (`packages/core/src/session/runner/llm.ts:55`).

### 2.4 Retry / backoff

Codex has **two independent retry layers**. The transport layer
(`codex-client/src/retry.rs:8-12`, `:79`, backoff `:38-47`) is configured for the Responses
provider with `retry_429: false` (`model-provider-info/src/lib.rs:269-275`) — 429 is deliberately
*not* retried at HTTP level, it is classified instead (below). Above it,
`core/src/responses_retry.rs:43` (`handle_retryable_response_stream_error`, called from
`core/src/session/turn.rs:1409-1418`) is a three-rung ladder: optional unbounded connection
retries (feature-gated, 5 s → 60 s, `:17-18`, `:57-83`), then a **WS→HTTPS transport fallback that
resets the counter** (`:85-99`), then ordinary retry (`:101-124`).

| | opencode V1 | opencode V2 (`packages/llm`) | Codex |
|---|---|---|---|
| max attempts | `RETRY_MAX_RETRIES = 5` (`session/retry.ts:31`) | `MAX_RETRIES = 2` (`packages/llm/src/route/executor.ts:36`) | request 4, stream-reconnect 5 (`model-provider-info/src/lib.rs:26-27`, capped at 100 each `:29-33`) |
| base / factor | 2000 ms × 2 (`retry.ts:26-27`) | 500 ms, 10 s cap (`executor.ts:37-38`) | `INITIAL_DELAY_MS = 200`, `BACKOFF_FACTOR = 2.0` (`core/src/util.rs:6-7`) |
| jitter | `RETRY_JITTER_FACTOR = 0.25` (`retry.ts:28`) | — | 0.9–1.1 multiplier (`core/src/util.rs:86-91`) |
| cap w/o headers | `RETRY_MAX_DELAY_NO_HEADERS = 30_000` (`retry.ts:29`) | 10 s | — |
| stream idle timeout | — | — | `DEFAULT_STREAM_IDLE_TIMEOUT_MS = 300_000`, **per-frame not total** (`codex-api/src/sse/responses.rs:552-578`) |
| retryable set | regex battery over error text — 429/5xx/"overloaded"/"socket hang up"/"econnreset" (`retry.ts:33-40`); forces retry on **any** 5xx even when the SDK says non-retryable (`:91-97`); excludes context-overflow (`:86`) | typed: `429\|503\|504\|529` + `ProviderInternal` (`executor.ts:91`, `schema/errors.ts:117-119`) | typed: `CodexErr::is_retryable` (`protocol/src/error.rs:364-403`) — `Stream`, `Timeout`, `UnexpectedStatus`, `ConnectionFailed`, `InternalServerError`, `Io`, `Json`, … `UsageLimitReached` / `ContextWindowExceeded` are **not** |
| `Retry-After` honoured | yes (`retry.ts:46-77`) | unverified | yes — `err.retry_delay()` preferred over backoff (`responses_retry.rs:101-124`) |

Three Codex details are worth taking:

* **The idle timeout resets on every frame** (`sse/responses.rs:553`), so a long-thinking turn is
  never killed for being slow, only for being *silent*. This is exactly the rule the host already
  learned for streaming calls ("bound silence, not duration").
* **429 is parsed, not retried.** `codex-api/src/api_bridge.rs:118-149` turns a 429 whose body says
  `usage_limit_reached` into `CodexErr::UsageLimitReached { plan_type, resets_at, rate_limits, … }`
  — a terminal, *informative* error, not a backoff loop against a quota that will not clear.
* **There is no mid-stream resume.** A dropped SSE becomes
  `CodexErr::Stream("stream closed before response.completed")` (`core/src/session/turn.rs:2262-2266`)
  and the whole sampling request is re-sent — but the prompt is **rebuilt from current history**
  (`:1351-1357`), so already-completed tool calls and their outputs are included and are not re-run.
  Retry-by-rebuilding-from-the-store is far simpler than stream resumption and loses nothing.

### 2.4b Interrupt / abort

`Op::Interrupt` → `Session::interrupt_task` (`core/src/session/mod.rs:4075`) →
`abort_all_tasks(TurnAbortReason::Interrupted)` (`core/src/tasks/mod.rs:494`). `TurnAbortReason`
(`protocol/src/protocol.rs:3984-3989`) is `Interrupted | Replaced | ReviewEnded | BudgetLimited`;
note that starting a new turn implicitly aborts the old one with `Replaced`
(`core/src/tasks/mod.rs:285`). Abort is graceful-then-hard: cancel the token, wait
`GRACEFULL_INTERRUPTION_TIMEOUT_MS = 100` (`core/src/tasks/mod.rs:66`), then `handle.abort()`.

The part worth copying is what happens to the *transcript*. Because items are recorded as they
complete, an abort leaves history with a tool call whose output is missing. On the next prompt
build, `core/src/context_manager/normalize.rs:21-131` **synthesizes an `"aborted"` tool output with
a deterministic ID** and deletes orphan outputs (`:148-216`). A crashed or interrupted turn
therefore always yields a well-formed conversation rather than a malformed one the provider will
reject. A clean interrupt additionally writes an explicit model-visible marker before emitting
`TurnAborted` (`core/src/tasks/mod.rs:919-935`, marker built at `:101-124`).

### 2.5 Compaction

**Codex has four compaction implementations behind one dispatcher**, `run_auto_compact`
(`core/src/session/turn.rs:1160-1236`):

1. **Token-budget inline** (`Feature::TokenBudget`) — `core/src/compact_token_budget.rs:47-64`
   skips summarization entirely and installs a fresh context window
   (`Session::start_new_context_window`, `core/src/session/mod.rs:3724-3782`).
2. **Remote v2** — `core/src/compact_remote_v2.rs`. Not a special endpoint: a *normal* streaming
   `/responses` request with a `ResponseItem::CompactionTrigger {}` sentinel appended
   (`compact_remote_v2_attempt.rs:77`); the client then rebuilds history itself
   (`compact_remote_v2.rs:459-487`), retaining messages up to
   `RETAINED_MESSAGE_TOKEN_BUDGET = 64_000` (`:65`) plus exactly one `Compaction` item.
3. **Remote v1** — genuinely server-side: a unary POST to
   `RESPONSES_COMPACT_ENDPOINT = "/responses/compact"` (`core/src/client.rs:162`,
   `compact_conversation_history` `:552-654`) returning a replacement `Vec<ResponseItem>`.
4. **Local** — `core/src/compact.rs`, model-summarized.

Four triggers: manual `/compact` (`Op::Compact`, `core/src/session/handlers.rs:635`), **pre-turn**
auto (`core/src/session/turn.rs:993-1021`), **mid-turn** auto (`:441-461`, when
`needs_follow_up && (new_context_window_requested || token_limit_reached)`), and model change
(`:1063-1152`).

The budget is **90 % of the context window**, and that is where it is written down
(`protocol/src/openai_models.rs:488-499`):

```rust
pub fn auto_compact_token_limit(&self) -> Option<i64> {
    let context_limit = self.resolved_context_window().map(|w| (w * 9) / 10);
    …std::cmp::min(limit, context_limit)…
}
```

**The local strategy is far more aggressive than opencode's, and the difference matters.**
`build_compacted_history_with_limit` (`core/src/compact.rs:652-717`) keeps **only real user
messages**, newest→oldest until `COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000` is spent (`:57`,
`:661-682`), then appends the summary as a final `user` message (`:708-714`). Everything else —
reasoning, every tool call and output, every assistant message, developer/context items — is
dropped. opencode instead preserves a *tail of whole turns* verbatim. Codex's shape says "the
summary is the memory"; opencode's says "the last few turns are the memory and the summary covers
the rest". For a science agent whose recent tool outputs are the evidence, **opencode's shape is
the safer default**, with Codex's `prune`-like aggressiveness reserved for the far past.

The summary prompt itself is short and generic (`prompts/templates/compact/prompt.md:1-9`):

```
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.
Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue
```

Compaction is bracketed by pre/post hooks that can abort the turn
(`compact_token_budget.rs:71-90`, `PreCompactHookOutcome::Stopped → CodexErr::TurnAborted`), and
falls back by dropping the oldest item and retrying on `ContextWindowExceeded`
(`core/src/compact.rs:309-318`).

**opencode V1's compaction is more prescriptive about what survives.** The trigger is token-count
based against a reserved buffer (`packages/opencode/src/session/overflow.ts:8-33`,
`COMPACTION_BUFFER = 20_000`). What is preserved is a **tail of whole turns**, not a token slice:
`compaction.ts:223-269` walks turns backwards until `preserveRecentBudget` is spent, clamped to
`MIN_PRESERVE_RECENT_TOKENS = 2_000` … `MAX_PRESERVE_RECENT_TOKENS = 15_000`
(`compaction.ts:32-33`); the head is summarized and `tail_start_id` marks the verbatim survivors.
Compaction itself runs as a real assistant turn with `agent: "compaction"` and `tools: {}`
(`compaction.ts:393-448`).

The summary prompt is a fixed skeleton (`packages/core/src/session/compaction.ts:16-46`):
`## Objective` / `## Important Details` / `## Work State` (Completed / Active / Blocked) /
`## Next Move` / `## Relevant Files`, with the rule *"Preserve exact file paths, symbols, commands,
error strings, URLs, and identifiers."* When re-summarizing, `SUMMARY_UPDATE_INSTRUCTIONS`
(`:47-55`) warns the model that *"anything you do not carry into the new summary is lost."*

A separate **prune** pass erases old tool *outputs* in place while keeping the turns
(`compaction.ts:273`, `PRUNE_MINIMUM = 20_000`, `PRUNE_PROTECT = 40_000` at `:28-31`), protecting
`skill` outputs. This is a good idea: tool output is usually the bulk and the least re-readable
part of a transcript.

opencode V2 adds a **reactive** path: when the provider itself reports overflow before any
assistant output, it compacts and rebuilds the request once, explicitly refusing to recurse
(`packages/core/src/session/runner/llm.ts:283-288`, `:355-367` — *"Post-compaction provider attempt
cannot recover another overflow"*).

### 2.6 Context epoch (opencode V2 only — worth understanding)

`packages/core/src/session/context-epoch.ts` plus a `session_context_epoch(session_id, baseline,
snapshot, baseline_seq)` table. Instead of re-rendering the system prompt every turn (which
silently rewrites history and destroys prompt caching), opencode pins the rendered baseline and
the event sequence at which it took effect. Each turn reconciles:

* `Unchanged` / `ReplacementBlocked` → reuse the stored baseline (`:63-65`)
* `ReplacementReady` → write a new baseline at a new `baseline_seq` — only allowed once a
  compaction has landed past the current baseline (`:59`, `:66-70`)
* otherwise → publish a **`ContextUpdated` event describing only the delta** as an in-conversation
  system message (`:72-77`)

History then excludes system messages at or below `baseline_seq` because they are already folded
into the baseline (`packages/core/src/session/history.ts:36-47`).

### 2.7 Sub-agents

opencode V1 has a `task` tool (`packages/opencode/src/tool/task.ts`) that runs a **child session**
(`parentID`) through the same prompt loop, with `subagent_depth` defaulting to 1 — i.e. subagents
cannot spawn subagents (`task.ts:104-117`, `packages/core/src/v1/config/config.ts:84-85`).
Background subagents are flag-gated (`task.ts:98-102`).

Codex has a richer multi-agent surface: `spawn_agent`, `send_input`, `send_message`, `list_agents`,
`wait_agent`, `resume_agent`, `interrupt_agent`, `close_agent`
(`codex-rs/core/src/tools/handlers/multi_agents_spec.rs:87-204`), plus
`core/src/codex_delegate.rs` and `core/src/agent_communication.rs`. Inter-agent messages are
first-class rollout records (`RolloutItem::InterAgentCommunication`,
`codex-rs/history/src/lib.rs:98`).

---

## 3. TOOL SURFACE

### 3.1 Codex — inventory

Everything is registered in one place, `add_core_tool_sources`
(`codex-rs/core/src/tools/spec_plan.rs:892-937`), called from `build_tool_router` (`:121`), which
then appends MCP tools (`:148`), extension executors (`:157`), dynamic tools (`:162`) and hosted
model tools (`:163`). `ToolSpec` has five kinds (`tools/src/tool_spec.rs:22`): `Function`,
`Namespace`, `ToolSearch`, `WebSearch`, `Freeform`. Exposure levels
(`tools/src/tool_executor.rs:51-80`) are `Direct | Deferred | DeferredModelOnly | DirectModelOnly |
CodeModeOnly | Hidden` — the tool list the model sees is a *view*, not the registry.

Two absences worth stating: **there is no `read_file` tool** (the model reads with `cat`/`sed`
through the shell — grep for `ToolName::plain("read_file")` returns nothing outside MCP fixtures),
and there is no `TodoWrite`; the equivalent is `update_plan`.

Verified tool names:

| Tool | Spec file | Notes |
|---|---|---|
| `exec_command` | `shell_spec.rs:21-107` | the shell. Returns output *or a session id* for a still-running command. `tty: true` allocates a PTY; omitted means plain pipes (`:46`) |
| `write_stdin` | `shell_spec.rs:109+` | writes to a running `exec_command` session |
| `apply_patch` | `apply_patch_spec.rs:9-28` | a **Freeform grammar tool** (Lark), not a JSON function |
| `update_plan` | `plan_spec.rs:43` | the TODO list |
| `view_image` | `view_image_spec.rs` | attach a local image |
| `request_permissions` | `request_permissions.rs` | the model asks for a *policy change*, not a one-off approval |
| `request_user_input` | `request_user_input_spec.rs` | structured question to the human |
| `get_context_remaining` | `get_context_remaining_spec.rs` | model can inspect its own budget |
| `new_context_window` | `new_context_window_spec.rs` | model-initiated compaction |
| `tool_search` | `tool_search_spec.rs` | search a large tool catalogue (deferred-loading tools) |
| `sleep` | `sleep.rs:25` | |
| `current_time` | `current_time.rs` | |
| `spawn_agent` / `send_input` / `send_message` / `list_agents` / `wait_agent` / `resume_agent` / `interrupt_agent` / `close_agent` | `multi_agents_spec.rs` | multi-agent |
| `list_mcp_resources` / `list_mcp_resource_templates` / `read_mcp_resource` | `mcp_resource_spec.rs` | |
| `request_plugin_install` / `list_available_plugins_to_install` | `request_plugin_install*.rs` | |
| `shell_command` | `shell_spec.rs:157-225` | the classic surface: a single `command` **script string** (not an array) + `workdir` + `timeout_ms` (default 10000 ms). Hidden when unified exec is on (`spec_plan.rs:995`) |
| `web_search` | `hosted_spec.rs:14-46` | **hosted**, not a function tool — `ToolSpec::WebSearch`; modes `Cached\|Indexed\|Live\|Disabled` (`:15-20`) |
| `wait_for_environment` | `wait_for_environment.rs:90-99` | host-supplied description, capped at 1024 bytes (`:27-29`) |

The classic path shows where the "shell profile wrapper" lives: `Shell::derive_exec_args`
(`core/src/shell.rs:22-49`) chooses `-lc` vs `-c` for sh/bash/zsh (`:25`), `-NoProfile … -Command`
for PowerShell (`:32`), `/c` for cmd (`:42`). `login: true` means login+rc-file semantics — a real
behavioural switch, not cosmetics.

Timeout and output constants (`core/src/unified_exec/mod.rs:66-75`):
`MIN_YIELD_TIME_MS = 250`, `MAX_YIELD_TIME_MS = 30_000`, `MIN_EMPTY_YIELD_TIME_MS = 5_000`,
`DEFAULT_MAX_BACKGROUND_TERMINAL_TIMEOUT_MS = 300_000`, `DEFAULT_MAX_OUTPUT_TOKENS = 10_000`,
`UNIFIED_EXEC_OUTPUT_MAX_BYTES = 1 MiB`, `MAX_UNIFIED_EXEC_PROCESSES = 64`. Classic exec default is
`DEFAULT_EXEC_COMMAND_TIMEOUT_MS = 10_000` (`core/src/exec.rs:61`), timeout exit code 124 (`:68`),
50 ms SIGKILL grace (`:69`).

**stdout and stderr are captured separately and concatenated, not interleaved** — each is truncated
to `max_bytes` independently (`core/src/exec.rs:718-744`) and `aggregate_output` (`:829-850`)
appends stderr after stdout. Model-facing truncation is a per-model `TruncationPolicy` of
`Bytes(n) | Tokens(n)` (`protocol/src/protocol.rs:3099-3102`) applied by middle-truncation
(`protocol/src/error.rs:600-604`).

`exec_command` schema (`shell_spec.rs:30-107`), required `["cmd"]`, `additionalProperties: false`:
`cmd`, `workdir`, `tty`, `yield_time_ms` (default 10000 ms, range 250-30000; 10000-30000 on
Windows), `max_output_tokens` (**default 10000 tokens** — a *token* budget, not a byte budget),
optional `shell`, optional `login`, optional `environment_id`.

Three of those are unusual and good:

* **`yield_time_ms`** turns "long-running command" from an error into a first-class outcome: the
  tool returns a session id and the model keeps working, then reads more or writes stdin later.
  There is no "background job" concept to bolt on — every command is potentially a session.
* **`max_output_tokens`** is denominated in the unit the model actually pays in.
* The approval fields ride **on the tool schema itself** (`create_approval_parameters`,
  `shell_spec.rs:298-343`): `sandbox_permissions` ∈
  `use_default | with_additional_permissions | require_escalated`, `justification` (the
  user-facing approval question), `additional_permissions` (a full permission-profile object), and
  `prefix_rule` — an array like `["git","pull"]` that the model proposes as a **reusable
  execpolicy allow rule**. The model does not just ask for permission; it proposes the rule.

### 3.2 Codex — file editing: `apply_patch`

This is the design worth copying. `apply_patch` is exposed as a **freeform grammar tool**, not a
JSON function (`apply_patch_spec.rs:19-28`):

```rust
ToolSpec::Freeform(FreeformTool {
    name: "apply_patch".to_string(),
    description: "The `apply_patch` tool can be used to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON.".to_string(),
    format: FreeformToolFormat { r#type: "grammar".to_string(), syntax: "lark".to_string(), definition },
})
```

The grammar is checked in verbatim, `codex-rs/core/src/tools/handlers/apply_patch.lark`:

```lark
start: begin_patch hunk+ end_patch
begin_patch: "*** Begin Patch" LF
end_patch: "*** End Patch" LF?
hunk: add_hunk | delete_hunk | update_hunk
add_hunk: "*** Add File: " filename LF add_line+
delete_hunk: "*** Delete File: " filename LF
update_hunk: "*** Update File: " filename LF change_move? change?
filename: /(.+)/
add_line: "+" /(.*)/ LF -> line
change_move: "*** Move to: " filename LF
change: (change_context | change_line)+ eof_line?
change_context: ("@@" | "@@ " /(.+)/) LF
change_line: ("+" | "-" | " ") /(.*)/ LF
eof_line: "*** End of File" LF
```

Worked example:

```
*** Begin Patch
*** Update File: engine/src/co_scientist/agents/generation/generate.py
@@ def draft_hypotheses(
     state: WorkflowState,
-    count: int = 5,
+    count: int = 8,
 ) -> list[Hypothesis]:
*** Add File: engine/src/co_scientist/agents/generation/simulate.py
+"""Runs the numeric simulation for a hypothesis."""
+
+def simulate(params: dict) -> dict:
+    return {}
*** Delete File: engine/dev/old_probe.py
*** End Patch
```

Key properties:

* **One tool call can touch many files atomically-ish** — add, update, delete and move in one
  envelope. Neither of opencode's two edit tools can do that.
* **No line numbers.** Location is by `@@` context plus the leading-space context lines inside a
  hunk. Nothing goes stale when the file shifts.
* The parser (`codex-rs/apply-patch/src/parser.rs:1-24`) documents the Lark grammar as the spec
  and is deliberately *more lenient* than it, tolerating whitespace around markers (`:24-25`) and
  running in lenient mode unconditionally (`PARSE_IN_STRICT_MODE: bool = false`, `parser.rs:53`,
  with the comment that gpt-4.1 needs it).
* **Context resolution is a strictness ladder** — `codex-rs/apply-patch/src/seek_sequence.rs`:
  exact match → `trim_end` match → `trim` both ends → Unicode-punctuation-normalised match
  (`:71-79`: "mirrors the fuzzy behaviour of `git apply`"). Plus an EOF-anchored search when the
  hunk ends with `*** End of File` (`:31-38`), and two defensive early-returns documented from a
  real panic (`:9-12`).
* Line endings are a policy, not an accident: `ApplyPatchFileUpdateMode::{NormalizeToLf,
  PreserveLineEndings}` (`codex-rs/apply-patch/src/lib.rs:57-66`), threaded to the arg0-dispatched
  standalone process by env var `CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS` (`:53-55`).
* **Ambiguity is prevented by a monotonic cursor, not by scoring.** Each pass returns the *first*
  match scanning forward, but `compute_replacements` (`apply-patch/src/file_update.rs:82-216`)
  keeps a `line_index` that only advances (`:203`), and an `@@` context line is itself located with
  the same ladder and then anchors the search (`:94-108`). So hunks resolve strictly in order —
  a much simpler correctness story than opencode's similarity thresholds.
* **No staleness check of any kind.** `grep -ni "stale|must.read|read_before|mtime"` across
  `apply-patch/src/` and both `apply_patch.rs` files returns nothing. The file is read at apply
  time (`file_update.rs:32`) and the context match *is* the drift detection. That is the
  argument for patch-with-context over string-replace: freshness is structural, not bookkeeping.
* `apply_patch` is **also a real executable path**: the Codex binary self-invokes with
  `--codex-run-as-apply-patch` (`lib.rs:50`), and a model that types `apply_patch <<'EOF' …` into
  the *shell* tool is intercepted (`core/src/tools/handlers/apply_patch.rs:500`
  `intercept_apply_patch`, called from `shell.rs:142` **and** `unified_exec/exec_command.rs:314`)
  and routed to the same code. Heredoc extraction uses a **tree-sitter bash parse**
  (`apply-patch/src/invocation.rs:5-9`, `:311`). Codex even creates a temp dir containing an
  `apply_patch` symlink and prepends it to `PATH` (`arg0/src/lib.rs:322-337`), so the command
  genuinely exists. One format, three entry points.
* A raw patch body passed *without* an explicit `apply_patch` command is **rejected, not silently
  applied**: `patch detected without explicit call to apply_patch. Rerun as ["apply_patch", "<patch>"]`
  (`apply-patch/src/lib.rs:91-93`, `invocation.rs:169-178`).
* Errors reach the model as tool output (`FunctionCallError::RespondToModel`), prefixed
  `apply_patch verification failed: {error}` (`core/src/tools/handlers/apply_patch.rs:383-386`,
  `:534-538`), with a distinct `patch rejected: {reason}` for policy refusals
  (`core/src/apply_patch.rs:57-59`). Context-match failures print the expected lines
  (`file_update.rs:205-209`), which is what lets the model self-correct.
* Patch safety is assessed *before* application: `assess_patch_safety`
  (`codex-rs/core/src/safety.rs:40-98`) checks whether every target is inside a writable root, and
  notes the hard-link caveat — *"paths in the patch are hard links to files outside the writable
  roots, so we should still run `apply_patch` in a sandbox"* (`safety.rs:57-59`). If no platform
  sandbox is available it will not auto-approve (`:71-79`).

### 3.3 opencode — inventory (V1, the shipping set)

Registered in `packages/opencode/src/tool/registry.ts:229-252`, in advertised order:
`invalid`, `question`, `bash`, `read`, `glob`, `grep`, `edit`, `write`, `task`, `webfetch`,
`todowrite`, `websearch`, `skill`, `apply_patch`, `execute` (code-mode), `lsp` (flag),
`plan` (flag + CLI only). Description prompts are companion `.txt` files
(`packages/opencode/src/tool/*.txt`), imported at the top of each module.

The **model-conditional edit surface** is a striking choice — `registry.ts:296-301`:

```ts
const usePatch =
  input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
if (tool.id === ApplyPatchTool.id) return usePatch
if (tool.id === EditTool.id || tool.id === WriteTool.id) return !usePatch
```

GPT-5-class models get `apply_patch` and are **denied `edit` and `write` entirely**; every other
model gets `edit`+`write` and never sees `apply_patch`. opencode has empirically concluded the
edit format should follow the model.

`bash` is a multi-shell runner whose tool id is kept as `"bash"` only for backwards compatibility
(`packages/opencode/src/tool/shell/id.ts:14-17`). Schema (`shell/prompt.ts:15-23`): `command`,
`timeout?` ms, `workdir?`. Its **description is generated per shell** — bash / pwsh /
PowerShell 5.1 / cmd profiles with different chaining guidance, and the truncation limits and
default timeout interpolated into the prompt (`shell/prompt.ts:43-262`, `:97-98`).
Execution is a plain spawn with **`stdin: "ignore"`** (`shell.ts:293-310`) — commands cannot be
interactive, which is precisely the case Codex's `write_stdin` handles. Default timeout
2 min (`shell.ts:347`), **no maximum**. Output is streamed to an in-memory ring of
`maxBytes * 2` and spilled to a file past the limit, with the model receiving a UTF-8-safe *tail*
prefixed `...output truncated...\n\nFull output saved to: <file>` (`shell.ts:439-522`, `:225-255`,
`:578-580`). Global truncation constants: `MAX_LINES = 2000`, `MAX_BYTES = 50 * 1024`,
7-day retention (`packages/opencode/src/tool/truncate.ts:12-15`).

A detail worth stealing: the truncation hint is **agent-aware** (`truncate.ts:129-131`) — when a
`task` tool exists it says *"Use the Task tool to have explore agent process this file… Do NOT read
the full file yourself - delegate to save context."*, otherwise it suggests `Grep`/`Read` with
offset.

### 3.4 opencode — file editing: the 9-replacer chain

`packages/opencode/src/tool/edit.ts`. Schema (`:47-56`): `filePath`, `oldString`, `newString`,
`replaceAll?`. Provenance is credited in the header (`:1-4`) to Cline and gemini-cli.

A `Replacer` is a **generator of candidate substrings that actually exist in the file**
(`edit.ts:217`); the driver then does `content.indexOf(search)`. Order (`edit.ts:694-704`):

| # | Replacer | Line | Strategy |
|---|---|---|---|
| 1 | `SimpleReplacer` | `:244` | exact |
| 2 | `LineTrimmedReplacer` | `:248` | per-line `.trim()` equality over an N-line window; reconstructs the exact original span by char offsets |
| 3 | `BlockAnchorReplacer` | `:288` | ≥3 lines: match first+last line as anchors, block-size delta ≤ `max(1, floor(size*0.25))`, score middles by Levenshtein |
| 4 | `WhitespaceNormalizedReplacer` | `:427` | collapse `\s+` → `" "` |
| 5 | `IndentationFlexibleReplacer` | `:471` | strip common minimum indent from both sides |
| 6 | `EscapeNormalizedReplacer` | `:499` | unescape `\n \t \r \' \" \` \\ \$` — fixes models emitting literal backslash-n |
| 7 | `TrimmedBoundaryReplacer` | `:562` | only when `find.trim() !== find` |
| 8 | `ContextAwareReplacer` | `:588` | first/last anchors **plus** equal line count, ≥50% of middle non-empty lines matching trimmed |
| 9 | `MultiOccurrenceReplacer` | `:548` | yields `find` once per exact occurrence (feeds `replaceAll`) |

Thresholds `SINGLE_CANDIDATE_SIMILARITY_THRESHOLD` / `MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD`
are both `0.65` (`edit.ts:219-221`); `levenshtein` is a hand-rolled DP matrix at `:226-242`.

The driver (`edit.ts:682-729`) has two guards that matter more than the matchers:

```ts
if (isDisproportionateMatch(search, oldString)) {
  throw new Error("Refusing replacement because the matched span is much larger than oldString. …")
}
if (replaceAll) return content.replaceAll(search, newString)
const lastIndex = content.lastIndexOf(search)
if (index !== lastIndex) continue          // ambiguous -> try the next candidate, never guess
```

`isDisproportionateMatch` (`:731-737`) rejects a match ≥ `max(oldLines+3, oldLines*2)` lines, or
whose trimmed length exceeds `max(len+500, len*4)`. **Fuzzy matching without this guard is how a
block-anchor matcher silently eats a whole function.**

Failure messages returned to the model are distinct and actionable (`:723-728`): *"Could not find
oldString in the file. It must match exactly, including whitespace, indentation, and line
endings."* vs *"Found multiple matches for oldString. Provide more surrounding context to make the
match unique."*

Two caveats found in the code that a copier must know:

* **`replaceAll` applies to the matched *candidate* span, not the model's literal `oldString`** — a
  fuzzy match can therefore multiply.
* **`write.txt:5` promises a read-before-write guard that does not exist.** The prompt says *"This
  tool will fail if you did not read the file first"*; there is no read-time tracker anywhere in
  `packages/*/src`. `edit.txt:4` makes the same false claim, and `edit.txt:8` quotes an error
  string that does not match the real one. Do not copy those prompt lines without building the
  check.

The genuine staleness protection is in **V2**: `FileMutation.writeIfUnchanged`
(`packages/core/src/file-mutation.ts:144-157`) re-reads under a per-path `KeyedMutex` and
byte-compares against the content the tool read, raising `StaleContentError` → *"File changed after
permission approval. Read it again before editing."* (`packages/core/src/tool/edit.ts:113-116`).
Note the window it closes is *approval → write*, not *read-tool → write*, and V2 `write` skips it
entirely (`packages/core/src/tool/write.ts:87` calls the unconditional `writeTextPreservingBom`).

opencode also implements the Codex envelope twice: V1 `packages/opencode/src/tool/apply_patch.ts`
(supports `*** Move to:`) and V2 `packages/core/src/tool/apply-patch.ts` (**rejects moves**,
`:97-98`) with its own parser `packages/core/src/patch.ts`, whose chunk seeker is a four-stage
ladder — exact / `trimEnd` / `trim` / Unicode-normalised (`patch.ts:160-193`) — i.e. an
independent re-derivation of Codex's `seek_sequence`.

### 3.5 Post-edit feedback: LSP diagnostics (opencode only)

opencode V1 runs **formatter → LSP touch → diagnostics** after every mutation and appends the
result to the tool output the model reads:

```ts
let output = "Edit applied successfully."
yield* lsp.touchFile(filePath, "document")
const diagnostics = yield* lsp.diagnostics()
const block = LSP.Diagnostic.report(filePath, diagnostics[normalizedFilePath] ?? [])
if (block) output += `\n\nLSP errors detected in this file, please fix:\n${block}`
```
(`packages/opencode/src/tool/edit.ts:196-201`; `write.ts:74-90` also reports *other* files' errors,
capped at `MAX_PROJECT_DIAGNOSTICS_FILES = 5`; `apply_patch.ts:266-293` per file.) Only severity-1
diagnostics are shown, ≤20 per file (`packages/opencode/src/lsp/diagnostic.ts:3, 20-27`). The
formatter may rewrite the file, so the content is re-read afterwards (`edit.ts:112-114`).

Codex has no equivalent — it relies on the model running the project's own checks via the shell.
For a scientific host this is a real point in opencode's favour: *the closest analogue is running
the test/lint/typecheck command automatically after a write and feeding failures back*.

---

## 4. APPROVAL MODEL

### 4.1 Codex — policy enum

`codex-rs/protocol/src/protocol.rs:915-939` — note this is **not** the commonly-cited
4-variant enum; `on-failure` is now an *alias* for `OnRequest`, and a `Granular` variant exists:

```rust
pub enum AskForApproval {
    /// only "known safe" commands—as determined by `is_safe_command()`—that
    /// **only read files** are auto-approved. Everything else will ask.
    #[serde(rename = "untrusted")] UnlessTrusted,
    /// The model decides when to ask the user for approval.
    #[serde(alias = "on-failure")] #[default] OnRequest,
    /// Fine-grained controls for individual approval flows.
    Granular(GranularApprovalConfig),
    /// Never ask. Failures are immediately returned to the model.
    Never,
}
```

`GranularApprovalConfig` (`:941-956`) is five independent booleans:
`sandbox_approval`, `rules` (execpolicy `prompt` rules), `skill_approval`,
`request_permissions`, `mcp_elicitations`. **A `false` auto-rejects rather than prompting** —
which is what makes `Granular` usable headlessly.

### 4.2 Codex — the decision matrix

Approval and sandbox are two orthogonal axes, resolved in
`codex-rs/core/src/tools/sandboxing.rs:194-230`:

```rust
let needs_approval = match policy {
    AskForApproval::Never => false,
    AskForApproval::OnRequest | AskForApproval::Granular(_) =>
        matches!(file_system_sandbox_policy.kind, FileSystemSandboxKind::Restricted),
    AskForApproval::UnlessTrusted => true,
};
if needs_approval && matches!(policy, AskForApproval::Granular(g) if !g.allows_sandbox_approval()) {
    ExecApprovalRequirement::Forbidden { reason: "approval policy disallowed sandbox approval prompt" }
} else if needs_approval { ExecApprovalRequirement::NeedsApproval { … } }
else { ExecApprovalRequirement::Skip { bypass_sandbox: false, … } }
```

The escalation path — "run this one unsandboxed" — is `sandbox_override_for_first_attempt`
(`sandboxing.rs:238-267`), and the guard on it is the sharpest thing in either codebase
(`sandboxing.rs:269-295`):

```rust
/// Denied reads only exist inside the sandbox. If a policy contains any
/// denied-read paths, bypassing the sandbox would silently grant those reads,
/// so escalation must keep the command sandboxed with the denied reads intact.
pub(crate) fn unsandboxed_execution_allowed(p: &FileSystemSandboxPolicy) -> bool {
    !p.has_denied_read_restrictions()
}
```

i.e. **an escalation request is downgraded from "bypass" to "sandboxed" whenever bypassing would
lose a restriction the sandbox is the only enforcer of.** A permission system that grants what was
asked for rather than what was meant is exactly how deny-lists leak.

That function is only the *fallback*. The real command path is execpolicy
(`core/src/exec_policy.rs:314-440`), and for a command **no rule matched**,
`render_decision_for_unmatched_command` (`exec_policy.rs:730-831`) is the authoritative table:

| command class | `UnlessTrusted` | `OnRequest` | `Granular` | `Never` |
|---|---|---|---|---|
| known-safe, no complex parsing | **Allow** (`:761-767`) | ↓ | ↓ | ↓ |
| dangerous (`dangerous_command_match`) | Prompt | Prompt | Prompt | **Forbidden** (`:778`) |
| unmatched, FS unrestricted / external | Prompt (`:791-795`) | **Allow** (`:798-802`) | **Allow** (`:816-821`) | **Allow** (`:786-790`) |
| unmatched, FS restricted, no override asked | Prompt | **Allow** (`:810-812`) | **Allow** (`:824-827`) | **Allow** |
| unmatched, FS restricted, override asked | Prompt | **Prompt** (`:808-809`) | **Prompt** (`:823`) | Allow |

Two readings matter. First, **`is_known_safe_command` only grants `Allow` under `UnlessTrusted`**
(`:761-767`) — under every other policy the allowlist is not what lets a command through.
Second, under `Never` a non-dangerous command is allowed with the comment
*"We allow the command to run, relying on the sandbox for protection"* (`:786-790`). That is the
whole architecture in one line: **the approval layer classifies, the sandbox enforces.** A host
that copies the classification without the enforcement has copied nothing.

Approval results are memoised per session by `with_cached_approval`
(`sandboxing.rs:70-116`, doc at `:64-69`), which stores a decision **per key** so a later request
touching a subset skips the prompt (the multi-key shape exists because a patch touches many files).
Two refinements are worth copying verbatim:

* **Key canonicalization** (`core/src/command_canonicalization.rs:14-38`): a `bash -lc` script that
  parses to exactly one plain command is reduced to that command's argv, so `/bin/bash -lc "ls"`,
  `bash -lc "ls"` and `ls` share one cache entry; complex scripts keep their exact text behind a
  `__codex_shell_script__` sentinel (`:5-6`, `:21-35`).
* **The cache key carries the execpolicy fingerprint** (`core/src/tools/approvals.rs:706-717`), so
  editing the policy invalidates every cached approval. A "remember this" cache that does not key
  on the policy that produced it is a stale-authorization bug waiting to happen.

The cache is session-scoped and never persisted (`sandboxing.rs:88`; `ReviewDecision` doc at
`protocol/src/protocol.rs:3877-3880`). Cross-session persistence exists only via the two *amendment*
decisions — `ApprovedExecpolicyAmendment` (writes a rule to the policy file) and
`ApprovedMcpPolicyAmendment` (`:3882-3884`).

### 4.3 Codex — trusted commands

`UnlessTrusted` leans on `is_known_safe_command`
(`codex-rs/shell-command/src/command_safety/is_safe_command.rs:12-50`), which is a real
allowlist, not a heuristic:

* `zsh` is normalised to `bash` (`:16-20`).
* The base list (`is_safe_to_call_with_exec`, `:67-102`) is `cat cd cut echo expr false grep head
  id ls nl paste pwd rev seq stat tail tr true uname uniq wc which whoami`, plus `numfmt`/`tac`
  on Linux.
* **Flag-aware exceptions** — this is where the real work is:
  `base64` unsafe with `-o`/`--output` (`:104-112`); `find` unsafe with
  `-exec -execdir -ok -okdir -delete -fls -fprint -fprint0 -fprintf` (`:114-131`);
  `rg` unsafe with `--pre`, `--hostname-bin`, `--search-zip`, `-z` (`:134-154`);
  `sed` safe **only** in the exact shape `sed -n {N|M,N}p` with ≤4 argv (`:160-168`);
  `git` safe only for `status|log|diff|show|branch` (`:177`), `branch` further restricted to
  listing flags (`:213-214`), behind a denylist of value-taking global options — `-c`,
  `--config-env`, `--exec-path`, `--git-dir`, `--work-tree`, `--output`, `--ext-diff`,
  `--textconv`, `--exec` (`:240-263`).
* Composite commands are handled properly: `bash -lc "a && b | c"` is parsed, and the whole thing
  is safe **only if every constituent command is individually safe** (`:35-48`).

The mirror image is `command_safety/is_dangerous_command.rs`: `rm` with a force flag (`:178`,
`:239-241`), unwrapping through `sudo` (`:183`), `env` (`:186`) and `trap` (`:189`), bounded at
`MAX_DANGEROUS_COMMAND_WRAPPER_DEPTH = 8` (`:16`). Plus Windows lists and a PowerShell tokenizer
(`command_safety/powershell_parser.rs` + `powershell_parser.ps1`).

**Every one of those exceptions is a bug someone shipped.** A Python transcription that keeps the
allowlist and drops the flag rules is strictly worse than having no allowlist.

### 4.4 Codex — execpolicy and model-proposed rules

Beyond the built-in allowlist, `codex-rs/execpolicy/` is a **user-editable command policy** in
Starlark syntax with three decisions (`allow | prompt | forbidden`) and `justification` text
surfaced in the prompt (README "Overview"). The `match` / `not_match` fields are validated at load
time — the policy carries its own tests.

The loop closes at `ExecPolicyAmendment` (`codex-rs/protocol/src/approvals.rs:37-42`): when the
model requests escalation it may attach a `prefix_rule`, and approving it appends a permanent
`prefix_rule(..., decision="allow")` to the policy file (`core/src/exec_policy.rs:442`
`append_amendment_and_update`; network rules at `:492`). **"Approve and remember" is expressed as a
rule the user can read and edit, not as an opaque cache entry.**

### 4.4b CLI modes — and the absence of `--full-auto`

`--full-auto` **does not exist** in this checkout (a repo-wide grep for `full-auto|full_auto`
returns nothing). The actual surface is `utils/cli/src/shared_options.rs:9-73`:

* `--sandbox` / `-s` ∈ `read-only | workspace-write | danger-full-access`
  (`utils/cli/src/sandbox_mode_cli_arg.rs:12-28`)
* `--ask-for-approval` / `-a` ∈ `untrusted | on-request | never`
  (`utils/cli/src/approval_mode_cli_arg.rs:9-31`) — **no CLI surface for `Granular`**
* `--dangerously-bypass-approvals-and-sandbox` (alias `--yolo`) → `(Never, DangerFullAccess)`
  (`cli/src/main.rs:2163-2172`), conflicting with `--ask-for-approval`
* `--approve-for-me` (alias `--not-so-yolo`) — the interesting one. It expands to three config
  overrides (`shared_options.rs:76-89`):
  ```rust
  .push(r#"approvals_reviewer="auto_review""#);
  .push(r#"approval_policy="on-request""#);
  .push(r#"sandbox_mode="workspace-write""#);
  ```
  i.e. **"route my approvals through the guardian LLM inside a workspace-write sandbox"** — the
  productised form of §4.5, and the closest thing in either project to an autonomous-but-bounded
  mode. This is the shape a headless scientific agent wants.

`approval_policy` is a `ConstrainedWithSource<AskForApproval>` (`config/src/config_requirements.rs:167`),
so a managed/admin layer can forbid specific values — the policy can be narrowed by the deployment
and not widened by the user.

### 4.5 Codex — the guardian (LLM approval reviewer)

`codex-rs/core/src/guardian/` routes an `on-request` approval to a dedicated review session that
returns strict JSON and **fails closed** on timeout, execution failure or malformed output
(`guardian/mod.rs:1-13`). The rubric is a 65-line checked-in prose policy,
`guardian/policy.md`, bundled at `guardian/prompt.rs:819`, organised as four risk domains
(Data Exfiltration, Credential Probing, Persistent Security Weakening, Destructive Actions), each
ending in explicit `Outcome rule: deny …` / `Outcome rule: allow …` lines. Examples of its
reasoning quality:

* *"Authorization to create or interact with content does not authorize its egress."*
* *"Do not assume the user has version control when evaluating file changes for destructiveness."*
* *"Shadowing of common variables like `HOME` is highly risky."*
* and a whole Low-Risk section that exists to suppress false positives: *"Do not treat a sandbox
  retry/escalation as suspicious by itself."*

Risk is scored as `GuardianRiskLevel {Low, Medium, High, Critical}` crossed with
`GuardianUserAuthorization {Unknown, Low, Medium, …}` (`protocol/src/approvals.rs:87-99`).

### 4.6 opencode — the permission model

Three effects, last-match-wins, default `ask` — `packages/core/src/permission.ts:76-86`:

```ts
export function evaluate(action: string, resource: string, ...rulesets: Permission.Ruleset[]) {
  return rulesets.flat()
    .findLast((rule) => Wildcard.match(action, rule.action) && Wildcard.match(resource, rule.resource))
    ?? { action, resource: "*", effect: "ask" }
}
```

Because it is `findLast`, **JSON key order in the user's config is semantically significant** —
acknowledged in a comment at `packages/core/src/v1/config/permission.ts:22-24`, which notes the
parser is configured with `propertyOrder: "original"` for exactly this reason. That is a sharp edge
worth *not* copying.

Ordering that is worth copying: configured `deny` is evaluated **before** saved "always" rules are
appended, so a saved approval can never override a configured deny
(`packages/core/src/permission.ts:147-162`). And a missing agent resolves to
`[{action:"*", resource:"*", effect:"deny"}]` — fail-closed (`permission.ts:15`).

**Defaults are permissive.** The base rule is `{action:"*", resource:"*", effect:"allow"}`
(`packages/core/src/plugin/agent.ts:108-119`; V1 `packages/opencode/src/agent/agent.ts:119-136`).
Out of the box `bash`, `edit`, `write`, `webfetch`, `websearch` never prompt; only
`external_directory`, `doom_loop` (V1) and reading `*.env` ask.

### 4.7 opencode — the bash AST split (its best idea)

V1 parses the command with **tree-sitter-bash / tree-sitter-powershell WASM**
(`packages/opencode/src/tool/shell.ts:311-336`), extracts every `command` node —

```ts
function commands(node: Node) {
  return node.descendantsOfType("command").filter((child): child is Node => Boolean(child))
}
```
(`shell.ts:123-125`) — so `a && b | c`, subshells and `$( )` all decompose. Then for each
sub-command (`shell.ts:392-411`):

* if the head is a file-touching command (`FILES` / `CMD_FILES`, `shell.ts:29-64`) it resolves each
  path argument (env/`~`/`$PWD` expansion, glob-prefix trimming, `cygpath` on Windows) and
  collects out-of-tree directories for an `external_directory` prompt;
* it records the sub-command's raw source as a permission pattern, **and** a reusable prefix
  pattern `BashArity.prefix(tokens).join(" ") + " *"`.

`BashArity` (`packages/opencode/src/permission/arity.ts:1-9` + a ~130-entry generated `ARITY`
table from `:24`) maps a command prefix to how many tokens identify it — `rm: 1`, `git: 2`,
`npm run: 3`, `docker compose: 3`, `aws: 3`. So approving `git checkout main` with "always" saves
`git checkout *`, not `git *` and not the literal command. **This is the correct granularity for
"remember this approval" and neither project's alternative is as good.**

Path expansion is deliberately conservative: `dynamic()` (`shell.ts:174-179`) refuses to resolve
any argument containing `$`, `$( )`, `${ }` or backticks, so command substitution can never
produce a false "safe path".

Since `Permission.ask` loops over every pattern (`packages/opencode/src/permission/index.ts:72-82`),
one `deny` among the sub-commands denies the whole call, and all-`allow` skips the prompt.

### 4.8 opencode — request lifecycle and "always"

Pending requests are an **in-memory `Map` + Effect `Deferred`**
(`packages/core/src/permission.ts:117`, `:176-218`), never persisted; a shutdown finalizer fails
every pending request with `DeclinedError` (`:119-129`) so a restart rejects rather than silently
approving. The tool fiber blocks on `Deferred.await`; the UI resolves via
`POST /permission/:requestID/reply` with `once | always | reject`.

Two behaviours worth noting:

* **Reject cascades** — rejecting one request fails every other pending request in the same session
  (`permission.ts:231-248`). A reject carrying a message becomes `CorrectedError { feedback }`, fed
  back to the model as *steering* rather than a bare failure.
* **`always` re-evaluates** every other pending request and auto-resolves any now fully allowed
  (`:259-283`).

"Always" scope diverges: V1 keeps it in RAM for the session
(`packages/opencode/src/permission/index.ts:23-26, 145-151`); **V2 writes it to SQLite per project
with no expiry** (`packages/core/src/permission.ts:250-256`, table
`permission(id, project_id, action, resource)` at `packages/core/src/permission/sql.ts`). And the
saved pattern is whatever the tool proposed — `read`/`edit`/`grep`/`webfetch`/`websearch`/
`todowrite` all send `save: ["*"]`, so one "always" permanently allows that entire action for the
project. Only V1's bash produces a narrowed prefix.

### 4.9 opencode — modes and agents

There is no `--full-auto`-style server concept. `--auto` (aliases `--yolo`,
`--dangerously-skip-permissions`) is **client-side**: the CLI simply auto-replies `once` to each
SSE permission event (`packages/opencode/src/cli/cmd/run.ts:797-810`). Configured denies still
hold, because `deny` short-circuits before a request is created.

Agent-level rulesets are first-class and tools are **removed from the model's tool list** when
wholly denied (`packages/core/src/tool/registry.ts:106-113`;
V1 `packages/opencode/src/permission/index.ts:204-219`). Built-ins: `build` (default),
`plan` (edit denied except `.opencode/plans/*.md`), `general`, `explore` (deny-all then re-allow
`grep/glob/webfetch/websearch/read`), and hidden `compaction`/`title`/`summary` with `*:* deny`
(`packages/core/src/plugin/agent.ts:121-201`).

Subagent inheritance is deny-only — `packages/opencode/src/agent/subagent-permissions.ts:14-26`
propagates the parent's `deny` rules and `external_directory` rules and nothing else, so a parent's
`allow` can never widen a child.

Plugin veto is `tool.execute.before` (`packages/plugin/src/index.ts:266-273`); note the declared
`"permission.ask"` hook (`:261`) **has no call site anywhere in the repo** — a plugin cannot
influence a permission decision at this commit.

---

## 5. SESSION & STATE

### 5.1 Codex — rollout files

Sessions are JSONL "rollouts" under `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<uuid>.jsonl`
(`codex-rs/rollout/src/lib.rs:67` `SESSIONS_SUBDIR = "sessions"`, path shape confirmed in
`rollout/src/compression_tests.rs:683-684`), with `archived_sessions/` alongside
(`lib.rs:68`). Files are **transparently compressed to `.jsonl.zst`** and materialised back to
plain JSONL for append (`rollout/src/compression.rs:41, 58, 64-72`).

Each line is (`codex-rs/history/src/lib.rs:199-205`):

```rust
pub struct RolloutLine {
    pub timestamp: String,
    pub ordinal: Option<u64>,
    #[serde(flatten)] pub item: RolloutItem,
}
```

with `RolloutItem` (`history/src/lib.rs:95-105`):
`SessionMeta`, `ResponseItem`, `InterAgentCommunication`,
`InterAgentCommunicationMetadata { trigger_turn }`, `Compacted`, `TurnContext`, `WorldState`,
`SecurityRiskScore`, `EventMsg`.

Two things stand out. **`TurnContext` is a record type** — the cwd, model, sandbox policy and
approval policy in force are written *into the transcript*, so a resumed session knows the
conditions each turn ran under rather than inheriting today's config. And a compaction is a
**record**, `Compacted(CompactedItem)` carrying `message` + `replacement_history`
(`history/src/lib.rs:141-149`), not a destructive rewrite.

**Not everything in the file goes back to the model.** `rollout/src/policy.rs:88-140` tiers what is
written (`TokenCount`, `TurnStarted/Complete`, `TurnAborted` always; `ItemCompleted` only in
paginated history mode; deltas and errors never), and the *replay* filter is narrower still —
`core/src/session/rollout_reconstruction.rs:328-378` admits only `ResponseItem`s and inter-agent
messages into model-visible history. Every `EventMsg` (the whole UI transcript, token counts, turn
markers) is dropped from the prompt; `TurnContext` / `WorldState` are consumed out-of-band
(`:379-400`). **One file, two readers, different projections** — the same split the host already
has between `run_events` (SSE) and `checkpoints` (resume).

Resume is O(tail), not O(file): the reconstructor scans **newest→oldest**
(`rollout_reconstruction.rs:154`) and stops at the first `Compacted` item carrying a
`replacement_history` (`:288-297`), then replays only the suffix forward. `ThreadRolledBack` events
become "skip the next N user-turn segments" (`:186-190`).

`InitialHistory { New, Cleared, Resumed(ResumedHistory), Forked(Vec<RolloutItem>) }`
(`history/src/lib.rs:216-222`) makes **fork a first-class outcome** — `codex fork` is its own
subcommand (`cli/src/main.rs:211`), and `forked_from_id()` (`:230-244`) reads lineage from
`SessionMeta`. There is also an explicit `Op::RecoverTurn` (`core/src/session/handlers.rs:579`)
that starts a turn with *empty* user input and `is_recovery: true`
(`core/src/session/turn_input.rs:158-165`) so the model continues from reconstructed history —
though no invoker was found in `app-server`/`tui`/`exec`.

The supporting crates divide cleanly, and the division is the lesson:
`history/` = **types only**; `rollout/` = the JSONL writer/reader (plus `.zst` compression,
`compression.rs:18`, and a `reverse_jsonl_scanner.rs` for tail-first reads);
`state/` = a **SQLite mirror of rollout metadata** for listing/search
(`state/src/lib.rs:1-5`); `thread-store/` = the storage-neutral interface core actually talks to,
with `LocalThreadStore` and `InMemoryThreadStore` implementations (`thread-store/src/lib.rs:19-40`);
`message-history/` = an unrelated global `~/.codex/history.jsonl` of user prompts, appended with a
single `O_APPEND` write for atomicity (`message-history/src/lib.rs:1-16`).

### 5.2 opencode — SQLite

One SQLite database at `<xdgData>/opencode/opencode.db` (`packages/core/src/database/database.ts:43-55`,
overridable by `OPENCODE_DB`), Drizzle ORM over a vendored Effect adapter, opened with

```
PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL; PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -64000; PRAGMA foreign_keys = ON; PRAGMA wal_checkpoint(PASSIVE);
```
(`database.ts:22-37`) — **the same PRAGMA set the host already uses.**

Tables (`packages/core/src/session/sql.ts`, generated DDL in
`packages/core/src/database/schema.gen.ts`):

* `session` (`sql.ts:22-66` / `schema.gen.ts:181-214`) — `parent_id` for subagents, `directory`,
  `agent`, `model` JSON, `revert` JSON, `permission` JSON, per-session token counters
  (`tokens_input/output/reasoning/cache_read/cache_write`) and `cost`.
* V1 `message` / `part` (`sql.ts:68-90` / `schema.gen.ts:127-147`) — opaque `data` JSON blobs,
  `part` indexed by `(session_id, time_created, id)`.
* V2 `session_message` (`schema.gen.ts:169-180`) — one row per message with `seq`, and
  `UNIQUE(session_id, seq)` (`:259`).
* V2 `event_sequence(aggregate_id PK, seq, owner_id)` + `event(id, aggregate_id, seq, type, data)`
  with `UNIQUE(aggregate_id, seq)` (`schema.gen.ts:72-88`, `:239`).

Migrations are hand-registered TypeScript modules in a bespoke `migration` table, not
`__drizzle_migrations` (`packages/core/src/database/migration.ts:18-41`, list of 38 at
`migration.gen.ts:3-44`).

### 5.3 opencode — checkpoint / undo via a shadow git repo

This is the one piece of opencode I would port wholesale.

* **Location**: `<data>/snapshot/<projectId>/<hash(worktree)>` — a bare git dir, never inside the
  user's repo (`packages/opencode/src/snapshot/index.ts:71`; V2 `packages/core/src/snapshot.ts:98`).
  Every invocation is `git --git-dir <shadow> --work-tree <real worktree> …`
  (`snapshot/index.ts:75`).
* **Seeding**: writes `objects/info/alternates` pointing at the real repo's object database
  (`snapshot/index.ts:209-224`), so the shadow repo references existing blobs instead of copying
  them; V2 also copies the real `index` so the first `add` is cheap
  (`packages/core/src/git.ts:407-425`).
* **A snapshot is a bare tree hash** (`snapshot/index.ts:340-344`): `git add` into the shadow
  index, `git write-tree`, keep the hash. **No commit, no ref, no branch** — so nothing appears in
  the user's `git log`, `status`, reflog, or stash.
* **Restore** is `read-tree <hash>` + `checkout-index -a -f` (`:382-406`); **revert** is per-file
  `git checkout <hash> -- <file>`, deleting files absent from that tree
  (`packages/core/src/git.ts:690-717`).
* **Diffs** cost one `git diff --cached --name-only <hash>` against the shadow index
  (`snapshot/index.ts:353-358`) — not a filesystem walk.
* V2 adds a **non-destructive preview**: build a throwaway index at `preview-<uuid>.index` via
  `GIT_INDEX_FILE`, `update-index --cacheinfo` each target blob, write a tree, diff it, delete the
  index in an `ensuring` (`packages/core/src/git.ts:638-688`). The worktree is never touched.
* `.gitignore` is honoured via the *real* repo's `check-ignore --no-index`
  (`snapshot/index.ts:102-130`); V2 also drops untracked files over 2 MB (`snapshot.ts:138`).
* Everything is serialized by a per-gitdir semaphore (`snapshot/index.ts:55-64`); snapshots are
  pruned after 7 days (`:23`).

Snapshots are captured before the stream starts (`processor.ts:99-102`, with the comment that the
AI SDK may execute tools before emitting `start-step`), and the per-step delta is written as a
`patch` part (`:436, 457-468`).

### 5.4 opencode — durable input and crash recovery

V2 admits a prompt into a `session_input` table **before** running anything
(`packages/core/src/session.ts:360-386`), then `execution.wake` starts or coalesces a drain, so a
prompt survives a process death even if the turn does not. On restart,
`failInterruptedTools` (`packages/core/src/session/runner/llm.ts:119-139`) marks any tool left
`pending`/`running` as failed before restarting; `SessionRunner.run`
(`llm.ts:383-406`) is driven by *pending durable input*, not by a prompt argument.

This is very close in spirit to the host's `scientific_tasks` lease/heartbeat model.

Concurrency is in-process only: one SQLite connection behind `Semaphore.make(1)`
(`packages/core/src/database/sqlite.bun.ts:121-130`), event appends under `BEGIN IMMEDIATE` with
projectors running inside the same transaction (`packages/core/src/event.ts:320-323, 351`), and a
per-session `SessionRunCoordinator` of Effect fibers (`session/run-coordinator.ts:5, 81-101`).
Cross-process is *not* guarded — `event_sequence.owner_id` with a `strictOwner` check that dies on
mismatch (`event.ts:254-260`) plus `UNIQUE(aggregate_id, seq)` is the whole story, and the V2 TODO
list says so: *"Replace local ownership with durable multi-node ownership when clustered"*
(`runner/llm.ts:51`).

### 5.5 opencode — client/server split

Headless server + thin client over **HTTP + SSE**. V2 spawns a *detached daemon* and reuses it
across launches, health-checking a registered `server.json` (url + pid + version) before spawning
(`packages/cli/src/services/daemon.ts:110-127`); V1 instead runs the server in a **worker thread**
and tunnels HTTP over worker RPC unless network flags are given
(`packages/opencode/src/cli/cmd/tui.ts:234-249`).

Two SSE endpoints: global `GET /api/event` (bounded 256-item queue, a synthetic `server.connected`
first frame, 15 s `: heartbeat` comments — `packages/server/src/handlers/event.ts:20-48`) and
**per-session durable replay `GET /api/session/:sessionID/event?after=<seq>`**
(`packages/protocol/src/groups/session.ts:327-337`). The `?after=<seq>` resume contract is exactly
the host's `GET /api/runs/{id}/events?after=<seq>`.

The TUI is TypeScript + SolidJS on OpenTUI — there are no `.go` files in the repo
(`packages/tui/package.json:50-66`, entry `packages/tui/src/app.tsx:1`).

---

## 6. CONVERGENCE TABLE

| Decision | Codex | opencode | Verdict for the host |
|---|---|---|---|
| **OS sandbox** | Seatbelt (macOS), bwrap+seccomp (Linux), restricted token (Windows, opt-in) | **none**, disclaimed in `SECURITY.md:15-19` | **Codex.** Not close. |
| **Sandbox as data** | `SandboxPolicy` enum serialized into the transcript; `ExternalSandbox` variant for "already contained" | n/a | **Codex** — the policy value object ports to Python unchanged |
| **Confinement seam** | argv transform: `sandbox-exec -p …` / `bwrap …` around the real command | none (path-string checks in the tool layer) | **Codex** — argv is language-independent |
| **Protected metadata** | `.git`, `.agents`, `.codex` forced read-only inside every writable root (`permissions.rs:29-33`, `:1757-1794`) | none | **Codex** — cheap, high value |
| **Network confinement** | a managed proxy is the only route; OS layer just pins it (`network-proxy/`, `seatbelt.rs:283-345`), fail-closed | scheme check only, no allowlist | **Codex** |
| **Unsupported platform** | agent path degrades to `SandboxType::None` **silently** (`manager.rs:292-297`); the CLI subcommand hard-fails (`cli/src/main.rs:1628-1632`) | n/a | **Neither** — copy the CLI's behaviour, not the agent's |
| **Child environment** | `env_clear()` + explicit allowlist (`core/src/spawn.rs:83-88`); `LD_*`/`DYLD_*` scrubbed pre-main (`process-hardening/src/lib.rs:60, 99`) | inherits `process.env` + a plugin hook (`shell.ts:416-426`) | **Codex** |
| **Denial detection** | heuristic: exit codes 2/126/127, `128+SIGSYS`, keyword scan (`denial.rs:25-58`) | n/a | **Codex**, but note even it is unreliable outside seccomp |
| **Interrupted-turn hygiene** | missing tool outputs synthesized as `"aborted"` on next prompt build (`context_manager/normalize.rs:21-131`) | V2 `failInterruptedTools` marks them failed on restart (`runner/llm.ts:119-139`) | **Convergent** — both essential; take either |
| **Command policy** | `execpolicy` Starlark DSL (`allow/prompt/forbidden`), self-testing rules | glob patterns over tool+resource | **Codex** for expressiveness; opencode's globs are simpler to build |
| **Trusted-command list** | real allowlist with flag-aware exceptions and composite parsing (`is_safe_command.rs:67-127`) | none (default is `allow` everything) | **Codex** |
| **Command decomposition for approval** | shell-lc parse in the safe-command check only | **tree-sitter AST**, every `command` node (`shell.ts:123-125`) | **opencode** |
| **"Approve always" granularity** | model-proposed `prefix_rule` appended to the policy file (`approvals.rs:37-42`, `exec_policy.rs:442`) | `BashArity` prefix, e.g. `git checkout *` (`arity.ts:1-9`) | **Tie** — take both: arity for the default, model-proposal for the escape hatch |
| **Approval-cache keying** | canonicalized argv (`bash -lc "ls"` ≡ `ls`) + execpolicy fingerprint, so editing policy invalidates (`command_canonicalization.rs:14-38`, `approvals.rs:706-717`) | raw resource string; V2 persists it to SQLite with no invalidation | **Codex** |
| **Headless autonomy preset** | `--approve-for-me` = guardian review + on-request + workspace-write (`shared_options.rs:76-89`) | `--yolo` auto-replies `once` client-side (`cli/cmd/run.ts:797-810`) | **Codex** — the only auditable one |
| **LLM approval reviewer** | yes — `guardian/` with a checked-in `policy.md` rubric, fails closed | no | **Codex** |
| **Approval enum** | `UnlessTrusted / OnRequest / Granular(5 flags) / Never` (`protocol.rs:915-939`) | `allow / deny / ask` rules, last-match-wins | **Codex** for headless (`Granular` auto-rejects instead of blocking) |
| **Escalation safety** | escalation downgraded to sandboxed when deny-reads exist (`sandboxing.rs:269-279`) | n/a | **Codex** |
| **Turn loop ownership** | own loop | own loop (`while(true)`, `prompt.ts:1088`) | **Convergent** — do not delegate to the SDK |
| **Conversation source of truth** | rollout JSONL replayed | **the database, re-read every iteration** (`prompt.ts:1092`) | **opencode** — matches the host exactly |
| **Loop detection** | none found | `DOOM_LOOP_THRESHOLD = 3` on identical tool+input (`processor.ts:29, 353-373`) | **opencode** |
| **Retry** | request 4 / stream-reconnect 5, 300 s idle (`model-provider-info/src/lib.rs:25-27`) | 5 attempts, 2 s×2 + 25% jitter (`retry.ts:26-31`) | **Convergent**; take Codex's *separate* stream-reconnect budget |
| **Compaction** | local + server-side + inline fresh-window, all one lifecycle | turn-tail preservation with a fixed summary skeleton, plus a tool-output-only prune | **opencode** for the prompt and the prune; **Codex** for recording compaction as a transcript item |
| **File edit format** | `apply_patch` V4A envelope, exposed as a **Lark grammar** tool | 9-strategy fuzzy string replace **and** its own `apply_patch`, chosen per model | **Codex** — see §7 |
| **Fuzzy matching** | 4-stage ladder in `seek_sequence.rs` | 9 replacers + Levenshtein + disproportion guard | **opencode** for the guard, **Codex** for the ladder |
| **Read-before-write** | n/a (patch carries its own context) | **promised in the prompt, not implemented** (`write.txt:5`) | Neither — build it, or use patch context instead |
| **Post-edit feedback** | none | formatter + LSP diagnostics appended to tool output (`edit.ts:196-201`) | **opencode** |
| **Long-running commands** | `yield_time_ms` → returns a session id; `write_stdin` to talk to it | `stdin: "ignore"`, single timeout, no max (`shell.ts:293-310, 347`) | **Codex** |
| **Output budget** | `max_output_tokens` (default 10000 **tokens**) | 2000 lines / 50 KB, spilled to a file with a tail preview | **Codex** for the unit, **opencode** for the spill-and-tail |
| **Session format** | JSONL rollout + zstd, `TurnContext` and `Compacted` as records, fork first-class | SQLite (WAL, `synchronous=NORMAL`, `busy_timeout=5000`) | **opencode** — identical to the host's store |
| **Undo / checkpoint** | none found | **shadow git repo, tree hashes, no commits** (`snapshot/index.ts:71, 340-344`) | **opencode** |
| **Durable input / crash recovery** | rollout replay | `session_input` admitted before the run; `failInterruptedTools` on restart | **opencode** |
| **Resume contract** | rollout file + `InitialHistory` | `GET /api/session/:id/event?after=<seq>` | **opencode** — already the host's contract |

**Overall:** Codex is the better template for the *execution* half (sandbox, approvals, command
policy, edit format, long-running commands). opencode is the better template for the *state* half
(SQLite session store, durable input, snapshot/undo, SSE resume) — and its state model is already
the host's model, so most of it is confirmation rather than new work.

---

## 7. WHAT IS WORTH TAKING

Ranked by value to *this* host. Language notes are blunt.

### 1. `SandboxPolicy` as a serialized value object + an argv-transform seam — **[PORT]** (Codex)
`codex-rs/protocol/src/protocol.rs:1002-1050`, `sandboxing/src/manager.rs:62-76`,
`sandboxing/src/seatbelt.rs:757-789`, `linux-sandbox/src/bwrap.rs:267-296`.
The *policy type* and the *argv transform* are pure data. Nothing about them is Rust. A Python
dataclass `SandboxPolicy` plus a function `wrap(argv, policy) -> argv` gets you seatbelt on a dev
Mac and bwrap in the Railway container, with `DangerFullAccess` and `ExternalSandbox` as the two
escape hatches. **The seccomp filter itself is the one genuinely non-portable piece** — from Python
you would need `python-seccomp`/`libseccomp` bindings or, far more simply, rely on
`bwrap --unshare-net`.

### 2. The `apply_patch` V4A envelope as the only edit tool — **[PORT]** (Codex)
`core/src/tools/handlers/apply_patch.lark`, `apply-patch/src/parser.rs`,
`apply-patch/src/seek_sequence.rs`.
Context-anchored, no line numbers, multi-file in one call, add/update/delete/move. The parser is
~700 lines of Rust that reimplements cleanly in ~300 lines of Python. Both projects independently
converged on this format and opencode *prefers it for the strongest models*
(`registry.ts:296-301`) — that is the strongest available signal.
The Lark-grammar exposure (`ToolSpec::Freeform`) is OpenAI-Responses-specific; through LiteLLM you
would ship it as a normal function tool with one `patch_text` string and put the grammar in the
description. That loses grammar-constrained decoding but keeps the format.

### 3. Trusted-command allowlist with flag-aware exceptions — **[PORT]** (Codex)
`shell-command/src/command_safety/is_safe_command.rs:12-127`.
~60 lines of Python. The important details are the ones that are easy to miss: `find` is not safe
if `-exec`/`-delete` is present, `base64` is not safe with `-o`, and a composite `bash -lc "a && b"`
is safe only if *every* constituent is safe. For a science agent the list wants extending with
`python -c`? — no: `python` is exactly what must **not** be on it.

### 4. Shadow-git snapshots for checkpoint/undo — **[PORT]** (opencode)
`packages/opencode/src/snapshot/index.ts:71, 102-130, 209-224, 340-344, 382-406`.
Pure subprocess `git` calls; nothing TypeScript about it. A `git --git-dir <shadow> --work-tree
<workspace> write-tree` gives an O(changed-files) checkpoint id that never pollutes the user's repo
and lets a run's file mutations be diffed, reverted, and *attached to a hypothesis*. For a
hypothesis-testing system this is not just undo — it is provenance: "this hypothesis was tested by
this exact worktree state".

### 5. Split the approval decision from the sandbox decision, and never let escalation lose a restriction — **[PORT]** (Codex)
`core/src/tools/sandboxing.rs:194-230, 238-295`.
Two orthogonal axes (`AskForApproval` × `SandboxPolicy`), plus
`unsandboxed_execution_allowed()`: an escalation is silently downgraded to "sandboxed" when
bypassing would drop deny-reads. Twenty lines of logic; the reasoning is the value.

### 6. Command decomposition via a bash AST + arity-prefix approvals — **[PORT]** (opencode)
`packages/opencode/src/tool/shell.ts:123-125, 392-411`; `permission/arity.ts:1-9`.
`tree_sitter` + `tree_sitter_languages` exist for Python, so the AST walk ports directly. The
`ARITY` table is plain data — copy it. This is what makes "always allow `git checkout *`" mean the
right thing instead of "always allow `git`".

### 7. The `guardian` LLM approval reviewer with a checked-in prose rubric — **[STUDY]** (Codex)
`core/src/guardian/mod.rs:1-13`, `core/src/guardian/policy.md`.
The *mechanism* (secondary model call, strict JSON, fail closed) is trivial in Python, and the host
already has the exact same shape in `app/app/safety.py` — deterministic rules first, then an
optional contextual model assessment, with every assessor failure leaving the hold standing. The
value here is `policy.md` itself: a well-written, adversarially-minded rubric with explicit outcome
rules *and* an explicit false-positive-suppression section. Read it before writing a command-risk
prompt.

### 8. `yield_time_ms` + `write_stdin`: long-running commands as sessions — **[PORT]** (Codex)
`core/src/tools/handlers/shell_spec.rs:30-107`, `:109+`.
A 40-minute simulation is the normal case for this host, not the exception. Modelling "still
running" as a *successful* return with a session id — rather than a timeout error — is the right
shape, and `max_output_tokens` as the budget unit is right too. In Python this is an
`asyncio.subprocess` handle in a per-run registry.

### 9. Post-edit diagnostics fed back to the model — **[PORT]** (opencode)
`packages/opencode/src/tool/edit.ts:196-201`, `lsp/diagnostic.ts:3, 20-27`.
Not the LSP part — a science host does not need an LSP. The idea: after a write, **run the cheap
project check and append its failures to the tool result**, capped (≤20 per file, errors only).
Here that is `ruff check` + `mypy` on the touched file, or the test file's own import.

### 10. The compaction summary skeleton and the tool-output-only prune — **[STUDY]** (opencode)
`packages/core/src/session/compaction.ts:16-55`,
`packages/opencode/src/session/compaction.ts:28-33, 273`.
The fixed skeleton (`Objective / Important Details / Work State / Next Move / Relevant Files`) and
the warning *"anything you do not carry into the new summary is lost"* are directly reusable prose.
The prune pass — erase old *tool outputs* while keeping the turns, protecting `skill` outputs — is
the higher-leverage half and cheaper to implement than summarization.

### Also worth taking (below the top ten, but cheap)

**A. Runtime-hygiene primitives — [PORT] (Codex).**
`core/src/spawn.rs:83-88` (`env_clear()` + explicit allowlist),
`process-hardening/src/lib.rs:46, 60, 85, 99, 103-110` (`PR_SET_DUMPABLE=0`, `PT_DENY_ATTACH`,
scrub `LD_*`/`DYLD_*`, `RLIMIT_CORE=0`), `sandboxing/src/bwrap.rs:185-186` (ignore a helper binary
found inside the cwd), `seatbelt.rs:35-39` (pin `/usr/bin/sandbox-exec` rather than resolving via
`PATH`), and `seatbelt.rs:780-786` (pass paths as `-D` parameters, never interpolate them into the
policy text). Each is a few lines of Python. The last two are the ones that turn a
sandbox-shaped thing into an actual sandbox.

**B. The interrupted-turn normalizer — [PORT] (Codex; opencode has a variant).**
`core/src/context_manager/normalize.rs:21-131` synthesizes an `"aborted"` output for any tool call
whose result is missing, with a deterministic ID, and deletes orphan outputs (`:148-216`).
opencode's V2 equivalent is `failInterruptedTools` (`packages/core/src/session/runner/llm.ts:119-139`).
The host restarts workers mid-task by design (lease expiry, `--reload`, healthcheck kills), so a
half-written tool exchange is the *normal* state on resume, not an exception. Without this, the
provider rejects the rebuilt conversation and the failure looks like a model error.

### Explicitly **[SKIP]**

* **opencode's permission model as a security boundary.** It is a UX layer; the project says so
  (`SECURITY.md:15-19, 30`). Taking it and calling it a sandbox is the failure mode this whole
  study exists to avoid.
* **Last-match-wins config where JSON key order is load-bearing**
  (`packages/core/src/v1/config/permission.ts:22-24`). A latent footgun; use explicit priorities.
* **The Effect-TS architecture** (layers, `Effect.gen`, `Deferred`, `Semaphore`, `RcMap`). The
  concepts have Python equivalents (`asyncio.Future`, `asyncio.Semaphore`, context managers);
  the framework does not transfer and should not be emulated.
* **Codex's arg0 self-re-exec trick** (`CODEX_LINUX_SANDBOX_ARG0`,
  `CODEX_CORE_APPLY_PATCH_ARG1`). It exists because a single static Rust binary must be its own
  helper. Python already has `python -m app.sandbox_helper`.
* **The AI SDK / provider-protocol layer** on both sides. The host has LiteLLM.
* **opencode's `--yolo` client-side auto-approve** (`cli/cmd/run.ts:797-810`). Auto-approval that
  lives in the client cannot be audited server-side; for a hosted system it must be a server policy.
* **The Windows backends** on both sides.

---

## 8. INTEGRATION NOTES — attaching each [PORT] to this host

Context assumed: `engine/` is a LangGraph graph; `app/` is FastAPI + a single-writer SQLite
(`WAL`, `synchronous=NORMAL`) with `scientific_tasks` as a leased durable queue; LLM dispatch is
LiteLLM; work must survive process restarts.

### 8.1 Where a terminal tool attaches at all

The natural seam is **a new durable task type**, e.g. `engine.exec.command`, alongside the existing
`engine.node.*` / `engine.fanout.*` rows — not a new in-process loop. That gives the shell tool
lease/heartbeat/retry/pause/cancel for free and keeps the "no in-process workflow" invariant.

The engine already has a tool loop (`engine/src/co_scientist/llm_tool_loop.py`, 460 lines,
`call_llm_with_tools`) which executes requested tool calls concurrently under `asyncio.gather`.
A `run_shell` tool registered there is the smallest possible integration — but it inherits that
loop's shape, which is *not* durable: an interrupted process loses the turn. For anything longer
than a few seconds the durable-task route is correct.

**Friction:** the engine's tool path today is MCP-backed (`mcp_client.py`,
`COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS`, default 300 s) and tools are declared in
`config/tools.yaml` with an `mcp_tool_name`. A local sandboxed exec tool is the first tool that is
*not* an MCP call, so either it becomes an MCP tool on a **local** server (clean, keeps one
registration path, but puts the sandbox behind an HTTP hop and the corpus-server's env surface) or
`ToolRegistry` grows a second kind. The MCP route is probably right, with the exec server running
as a sibling container so the sandbox boundary is also a process boundary.

### 8.2 [PORT] 1 — SandboxPolicy + argv transform

Shape it as a frozen dataclass mirroring `protocol.rs:1002-1050`, then one function per backend:

```python
def wrap_argv(argv: list[str], policy: SandboxPolicy, cwd: Path) -> list[str]:
    if policy.kind is Kind.EXTERNAL or policy.kind is Kind.DANGER_FULL_ACCESS: return argv
    if sys.platform == "darwin": return ["/usr/bin/sandbox-exec", "-p", _sbpl(policy, cwd), *_defs(policy), "--", *argv]
    if sys.platform == "linux":  return ["bwrap", *_bwrap_flags(policy, cwd), "--", *argv]
    raise UnsupportedSandbox(...)
```

Copy `seatbelt_base_policy.sbpl` and `restricted_read_only_platform_defaults.sbpl` verbatim — they
are data, Apache-2.0, and encode months of "PyTorch needs `__KMP_REGISTERED_LIB_` shm" debugging
(`seatbelt_base_policy.sbpl:96-99`) that you do not want to rediscover.

**Friction points, honestly:**

* **Production is Linux-in-Docker on Railway.** `bwrap --unshare-user` needs user namespaces, which
  many container runtimes disable. The probe Codex uses (`sandboxing/src/bwrap.rs:74-136`) exists
  precisely because this fails in the wild — and it **fails open**. In a hosted deployment you want
  it to fail *closed*: no sandbox ⇒ refuse to run model-authored code, do not run it bare.
* Codex's answer to "already in a container" is `ExternalSandbox`. Given Railway already gives you
  a container per service, the pragmatic production posture is `ExternalSandbox` + a
  **dedicated exec service** with no DB credentials, no provider keys, and a read-only mount of
  the data it may touch — i.e. let the platform be the sandbox and use the policy object to record
  that fact. Reserve seatbelt/bwrap for local development, where it is genuinely load-bearing.
* **Do not put the sandbox on the API process.** It has the SQLite writer; a `--unshare-pid` child
  that inherits its fds is exactly the shape you do not want near the single writer.
* The seccomp network filter has no clean Python equivalent. Use `bwrap --unshare-net` (coarse but
  real) or a network namespace with only a proxy route, mirroring Codex's `ProxyRouted` mode
  (`linux-sandbox/src/landlock.rs:220-246`).

### 8.3 [PORT] 2 — apply_patch

Implement `parse_patch(text) -> list[Hunk]` + `seek_sequence(lines, pattern, start, eof)` with the
four-stage ladder from `apply-patch/src/seek_sequence.rs`, and expose one LiteLLM function tool:

```json
{"name": "apply_patch", "parameters": {"type": "object", "required": ["patch_text"],
 "properties": {"patch_text": {"type": "string", "description": "<the V4A grammar, inline>"}}}}
```

**Friction:**

* The host's `AGENTS.md` records a hard-won rule: *structured-output schemas must not echo input
  back*. `apply_patch` is the good case here — the patch is the *output*, and output length scales
  with the edit, not with the pool. But note the same document's `THINKING_FLOOR_MAX_TOKENS`
  gotcha: a multi-file patch is a long completion, and on a thinking model it competes with the
  chain of thought for the same allowance. Size `max_tokens` for the patch, and expect
  `LLMBudgetExhaustedError` to be the failure you actually see.
* Every write must land inside the sandbox's writable roots, and `.git`/`AGENTS.md`-equivalent
  paths should be read-only (`permissions.rs:29-33`) — for this repo that list is `.git`,
  `CLAUDE.md`/`AGENTS.md`, `docs/PARITY.md` (machine-checked), and `corpus/`.
* Apply the patch **inside** the sandbox, not from the API process. Codex does this via the arg0
  self-exec; from Python, `python -m app.exec.apply_patch` run under the same `wrap_argv`.

### 8.4 [PORT] 3 + 6 — command policy

Two layers, both plain Python:

* `is_known_safe_command(argv) -> bool`, a direct transcription of
  `is_safe_command.rs:67-127` including the `find`/`base64` flag exceptions and the composite
  `bash -lc` rule.
* A tree-sitter split for approvals: `tree_sitter_languages.get_parser("bash")`, walk
  `descendantsOfType("command")` (`shell.ts:123-125`), and derive an approval pattern per
  sub-command plus an arity prefix from a copied `ARITY` table (`permission/arity.ts:24+`).

**Friction:** `tree-sitter` + `tree_sitter_languages` are wheels with native builds; they must go
into `app/requirements-app.txt` *and* `app/pyproject.toml` (the repo keeps those in sync by hand)
and survive `Dockerfile.api`. If that is unacceptable, `shlex.split` + `bashlex` is a weaker but
pure-Python fallback — accept that it will mis-handle `$( )`.

### 8.5 [PORT] 4 — shadow-git snapshots

Store the shadow git dir **off the Railway volume**, next to the cache
(`COSCIENTIST_CACHE_DIR=/tmp/coscientist-cache`), never on `COSCIENTIST_DB_PATH`'s volume — the
repo's deployment notes are explicit that only the DB belongs there, and a 0.5 GB volume already
filled once. Snapshot ids (tree hashes) are small and belong in SQLite: a new
`hypothesis_workspace(hypothesis_id, snapshot_id, created_at)` row, append-only like the rest.

**Friction:**

* Snapshot capture is a subprocess `git add` over the workspace; on a large data directory that is
  not free. opencode's mitigations — `objects/info/alternates` (`snapshot/index.ts:209-224`) and
  V2's 2 MB untracked-file cap (`snapshot.ts:138`) — are both worth copying, and for a science
  workspace the cap matters much more (datasets, not source).
* Serialize captures per workspace (opencode uses a per-gitdir semaphore,
  `snapshot/index.ts:55-64`). With `worker_pool_size` defaulting to 8, several fan-out tasks could
  otherwise `git add` the same worktree concurrently.
* Do not hold the SQLite write lock across the `git` call. The host's own rule — *never hold the
  write lock across network I/O* — generalises: capture first, then write the row.

### 8.6 [PORT] 5 — approval axes

`AskForApproval` maps onto a per-run setting. The important adaptation: this host is **not
interactive**, so `UnlessTrusted` and `OnRequest` are mostly useless — the analogue is Codex's
`Granular`, where a disabled flag **auto-rejects** rather than blocking
(`protocol.rs:930-934`). Model it as a per-run `ExecPolicy` with `allow / reject / hold`, where
`hold` reuses the existing safety-adjudication surface
(`POST /api/runs/{id}/safety/{decision_id}/adjudicate`) rather than inventing a second one.

**Friction:** a `hold` parks a durable task. The host's task semantics say only
`UnsupportedTaskError` is a permanent failure and nothing automatic recovers a `failed` task —
so a held command must become a `paused` row (resumable) rather than a failed one, and the resume
path must call `revive_task_for_retry` **before** enqueueing, per the existing rule.

### 8.7 [PORT] 8 — long-running commands

An `asyncio.subprocess.Process` handle in a per-run registry, keyed by an id returned to the model
when `yield_time_ms` elapses. **This is the item that fits the host worst**, and it is worth being
explicit about why: the registry is in-process memory, and the host's durable model assumes a task
can be picked up by a different worker after a restart. A running child cannot be.

The honest resolutions are (a) treat a process death as killing the command and report it to the
model on resume — cheap, correct, occasionally wasteful; or (b) run commands under a supervisor in
the exec service with its own pid file, so the API process restarting does not kill them. Given the
existing gotcha that `--reload` already drops the worker cohort mid-task, (a) is consistent with
how the rest of the system behaves and should be the first version.

### 8.8 [PORT] 9 — post-write checks

After an `apply_patch` lands, run the project's own cheap check on the touched files inside the
sandbox and append failures to the tool result, capped. Mirror
`lsp/diagnostic.ts:3, 20-27`: errors only, ≤20 per file, rendered as a compact block. For this repo
that is `ruff check <files>` and, for engine code, `mypy <files>`; for model-authored analysis
scripts it is simply running the script.

**Friction:** this doubles the number of sandboxed spawns per edit. Given the host's measured
finding that per-item LLM passes multiply badly across callers, note that this one does *not* — it
is a subprocess, not a model call — but it does multiply against `worker_pool_size`, so bound it
at the seam rather than per tool.

### 8.9 Also-worth-taking A + B

**A (runtime hygiene).** `env_clear()` + an explicit allowlist is a one-line change to whatever
spawns the child, and it is the difference between the model's shell seeing `DEEPSEEK_API_KEY` /
`LOGS_ADMIN_TOKEN` / `COSCIENTIST_DB_PATH` and seeing nothing. **This is the single highest
value-per-line item in the entire report for this host**, because the API process's environment is
exactly the set of secrets a hypothesis-testing agent must never reach. Pass through only `PATH`,
`HOME`, `LANG`, `TMPDIR` and whatever the analysis genuinely needs. `RLIMIT_CORE = 0` and
`PR_SET_DUMPABLE = 0` are `resource.setrlimit` / `ctypes.prctl` one-liners in a `preexec_fn`.

**Friction:** `preexec_fn` is not async-signal-safe and is unsupported with threads in some Python
builds; prefer `bwrap`'s own flags where available, or accept the narrow window.

**B (interrupted-turn normalizer).** The host already persists tool-shaped work as
`scientific_tasks` rows and checkpoints, so the analogue is: when a run resumes, any exec task left
`leased` past its lease, or `running` at process death, must be written into the reconstructed
conversation as an explicit aborted result before the next model call — not silently dropped.
`revive_task_for_retry` already handles the *queue* side of this; the *transcript* side is missing
and would show up as a provider-rejected malformed conversation after a restart.

---

## 9. Unverified

Stated plainly, per the ground rules.

**Codex:**

* The terminal fallback branch when **both** the system and the bundled `bwrap` are unusable — the
  discovery and warning code was read (`sandboxing/src/bwrap.rs:74-191`,
  `linux-sandbox/src/launcher.rs:36-70`), the final branch was not traced.
* `codex-rs/responses-api-proxy/` internals (distinct from `network-proxy/`, which was read).
* Windows job-object *limits* — `JobObject` lives in the external `codex-utils-pty` crate.
* Whether Windows `read_only_subpaths` agree at runtime with the protocol-side definition.
* Process-group kill semantics on abort — `core/src/tools/parallel.rs:178-200` cancels and aborts
  the dispatch task; the path down to `kill(-pgid)` for `exec` was not traced.
* Rollout retention/GC — `rollout/src/maintenance.rs` is a lock for compression/migration, not
  deletion; whether a TTL exists elsewhere is unknown.
* Internals of `rollout/src/state_db.rs`, `session_index.rs`; `thread-store/src/{live_thread,store,
  thread_metadata_sync}.rs`; `state/src/{runtime,migrations,log_db}.rs` — inventory only.
* Callers of `Op::RecoverTurn` — the handler exists, no invoker found.
* `code-mode` tool schemas (`CodeModeExecuteHandler`/`CodeModeWaitHandler`), MCP elicitation
  (`elicitation.rs`), `apply-patch/src/streaming_parser.rs`.
* Windows safe/dangerous command list *contents* (call sites verified, entries not enumerated).

**Two documentation-vs-code discrepancies found in Codex** (drift, not bugs):

* `linux-sandbox/README.md:91-92` says seccomp blocks "AF_UNIX/socketpair creation" in
  managed-proxy mode; the code blocks `socket(AF_UNIX)` but **permits `socketpair(AF_UNIX)`**, with
  a comment explaining why (`linux-sandbox/src/landlock.rs:218-247`).
* `linux-sandbox/src/landlock.rs:135-136` documents
  `install_filesystem_landlock_rules_on_current_thread` as "currently unused"; it is called at
  `:84`.

**opencode:**

* Whether the V2 (`lildax`) path ships in any released binary, or is preview-only.
* V1's `packages/opencode/src/patch` parser internals (call sites read, body not).
* `packages/core/src/pty/` — present, no consumer found.
* `packages/opencode/src/tool/plan.ts` and `code-mode.ts` bodies.
* `packages/effect-sqlite-node` appears unimported at this commit — deliberate staging or leftover
  is unknown.

**One opencode prompt-vs-code discrepancy, which matters if copied:**
`packages/opencode/src/tool/write.txt:5` and `edit.txt:4` tell the model *"This tool will fail if
you did not read the file first"*. No read-before-write check exists in either tool, and no
read-time tracker exists anywhere in `packages/*/src`. `edit.txt:8` also quotes an error string
that does not match the real one (`edit.ts:725`).
