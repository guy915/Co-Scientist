# M1 deployment scope

Investigation date: 2026-09-22. This is a proposed architecture, pending the
MCP and trusted-entry decisions below; it is not production acceptance.

## Finding

`campaign_free_mode()` reads `COSCIENTIST_REQUIRE_FREE_MODELS` process-wide.
The predicate gates provider admission, LLM and node caches, workspace network
and skill credentials, and caller-side MCP qualification. `enforce_free_request`
therefore wins over an explicit BYOK key whenever the deployment flag is on.
The durable worker already reloads credentials per task and scopes app and
engine credentials; `async_bridge` propagates context across child and
off-loop work. The reference MCP server is a separate process and its campaign
policy is also process-global.

## Alternatives

1. Enable the campaign flag globally on the existing API and MCP. Reject for
   shared production: every run becomes campaign-restricted and explicit BYOK
   is refused by design.
2. Leave the flag off and rely on system-default `:free` admission plus a
   globally campaign-enabled MCP. Insufficient: only non-BYOK `:free` model
   calls are admitted; app-side configured-model calls, workspace, cache and
   durable auxiliary calls remain outside the run's campaign boundary. The MCP
   process also cannot distinguish a campaign caller from an ordinary one.
3. Add a separate campaign API/worker/MCP deployment. Strong isolation, but
   it changes the requested existing-production path and adds routing, worker
   ownership and database coordination.

## Proposed route

Use the existing API with the global flag off and add a trusted, persisted,
non-secret run marker such as `execution_policy: "campaign"`. In
`engine/src/co_scientist/llm_free_policy.py`, add a monotone `ContextVar` scope
(`scoped_campaign_mode(True)`), resolving true when either the scope or the
legacy environment flag is true. Enter it in `app/app/engine_tasks.py` beside
the existing BYOK scopes, and in campaign-owned request/background/streaming
entry points. Reuse the existing cache, credential and async-bridge context
patterns; recovery, resume and lease reclaim must derive the marker from the
run row. Partition `mcp_client.py`'s cache by campaign policy so a client
discovered in one mode cannot be reused in the other.

Keep MCP globally campaign-safe only if production accepts the public-tool-only
surface for all callers. If ordinary BYOK users need metered/custom MCP tools,
the release must instead add request-scoped server admission (a trusted
campaign header plus server-side enforcement) or a second MCP service; the
current global MCP policy cannot provide coexistence.

## Test-first acceptance

- Concurrent campaign and paid-BYOK durable tasks: zero-price admission and no
  cache/workspace egress for campaign; user model/key and normal cache/tools for BYOK.
- Direct app calls, title/restatement, QA, safety and claim helpers inherit the
  campaign scope; context is empty after return and survives bridge/off-loop work.
- Restart, resume and lease recovery preserve the marker without checkpointing
  secrets; MCP stale-client and policy-change checks still fail closed.
- Production MCP root policy, exact endpoint, tool set and ordinary-user needs
  are observed before release.

## Unknowns

Confirm the deployed MCP policy/tool list and whether ordinary BYOK runs require
any removed metered or domain tools. Confirm the trusted campaign entry path,
campaign model configuration for app-side calls, and whether campaign interview
traffic must also be scoped.
