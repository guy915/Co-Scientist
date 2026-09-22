# Bounded Gemma 4 26B capability qualification — cycle 185

## Selected action and rationale

- **Requested model:** `openrouter/google/gemma-4-26b-a4b-it:free`
- **Source revision:** `b3f2e31621d82a226fdabfa2def5637fbb6023f1`
- **Action:** Run the existing `probe_capabilities.py` cases one at a time in fresh processes, stopping on the first provider operational failure.
- **Rationale:** Gemma 4 26B was a previously untested zero-price compatibility lead. The fresh public catalog advertises text input/output, `response_format`, tools and 262,144 context at prompt/completion price `0`. Gemma 4 31B had previously stopped on a shared-pool 429; this cycle tests the distinct 26B route without assuming capability from the family name.

## Eligibility and artifacts

- Fresh credential-free eligibility: [`gemma26-eligibility185.json`](gemma26-eligibility185.json), checked `2026-09-22T10:15:08.126722+00:00` against 444 catalog entries. Raw catalog SHA256: `817012b6ae70c5c3d1d0dc886d5d1b153a13f2ba3dc41014022b8376f382cf81`.
- Existing runner: [`probe_capabilities.py`](probe_capabilities.py), SHA256 `1a470cc7c7fb6cf7e35b0d116c65dc5e0ba4c88854ae0f73127a82ff78574abf`.
- Capability artifacts: [`gemma26-capabilities185-json_off.json`](gemma26-capabilities185-json_off.json), [`gemma26-capabilities185-json_on.json`](gemma26-capabilities185-json_on.json), and [`gemma26-capabilities185-tools.json`](gemma26-capabilities185-tools.json).
- The first launcher attempt (`6839` / child `6841`) failed before inference because its clean child environment omitted the repository root from `PYTHONPATH`, so `evaluations._live_config` could not import. It produced no artifact or provider request. The corrected launcher added the canonical repository root alongside `app`, `engine/src`, and `evaluations`; no repository source or runtime file changed.

## Exact outcomes

| Case | Result | Physical requests | Provider evidence | Stop state |
| --- | --- | ---: | --- | --- |
| `json_off` | fail, operational | 1 | `NotFoundError` 404: no endpoint accepted the requested structured-output parameters | launcher continued because its initial classifier did not include `NotFoundError` |
| `json_on` | fail, operational | 1 | Same provider-routing `NotFoundError` 404 | launcher continued because its initial classifier did not include `NotFoundError` |
| `tools` | fail, operational | 1 | `RateLimitError` 429: Google AI Studio upstream shared pool temporarily rate-limited | launcher stopped immediately |
| `streaming` | unavailable | 0 | not attempted after the 429 | unavailable |
| `long_json` | unavailable | 0 | not attempted after the 429 | unavailable |

Each recorded request used the exact requested Gemma route and carried `max_price.prompt=0`, `max_price.completion=0`, and `max_price.request=0`; there were no retries, observed served-model identities, usage records, paid fallbacks, or deterministic substitutions. The `json_off` and `json_on` 404s occurred with the runner's native named JSON schema envelope. The tools 429 occurred with the local tool-loop request. The runner rechecked current catalog eligibility at the start of each selected case; the initial preflight was performed before credential loading.

No scientific panel or deployment action was started. Gemma 4 26B remains capability-unqualified, with streaming and long-input behavior unavailable and structured-output/tool compatibility operationally unresolved.

## Process handle and remaining steps

- Corrected batch parent session: `87144`; launcher PID `6895`.
- Child PIDs: `6896` (`json_off`), `6900` (`json_on`), `6911` (`tools`).
- Parent exited `0` after the intentional first-429 stop; no capability process remains.
- No rerun is planned today. A future cycle may reassess current provider availability and, if authorized, retry the unresolved cases after backoff; no paid route or credentialed provider substitution is permitted.
- This cycle changed no runtime, PLAN, deployment, schedule or committed source files.
