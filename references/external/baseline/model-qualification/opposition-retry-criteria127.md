# Q2 live compatibility check

Local reliability verification, declared before inference at bf08a788.
Run three fresh Mini processes using the existing historical_controls function
and frozen historical-negative-controls.json. Retain its five fully live
controls and separately labelled controlled-primary/live-verifier control.
Every existing control must pass, with at least one actual verifier request.
Record the actual per-call schema without changing it: minItems must match
supplied pair count, with no maxItems and the existing two-attempt ceiling.
Require fresh zero-price admission, binding zero request caps, expected served
model and complete usage for successful calls, and no deterministic fallback.
Every verifier invocation must return a complete envelope: exactly the expected
verdict count and index set, both booleans typed, and no terminal exception.
A controlled negative outcome alone does not prove this: exhausted verification
also fails closed. Retain normalized returns/errors beside actual request evidence.
Preserve errors and all failed outcomes; no selective replacement.

The public-interface red/green tests establish malformed-response recovery and
two-pair behavior. These live controls establish provider/schema compatibility
and unchanged confirmatory-evidence protection. They do not claim that a live
model was made to produce an empty response, nor qualify Mini scientifically.
