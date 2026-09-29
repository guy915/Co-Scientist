# Batch claim-schema correction release

[PR #73](https://github.com/guy915/Co-Scientist/pull/73) merged locally verified branch head `3caefecea1855f307e3593b416c867fe413bdc99` as `c8399332368d730ba367208db416f3e5797462cc` on 27 September 2026. The release adds the nonempty batch-verdict schema invariant and offline regression coverage; it changes no model default, provider configuration, database schema or user workflow. The earlier failed Space Bunny scientific trial remains unchanged and cannot qualify the route.

The exact tested head passed `make test-all` (3,169 engine tests with two existing skips, 2,032 app tests, 312 MCP tests, parity and evaluation checks), `make lint`, `make typecheck`, `make build`, `make eval-smoke`, the frontend `bun run test` (803/803), and `make e2e` (18/18). An initial full pass caught that new tests pushed one module beyond the 500-line gate; the tests were split into a 164-line focused module, the original returned to 492 lines, and the complete suite passed on the final head. The Codex Security diff scan `dea1fe08-9798-4712-8958-0d2de86ad1e8` covered the changed runtime source and reported zero findings. A separate Luna 6 read-only review found no actionable issue. Scoped cleanup found no scratch files, dead imports, duplicated production logic or UI changes.

GitHub's hosted **Affected targets** job failed before downstream jobs ran; they were skipped, not green. The owner's existing hosted-CI waiver was applied only after the final local checks and reviews passed.

| Existing production service | Deployment | Commit | Observed state |
| --- | --- | --- | --- |
| Railway API | `fec7467a-113a-4911-a261-7c59d0ff99d6` | `c8399332` | SUCCESS |
| Railway MCP | `91b745bb-fcc6-4e1f-a5d7-031e3f5513a2` | `c8399332` | SUCCESS |
| Vercel frontend | `dpl_3PfZvqR3csB8i8BtgCWdJJi8qwcE` | `c8399332` | READY, production |

The production frontend returned HTTP 200. The keyless `python -m evaluations.prod_smoke` passed health, MCP/status, ownership isolation, untrusted-origin CORS and sanitized-share checks (5/5), with no model call. This release did not mutate production configuration or data. The preceding `9185a618` release remains the Git rollback point; any rollback would still need a fresh check that the zero-cost campaign route remains intact. A new scientific comparison remains separately gated on a committed protocol and fresh free-price admission.
