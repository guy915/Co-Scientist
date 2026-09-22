# Bounded Nemotron long-input recovery — cycle 181

## Selected action and rationale

- **Requested model:** `openrouter/nvidia/nemotron-3-super-120b-a12b:free`
- **Source revision:** `d65785ade0b8ecb41f8bbb4aa630e931840c4951`
- **Action:** Run exactly the existing `probe_capabilities.py` `long_json` case once.
- **Rationale:** Nemotron had already passed short JSON, tools and streaming in retained evidence, while its representative long-input case remained unresolved after operational upstream overload in cycles 164, 167 and 178. Qwen was deferred after three first-request shared-pool `429` stops. This targeted retry resolves the highest-value remaining Nemotron capability gap without repeating completed checks or starting a scientific batch.

## Artifacts

- Fresh credential-free eligibility: [`nemotron-super-eligibility181.json`](nemotron-super-eligibility181.json)
- Capability result: [`nemotron-super-capabilities181.json`](nemotron-super-capabilities181.json)
- Existing runner: [`probe_capabilities.py`](probe_capabilities.py), SHA256 `1a470cc7c7fb6cf7e35b0d116c65dc5e0ba4c88854ae0f73127a82ff78574abf`

The public catalog was refreshed at `2026-09-22T09:35:32.136629+00:00` before credential loading or inference. It contained 444 entries; the exact route remained eligible with prompt/completion pricing `0`, text input/output, `structured_outputs`, `response_format`, tools and 262,144 context. Raw catalog SHA256: `d8ba143c28bb357057b804677f5681c158320e9a752dfd1f75462abb7381733c`.

## Exact outcome

- `long_json`: **pass**. The 126,555-character public synthetic prompt returned `supports` with the exact supplied passage quote.
- Physical requests: `1`; served model observed: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`; usage reported: 29,187 prompt, 226 completion and 222 reasoning tokens; latency `4.7214527080068365s`; retries `0`; deterministic fallbacks `{}`; static estimate `$0`; billed receipt `null`.
- The captured request carried `max_price.prompt=0`, `max_price.completion=0`, and `max_price.request=0`, with no paid fallback route. The model's effective request used JSON-object mode and the repository-declared reasoning profile (`enabled=true`, `max_tokens=2048`) even though the case requested thinking off; this is retained as observed behavior, not evidence that the endpoint itself requires reasoning.
- `json_off`, `json_on`, `tools`, `streaming`, `long_json_on`, and all scientific cases were unavailable in this bounded batch by design. Prior successful evidence for the first three interface families remains retained; no scientific batch was started before full capability qualification.
- Credential handling: the launcher extracted the existing OpenRouter credential in process memory only, disabled dotenv, removed other API-key variables through the existing runner, and wrote no credential to artifacts or logs.

## Process and remaining steps

- **Process handle:** no PTY/session handle was allocated; the isolated inline launcher completed with exit code `0` and printed `long_json True None`.
- **Terminal:** yes; no capability process remains from this invocation. A later `ps` inspection was unavailable under the sandbox, so terminality is established by the completed non-session command rather than process enumeration.
- Nemotron's representative long-input compatibility gap is now resolved for this probe. It remains unqualified for production until the campaign's independent fallback qualification, scientific panels, full workflow and release checks complete. Qwen remains operationally unqualified behind its retained shared-pool `429` evidence. Gemma's fresh catalog lead remains a possible later compatibility candidate; it was not broadened into this cycle.
