# Baseline verification — cycle 41

Code revision: `403134a4` (subsequent change only corrects the safety test module docstring).
These are local offline checks, not live model qualification or production acceptance.

| Check | Result |
| --- | --- |
| `make test-all` | Exit 0; engine 3124 passed / 2 existing skips, app 1828 passed, MCP 274 passed, MCP mypy and parity/evaluation tests passed |
| `make lint` | Exit 0 in cycle 40; no executable source changes since |
| `make typecheck` | Exit 0 in cycle 39; cycle 40 safety fixture additionally passed targeted mypy |
| `make build` | Exit 0; frontend build and public-route prerender completed |
| `make eval-smoke` | Exit 0; offline safety and citation evaluations passed |
| `bun run test` in app/frontend | Exit 0; 119 files, 718 tests passed |
| `make e2e` | Exit 0; nine Chromium tests passed against isolated offline backend |
| Final safety escalation regression suite | Nine passed after the final fixture assertions; repeated after docstring cleanup |

Local command logs are `/tmp/coscientist-cycle40-test-all.log` and
`/tmp/coscientist-cycle41-{build,smoke,frontend,e2e}.log`.
The full suite ran with host execution permission for macOS confinement tests.
No assertions, thresholds or skips were changed to pass these checks.
The full-suite evaluation output suppresses a summary count; its command exit
was observed directly rather than inferred from a log fragment.

The baseline-suite checkbox is complete. Live model qualification, verification
provenance, the discovered publication-evaluator safety gaps, a full public-evidence
research run, deployment verification, and final baseline freeze remain open.
Later relevant code changes invalidate affected checks before release.
