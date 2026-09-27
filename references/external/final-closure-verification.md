# Final scoped closeout verification — 25 September 2026

The product tree in this branch is identical to the released `origin/main` merge
`91c70ed0dd23b34529f19fbfb9331b247d56ef9d`. The final diff changes only
`PLAN.md` and `references/external/`; the unaccepted PubMed pilot instrumentation
in the separate M11 branch is excluded. The release-time checks for that exact
product code passed `make test-all`, `make lint`, `make typecheck`, `make build`,
`make eval-smoke`, frontend Vitest (803 passed), and browser E2E (18 passed), as
recorded in [the Robin UI release receipt](robin/m11-ui-release-verification.json).
The hosted GitHub CI waiver was owner-authorized; CI is **not** counted as passed.

Fresh on this final branch, with `PYTHONPATH` set to this worktree's root,
`engine/src`, and `app` (and the already installed campaign Python environment):

- `pytest evaluations/tests/test_function_length.py -q`: 3 passed.
- `python -m evaluations.smoke`: safety and citation offline evaluations passed.
- Static link check over `PLAN.md` and `references/external/**/*.md`: 413 local
  links, zero missing targets.
- JSON syntax check: 290 valid retained JSON artifacts; two zero-byte raw files
  are deliberately excluded. They are the previously retained
  `dots-challenge128-2.json` baseline artifact and the first stopped precise-rung
  invocation's empty reserved output. Their status is documented in the
  adjacent baseline summary or failure record and Plan log; they are not
  parsed as results.
- `git diff --check`: passed after the reference-only import.
- Secret-pattern scan of the retained reference directory: 194 generic matches
  were reviewed by field and value shape; all were 64-character SHA-256 hashes
  or deployment/service UUIDs, with no credential-shaped value identified.

The [experimental-branch receipt](final-local-verification-2026-09-25.json)
reports its own `make test-all` function-length failure in two unaccepted PubMed
instrumentation functions. It does not establish a pass for that experimental
branch. No new model inference, public research goal, or production mutation
was performed for this closeout; the eight deferred follow-ups remain unfinished.

## 26 September M11 branch check

The [current branch receipt](m11-branch-verification-2026-09-26.json) covers source commit `7df7ef34` after the provisional Ling Sante route was removed: `make test-all`, lint, typecheck, build, offline evaluation smoke, 803 frontend tests and 18 isolated Chromium E2E tests passed. The 153 generic-key scanner matches were classified as generated public fixture IDs or SHA-256 integrity digests, not credentials. This is local/offline verification, not a current-model qualification, a deployed-commit readback, or a public-goal result. M12's combined-system acceptance item remains open.

## 27 September integrated-code offline verification

The [M12 offline receipt](m12-offline-verification-2026-09-27.json) pins integrated `main` `231f6540` after PR #57 and shows that app, engine, evaluations, E2E, vendor, build files, CI configuration and parity specification have identical Git objects to the last code-bearing release, PR #53. Fresh sequential `make test-all` passed 3,163 engine tests (2 skipped), 2,013 app tests, 312 MCP tests and parity. The exact default `(cd app/frontend && bun run test)` command passed 803/803 tests in 127 files. The [retained logs](m12-verification/) match the receipt's SHA-256 digests.

The unchanged-tree PR #53 receipt supplies the already successful lint, typecheck, build, offline evaluation smoke and clean 18/18 browser E2E rerun. Its earlier timeout/concurrency failures remain disclosed there; hosted CI was waived, not passed. This completes M12-02a's offline boundary only. A qualified zero-cost configuration, completed public research goal, novelty comparison and deployed Robin refinement remain unverified under M12-02b and other open gates.
