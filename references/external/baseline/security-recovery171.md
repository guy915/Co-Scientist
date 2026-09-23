# Security preflight recovery — cycle 171

Status: diagnosed; no helper rerun, configuration edit, scan replacement, or
substantive security review was performed.

## Diagnosis

The existing scan is `37397870-2c59-4fa1-b638-30445fd598f6`. Its cycle-167
receipt records the same error returned by the helper:

`agents.max_threads cannot be set when multi_agent_v2 is enabled`

The active user config has the conflicting pair:

- `/Users/guy/.codex/config.toml`, `[features]`: `multi_agent_v2 = true`
- `/Users/guy/.codex/config.toml`, `[agents]`: `max_threads = 6`

The current runtime evidence is native multi-agent V2 with a seven-thread
session cap including the root thread; delegation and goal tools are available.
This makes the V2 interpretation and the conflict unambiguous.

In `codex-security/0.1.24/scripts/config_preflight.py`,
`resolve_multi_agent_context()` resolves the config and then raises at lines
536–542 when native V2 is enabled and `agents.max_threads` is present. The
exception is caught by `main()` and returned as an error envelope before
`evaluate()` can construct `results`, `user_config_path`, or `remediation`.
Therefore the missing remediation is a helper validation-path consequence,
not evidence that a safe patch was discovered and omitted.

## Supported recovery

When a persistent config edit is authorized, remove only the
`max_threads = 6` entry from the `[agents]` table in
`/Users/guy/.codex/config.toml`. Preserve the rest of the table and config;
`agents.max_depth` is a V1 setting and is not needed for native V2. Do not
disable V2, invent an `effective-config` override, or use a lower-precedence
project edit to conceal the user-config conflict.

Then rerun the existing scan's preflight once with the already verified facts:

```text
python3 /Users/guy/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.24/scripts/config_preflight.py --profile security_diff_scan --cwd /Users/guy/Code/co-scientist --runtime-check delegation_available=true --runtime-check goal_tools_available=true --multi-agent-runtime-owner native --multi-agent-runtime-version v2 --multi-agent-session-cap 7 --multi-agent-runtime-provenance tool-surface
```

Continue the preserved scan only if that rerun returns `ready`; otherwise
retain it in preflight and record the new helper result. Do not create a new
scan or repeat the unchanged failing invocation.
