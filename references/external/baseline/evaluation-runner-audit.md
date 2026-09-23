# Evaluation runner audit

Inspected 2026-09-19 at `5b39e218`. Classification: local design choice.
This is source evidence, not live inference or verified free-model selection.

| Entry point | Observed gap | Required disposition |
| --- | --- | --- |
| `_run_driver.py`, scaling, ablation, claim-support | Shared loader reads DeepSeek from environment or root `.env`; scaling and ablation live modes require it | Shared explicit campaign configuration before app imports; preserve offline runs |
| `golden_run.py` | Duplicated DeepSeek loader; implicit model; fixed INDRA tools | Remove paid assumptions; fail closed on unqualified tools without weakening INDRA acceptance |
| `citation_eval.py`, `elo_concordance_eval.py` | Missing MODEL_NAME defaults to paid DeepSeek | Explicit admitted model configuration |
| `citation_usefulness_eval.py` | CLI model defaults to DeepSeek | Explicit admitted model configuration |
| `app/app/config.py` | Pydantic reads `.env` independently | Prevent dotenv restoration in isolated evaluation processes; clearing environment alone is insufficient |
| `_run_driver.compute_arm_metrics`, `golden_run._cost_summary` | Reduce usage to estimated cost; missing cost becomes zero | Retain observed usage and distinguish unknown pricing from verified zero |
| Direct model panels | No scoped served-model telemetry | Reuse engine telemetry; label missing provider identity rather than claim observed service |
| Comparison drivers | No enforced complete frozen configuration identity | Record and compare model/fallback/input/cache settings across paired trials |

The engine's `llm_request` physical transport already performs fresh free-route
admission. Reuse it; do not duplicate catalog eligibility in runners. A free
suffix alone is neither sufficient nor necessary under the existing policy.
`llm_telemetry` captures response model when available but falls back to requested
model when absent; retained evidence must disclose that distinction. A local
cost estimate does not independently prove the amount billed.

`prod_smoke.py` and `mcp_live_smoke.py` do not themselves perform model inference,
but their network/tool paths still require qualification. In particular, do not
run the INDRA smoke path under an assumed free authorization. Offline evaluators
and import/export panels must remain offline. Inspect standalone engine developer
runners before any future campaign use; they are not authorized escape routes.

Verification boundaries are the existing LLM request boundary, durable research
workflow and evaluator artifacts. Reproduce paid/default credential loading with
synthetic secrets in isolated processes before changing behavior. Exercise
fallback served-model reporting, unknown usage, dotenv isolation and mismatched
comparison rejection. No production credentials or private research inputs belong
in fixtures. Live capability and full research qualification remain later M1 work.
