# Production model-route boundary

**Finding:** The deployed public `POST /api/runs` request has no per-run model
selector. A campaign-owned production run cannot pin Space Bunny through this
interface independently of the process model-role settings. This read-only
finding makes M12-03b's production goal and Robin refinement unverified; it
does not report a failed run.

| Boundary | Current implementation | Consequence |
|---|---|---|
| Run creation | [Run request](../../app/app/runs_models.py) accepts the goal, interview, tier, focus and run controls, but no model field. The [client](../../app/frontend/src/api/runs.ts) sends those fields. Campaign status is server-derived by [execution policy](../../app/app/execution_policy.py). | A caller cannot safely override unknown production role settings by naming Space Bunny. |
| Model roles | [Settings](../../app/app/config.py) provide worker, supervisor, chat, semantic-safety and optional claim-verifier roles. [Engine dispatch](../../app/app/engine_adapter/opts.py), [safety](../../app/app/safety.py) and the [claim gate](../../app/app/engine_tasks_gate.py) resolve those roles from process settings. | Changing source defaults alone does not override Railway process values; historical values do not prove current values. |
| Exact-zero route | The [free policy](../../engine/src/co_scientist/llm_free_policy.py) checks the current catalog and sets zero price caps; [gateway routing](../../engine/src/co_scientist/llm_gateway_routing.py) pins Space Bunny to Stealth with provider fallback disabled. OpenRouter's [endpoint listing](https://openrouter.ai/api/v1/models/stealth/space-bunny-alpha/endpoints) on 27 September showed one Stealth endpoint with zero prompt and completion prices. | These safeguards apply when the role actually selects Space Bunny. They do not prove that production roles currently do. |
| Robin refinement | The [action](../../app/app/outcome_refinement_action.py) requires an owned, completed, engine-backed run and an eligible parent; [targeted evolution](../../engine/src/co_scientist/agents/evolution/evolve.py) restores `model_name` from the parent checkpoint. Claim and safety calls can still use process roles. | The action cannot retarget an arbitrary parent run to Space Bunny; the parent and auxiliary roles must already be safe. |

The exact production role-value read was rejected by automatic approval review
and remains unavailable. No credentialed read, provider inference, model-role
mutation, production goal, or Robin action was performed for this assessment.
Options considered were changing source defaults, assuming historical Railway
values, adding a per-run selector, or retaining the gate. The first two cannot
prove the route; a selector would be a new product behavior requiring its own
design and release checks. Retain M12-03b until an approved readback or another
independently verified, fail-closed route can establish the roles before a live
run. The earlier local Space Bunny run remains operational evidence only.
