# Space Bunny comparison preflight

**Classification:** local design choice. **Result:** offline preparation complete;
no scientific comparison or provider inference was performed.

- An existing OpenRouter API key authenticated with a read-only `GET /api/v1/key`
  (HTTP 200). The key and account identifiers were neither printed nor retained.
- OpenRouter's [Space Bunny model page](https://openrouter.ai/stealth/space-bunny-alpha)
  calls the route free. Its [billing FAQ](https://openrouter.ai/support/)
  says inference cost is computed from provider usage and that its separate fee
  is charged when purchasing credits. Together, these are the authoritative
  basis for treating this model's current inference path as having no fixed
  request fee. This is an inference from the published billing explanation,
  not an account-level billing receipt. The exact endpoint prices and route
  must be checked again immediately before any trial.
- `probe_batch_schema.py` reaches `app.claims.assess_claims_batch` and its
  physical-request/usage observer. `probe_citation_panel.py` reaches the
  existing citation evaluator, with one run-scoped 80-request counter shared
  across its phases. Their protocol-pinned source hashes are unchanged.
- The focused offline command
  `.venv/bin/python -m pytest -q references/external/baseline/model-qualification/test_probe_batch_schema.py references/external/baseline/model-qualification/test_probe_terminal_errors.py`
  first failed three tests because the mock reply cited input-order passage
  numbers after production's evidence union reordered the prompt. The fixture
  now cites the numbers actually shown; the same command passed **40/40**.

The existing [committed protocol](m12-space-bunny-scientific-protocol-2026-09-27.md)
and frozen inputs are unchanged. Authentication and preflight do not authorize
the owner-stopped comparison; no scientific-quality claim follows from them.
