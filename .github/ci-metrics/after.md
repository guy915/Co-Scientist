All times are seconds. Job wall = completed − created; queue = started − created;
execution = completed − started. Workflow wall = updated − created (API terminal
timestamp). Initial dispatch = first job created − workflow created, separate
from runner queue. Job medians include success/failure; skipped/cancelled jobs
are counted separately and excluded from timing medians. Workflow medians
include every sampled terminal run, including cancelled runs. Matrices skipped
before expansion appear under their literal expression names. Samples are the
latest completed CI main-push runs and CI PR runs in each snapshot at
collection time; attempts use the latest available jobs. No success-only filter.

## main (4 runs)

Workflow wall median **183 s**; max **416 s**.
Initial dispatch median **1 s**; max **1 s** (3 observed).

| Job | Timed n | Skipped | Cancelled | Wall median | Queue median | Queue max | Execution median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Affected targets | 3 | 0 | 0 | 5 | 2 | 3 | 3 |
| App tests | 2 | 0 | 0 | 7 | 2.5 | 3 | 4.5 |
| App tests (shard 0/3) | 3 | 0 | 0 | 74 | 3 | 3 | 72 |
| App tests (shard 1/3) | 3 | 0 | 0 | 88 | 3 | 4 | 84 |
| App tests (shard 2/3) | 3 | 0 | 0 | 77 | 3 | 3 | 74 |
| Browser e2e (Playwright) | 2 | 0 | 0 | 6 | 2.5 | 3 | 3.5 |
| Browser e2e (production) | 3 | 0 | 0 | 92 | 3 | 3 | 89 |
| Browser e2e (shard 1/2) | 3 | 0 | 0 | 153 | 3 | 3 | 150 |
| Browser e2e (shard 2/2) | 3 | 0 | 0 | 104 | 3 | 3 | 102 |
| Docker builds + Compose config smoke | 3 | 0 | 0 | 101 | 3 | 8 | 98 |
| Engine tests (py3.10) | 3 | 0 | 0 | 40 | 3 | 3 | 37 |
| Engine tests (py3.12) | 3 | 0 | 0 | 39 | 2 | 4 | 37 |
| Evaluations (parity + offline smoke) | 2 | 0 | 0 | 6.5 | 3 | 3 | 3.5 |
| Evaluations (tests + offline smoke) | 3 | 0 | 0 | 51 | 3 | 3 | 48 |
| Format and lint (ruff) | 3 | 0 | 0 | 37 | 3 | 3 | 34 |
| Frontend (lint + test + build) | 3 | 0 | 0 | 81 | 3 | 3 | 78 |
| MCP server tests | 2 | 0 | 0 | 6.5 | 2.5 | 3 | 4 |
| Required checks | 2 | 0 | 0 | 7 | 3 | 4 | 4 |
| Typecheck (mypy, strict) | 3 | 0 | 0 | 55 | 2 | 3 | 53 |

### Sample provenance

