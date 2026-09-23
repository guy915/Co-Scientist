# Nemotron scientific qualification — cycle 182 interruption

## Frozen input and eligibility

- Requested model and all model roles: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`.
- Frozen source revision: `7ebd9ebc3f5c595bc2ff5cfdff91fafaf5b11c39`.
- Frozen source manifest: [`nemotron-current-sources182.json`](nemotron-current-sources182.json), SHA256 `c8bc3b99139ae765cb8d7ba2031404291a7bb2382d039a7a65753a044615aa7c`; 586 current runtime source hashes.
- Challenge input: 30 items, SHA256 `1636ddcfb94084ccabe5f155fd5701c3270c7ffc751e1c16a6450cece61c39f2`.
- Historical controls: 5 items, SHA256 `2c226b079f5337b76919a842245744b429fbb76d78cc4ff70661b94f1300ec3a`.
- Scope controls: 10 items, SHA256 `f5e70ede3f73549e071e21579d3e7d41dac8afdf815443be51037a4b21696015`; helper SHA256 `e059c65dda9c0cd69cf55b86725e695aa03f2e70270cae7204f28897db1db6de`.
- Gates were unchanged: accuracy `>= 0.75` and contradiction recall `>= 0.80`, required in all three trials.
- Fresh credential-free eligibility was checked before recovery trial1 at `2026-09-22T09:51:18.093133+00:00` and before recovery trial2 at `2026-09-22T10:06:33.454920+00:00`; both had 444 catalog entries, prompt/completion pricing `0`, and runtime eligibility acceptance. Receipts: [`nemotron-eligibility182-recovery1.json`](nemotron-eligibility182-recovery1.json).

## Artifacts and process

- Original setup-failure receipts: `nemotron-challenge182-1.json`, `nemotron-challenge182-2.json`, and `nemotron-challenge182-3.json`. Each made 0 provider requests and failed before inference because the editable venv resolved `co_scientist.cache_storage` through the case-variant `/Users/guy/Code/Co-Scientist` path, which the source guard correctly rejected against `/Users/guy/Code/co-scientist`.
- Corrected recovery receipt: [`nemotron-challenge182-recovery1-1.json`](nemotron-challenge182-recovery1-1.json). It contains the only completed scientific batch.
- Recovery trial2 had no JSON artifact; its partial log is `/private/tmp/coscientist-nemotron-challenge182-recovery1-2.log`. Trial3 was never launched.
- Recovery parent session: `28940`; launcher PID `3065`; trial1 child PID `3066`; trial2 child PID `4872`. The coordinator terminated the launcher after the overload pattern; session `28940` ended with exit code `1`. No process remains.

## Exact results

Recovery trial1 completed the 30-item challenge and historical controls before a post-run manifest lookup raised `KeyError: 'scope_controls_sha256'`. The manifest stored those hashes only under nested `scope_controls`; the existing probe requires the top-level fields. Therefore the observed metrics are retained as diagnostic evidence, not accepted as a valid trial:

| Trial | Physical requests | Observed metrics | Controls | Status |
| --- | ---: | --- | --- | --- |
| Recovery 1 | 65 | accuracy `0.733`; contradiction recall `0.400` | historical pass; scope unavailable | invalid/inconclusive after post-run `KeyError` |
| Recovery 2 | unavailable; no artifact | unavailable | unavailable | interrupted during repeated upstream overload |
| Recovery 3 | not launched | unavailable | unavailable | stopped before launch |

All 65 recorded trial1 requests used the requested Nemotron route and carried `max_price.prompt=0`, `max_price.completion=0`, and `max_price.request=0`. Forty-one requests had observed response model and usage records; 24 had no response record. The log contains 25 `ServiceUnavailableError` messages from Nvidia upstream overload. Historical controls passed with 9 physical requests; the controlled-primary check passed with 2 verifier requests. Scope controls did not run because the manifest field lookup failed. One challenge assessment is recorded as `deterministic_lexical` after provider failure; the metrics are therefore diagnostic and are not a pure-model qualification result. No paid route, credential output, or scientific qualification claim is recorded.

The trial2 partial log contains two additional upstream overload errors before termination. The coordinator stopped the active batch to avoid repeated provider retries; no further trial or recovery launch was made.

## Remaining

Nemotron remains scientifically unqualified. Cycle 184 reproduced the missing-field error offline and created [a corrected manifest](nemotron-current-sources184.json), retaining the scope hashes at the top level required by `probe_citation_panel.py` and in the descriptive nested record. All 586 source hashes and frozen inputs remain unchanged; the original manifest and failures are preserved. A future batch requires fresh eligibility and evidence that the upstream can serve requests; no automatic retry was scheduled. No production or scientific source changes were made. The ephemeral launcher's terminal-error rule was corrected separately for future invocations; this already-running batch retained its earlier loaded rule.
