# Shared-service campaign policy verification

Reviewed implementation: `d8eaf38ba03e47c5ae7ab3419c769ec6e3a36961`.
These are local behavioral results, not deployment or scientific acceptance.

| Item | Behavior and evidence |
| --- | --- |
| scope-a | Verified bearer allowlist derives persisted run/interview policy; legacy rows default to standard; unsigned identity/body spoofing cannot originate campaign; linked interviews retain policy after configuration changes. `app/tests/test_campaign_policy_persistence.py` exercises migrations, public creation and restart readback. |
| scope-b | Context is monotone and restored across streams, deferred work, task recovery, reused threads and nested safety workers. Captured policy survives row deletion; missing-row compatibility paths abort. `test_campaign_policy_scope.py`, `test_async_bridge.py`, `test_engine_drain_escalation.py`, `test_interviews_stream.py` and engine `test_campaign_context.py` cover these boundaries. |
| scope-c | Policy headers require the existing secret, including policy-bearing root requests. Actual FastMCP SDK concurrent sessions observe campaign/standard/standard-after. Clients partition by event loop, resolved configuration and policy. MCP auth/context tests and engine client/admission tests cover the implementation. Existing campaign invocation guards remain in place. |
| scope-d | Public API creation, persisted identity removal and expired-lease recovery reach actual paid-price admission: campaign transport is blocked; ordinary BYOK reaches its exact model/key. `test_campaign_policy_integration.py` substitutes the node body and provider transport, not policy admission. Concurrent isolation is separately exercised by engine context and real MCP SDK tests. |

Coordinator verification on the final commit: 32 app policy, recovery, safety,
bridge and stream tests passed; all nine offline browser tests passed in 35.8s.
Earlier full runs passed 3,134 engine tests (two existing skips), 1,872 app tests
and 279 MCP tests. Final complete backend invocation is recorded separately in
PLAN.md; do not combine earlier partial invocations into a claimed passing run.
Build and all 718 frontend tests passed; frontend source is unchanged.

Independent review closed nested-thread leakage, deletion-race downgrade and
explicit-stream-close cleanup findings. The closing reviewer inspected code;
the coordinator supplied runtime tests from the configured virtualenv.

Campaign context activates the existing cache, tool, workspace and credential
restrictions without process-global environment changes. Production must keep
the global flag off and configure `CAMPAIGN_RESEARCHER_IDS` as a JSON array of
verified bearer subjects. A consistent production backup must include all three
additive columns before merge. Real deployed coexistence, final free-model
selection, security review and the live scientific workflow remain unverified.
