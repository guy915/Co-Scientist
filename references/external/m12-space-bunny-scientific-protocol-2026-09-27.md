# Space Bunny fixed-input scientific screen

**Status:** prepared, no comparison calls made. This local design-choice screen
tests the selected `openrouter/stealth/space-bunny-alpha` route; it does not
establish expert validation or knowledge of Google's private implementation.
The owner stopped broad model benchmarking. Authentication alone does not
authorize inference. Record separate authorization before starting this screen.

## Fixed boundary and comparison

Use the existing public `app.claims.assess_claims_batch` and citation-evaluation
interfaces on base product commit `b7e9a0d3260cb769e17561e7ab3a415756907619`.
The primary measure is agreement with the frozen gold judgments **and** valid
source-matched quotes, not an LLM's self-reported score. Pair each selected-route
result with the gold judgment for the identical input. This is a case-matched
absolute-quality screen, not a concurrent model comparison. The retained three
Nex Pro series on those inputs are historical context only: that route was
absent from the catalog at the last assessment and the local citation resolver
has changed, so those outputs cannot prove controlled model superiority. Hold
the assessor code, inputs, request
settings and evaluators fixed across selected-route trials; if any changes,
commit an amendment before further calls and restart the full affected series.

1. Four-claim batch: `references/external/baseline/model-qualification/partial-support-scope-controls.json`
   (SHA-256 `f5e70ede3f73549e071e21579d3e7d41dac8afdf815443be51037a4b21696015`),
   selected in `batch-schema-preflight109.json` (SHA-256
   `455b6c7481fde3a7cda19d9a4bd39b5e5d810d7b8685bef1ac18b2f93fce3a21`).
   Three fresh-process, cache-isolated trials. Each must send all four claims
   together in exactly one physical request, return `partial`, `supports`,
   `insufficient`, `contradicts` in order, and have the actual-interface
   quote, cited-source, offsets and verification-method results checked
   against the frozen public cases without deterministic fallback.
   The existing `probe_batch_schema.py` (SHA-256
   `4fdd6b86e92e8d0c892b3c3b7fda98e1a5be7498e2980b728cc4d1f570d2a2aa`)
   is the runner; do not alter it after this protocol without an amendment.
2. Only if all three batch trials pass, use
   `evaluations/datasets/citation_entailment_challenge_v1.json` (30 public
   items; SHA-256 `1636ddcfb94084ccabe5f155fd5701c3270c7ffc751e1c16a6450cece61c39f2`)
   through `probe_citation_panel.py` (SHA-256
   `a8c9b650837f71531b84ec3aaff2b63b53d01e7679f68d17d0adb941838d5b23`).
   Three fresh-process, cache-isolated trials, at most 80 physical requests
   each. Each must score at least 27/30 correct, contradiction recall at least
   0.80, no new false contradiction, and pass the existing historical,
   controlled-primary, and single/batch scope controls without fallback.
   Retain one result per trial with the identical evaluator and input hashes.

Before each batch, verify the exact model and Stealth endpoint still advertise
zero prompt and completion prices on official OpenRouter metadata **and**
establish from authoritative terms or a binding request control that no
per-request fee can be charged. The project request guard must pin Stealth,
disable fallbacks, reject nonzero rates, and send zero prompt/completion price
ceilings. Its `request: 0` field is not a documented binding fixed-fee cap;
if a zero-fee path cannot be verified **before** the call, do not send it.
Verify actual provider/account cost afterward as an independent check. No paid
tool, plugin, embedding, auxiliary route or alternate credential may be used.
Require the exact served model, complete physical-request usage, request/error records,
and unique artifact filenames. Never display or store credentials in artifacts.

Stop the series on the first unqualified price, route, cost or safety condition,
missing telemetry, terminal provider error, wrong-scoped quote, failed trial,
or rate limit without a bounded reset. Do not retry an ambiguous accepted
request, silently substitute a model, selectively rerun a bad trial, or loosen
a threshold. A failure makes this selected route unqualified on the declared
screen; mixed or incomplete evidence remains inconclusive. Do not infer broad
scientific quality, repeat-run reliability, or wet-lab validity from a pass.

**Execution prerequisite:** before calls, verify that both older probe runners
still reach the current production boundaries on this exact commit and produce
complete route/cost telemetry. Any required runner correction changes a hashed
source and needs a committed protocol amendment first. The comparison is open
until observed artifacts meet the stated rules; protocol preparation is not
an acceptance result.