- [Run 37645023942](https://github.com/guy915/Co-Scientist/actions/runs/37645023942): 2026-10-07T15:34:40Z, cancelled, attempt 1, `5b2125cb2ac2`
- [Run 37642230853](https://github.com/guy915/Co-Scientist/actions/runs/37642230853): 2026-10-07T15:06:07Z, failure, attempt 1, `b6c244199599`
- [Run 37641170919](https://github.com/guy915/Co-Scientist/actions/runs/37641170919): 2026-10-07T14:58:29Z, success, attempt 1, `652abf5ff4ac`
- [Run 37640719544](https://github.com/guy915/Co-Scientist/actions/runs/37640719544): 2026-10-07T14:55:00Z, success, attempt 1, `81e9306dd57f`

### Incident notes

- Run 37645023942: Pending main run replaced by a newer run in the original shared concurrency group; no jobs created. Final handoff PR makes non-PR CI groups independent.
- Run 37642230853: GitHub incident djlmxz2zd0j7 interrupted dependent-job scheduling (https://stspg.io/96smrcth8bpg).

## PR (12 runs)

Workflow wall median **45 s**; max **661 s**.
Initial dispatch median **1 s**; max **62 s** (12 observed).

| Job | Timed n | Skipped | Cancelled | Wall median | Queue median | Queue max | Execution median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Affected targets | 12 | 0 | 0 | 9.5 | 2 | 4 | 7 |
| App tests | 11 | 0 | 0 | 5 | 2 | 4 | 3 |
| App tests (shard ${{ matrix.shard }}/3) | 0 | 8 | 0 | — | — | — | — |
| App tests (shard 0/3) | 3 | 0 | 0 | 85 | 2 | 3 | 83 |
| App tests (shard 1/3) | 3 | 0 | 0 | 77 | 2 | 2 | 75 |
| App tests (shard 2/3) | 3 | 0 | 0 | 61 | 2 | 2 | 59 |
| Browser e2e (${{ matrix.name }}) | 0 | 8 | 0 | — | — | — | — |
| Browser e2e (Playwright) | 11 | 0 | 0 | 6 | 2 | 4 | 3 |
| Browser e2e (production) | 3 | 0 | 0 | 78 | 2 | 2 | 76 |
| Browser e2e (shard 1/2) | 2 | 0 | 1 | 332.5 | 2 | 2 | 330.5 |
| Browser e2e (shard 2/2) | 2 | 0 | 1 | 108.5 | 2 | 2 | 106.5 |
| Docker builds + Compose config smoke | 3 | 8 | 0 | 99 | 2 | 2 | 97 |
| Engine tests (py${{ matrix.python-version }}) | 0 | 8 | 0 | — | — | — | — |
| Engine tests (py3.10) | 3 | 0 | 0 | 38 | 2 | 3 | 36 |
| Engine tests (py3.10) [excluded-target context] | 3 | 0 | 0 | 7 | 3 | 4 | 4 |
| Engine tests (py3.12) | 3 | 0 | 0 | 35 | 2 | 3 | 33 |
| Engine tests (py3.12) [excluded-target context] | 3 | 0 | 0 | 7 | 4 | 4 | 3 |
| Evaluations (parity + offline smoke) | 11 | 0 | 0 | 6 | 2 | 4 | 4 |
| Evaluations (tests + offline smoke) | 4 | 7 | 0 | 50 | 2.5 | 3 | 47.5 |
| Format and lint (ruff) | 11 | 0 | 0 | 14 | 2 | 3 | 12 |
| Frontend (lint + test + build) | 3 | 8 | 0 | 63 | 3 | 3 | 60 |
| MCP server tests | 11 | 0 | 0 | 6 | 2 | 4 | 4 |
| Required checks | 11 | 0 | 0 | 5 | 2 | 3 | 3 |
| Typecheck (mypy, strict) | 4 | 7 | 0 | 61 | 2.5 | 3 | 58.5 |

### Sample provenance

- [Run 37644812647](https://github.com/guy915/Co-Scientist/actions/runs/37644812647): 2026-10-07T15:33:06Z, success, attempt 1, `fa1b4b2f1b0e`
- [Run 37644787780](https://github.com/guy915/Co-Scientist/actions/runs/37644787780): 2026-10-07T15:32:56Z, success, attempt 1, `2e5370488689`
- [Run 37644051349](https://github.com/guy915/Co-Scientist/actions/runs/37644051349): 2026-10-07T15:27:22Z, success, attempt 1, `a95a71147c74`
- [Run 37642869022](https://github.com/guy915/Co-Scientist/actions/runs/37642869022): 2026-10-07T15:19:04Z, success, attempt 1, `af1a79133bd8`
- [Run 37642172651](https://github.com/guy915/Co-Scientist/actions/runs/37642172651): 2026-10-07T15:05:43Z, failure, attempt 1, `78954c342cdf`
- [Run 37641904026](https://github.com/guy915/Co-Scientist/actions/runs/37641904026): 2026-10-07T15:03:44Z, cancelled, attempt 1, `d6e52b9e3dee`
- [Run 37641895316](https://github.com/guy915/Co-Scientist/actions/runs/37641895316): 2026-10-07T15:03:40Z, success, attempt 1, `23546a930220`
- [Run 37641461026](https://github.com/guy915/Co-Scientist/actions/runs/37641461026): 2026-10-07T15:00:36Z, success, attempt 1, `a4add9c7df29`
- [Run 37641278986](https://github.com/guy915/Co-Scientist/actions/runs/37641278986): 2026-10-07T14:59:23Z, success, attempt 1, `82f58a91f156`
- [Run 37640904445](https://github.com/guy915/Co-Scientist/actions/runs/37640904445): 2026-10-07T14:56:29Z, success, attempt 1, `4133bc422e6c`
- [Run 37639924314](https://github.com/guy915/Co-Scientist/actions/runs/37639924314): 2026-10-07T14:49:17Z, success, attempt 1, `435808cc2d02`
- [Run 37639163100](https://github.com/guy915/Co-Scientist/actions/runs/37639163100): 2026-10-07T14:43:54Z, success, attempt 1, `7a91e485830c`

### Incident notes

- Run 37642172651: GitHub incident djlmxz2zd0j7 interrupted dependent-job scheduling (https://stspg.io/96smrcth8bpg).
- Run 37639163100: Cold browser shard-1 install took 385 s; logs identify Ubuntu apt mirror/font downloads as the delay.
