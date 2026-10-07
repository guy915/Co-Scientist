All times are seconds. Job wall = completed − created; queue = started − created;
execution = completed − started. Workflow wall = updated − created (API terminal
timestamp). Initial dispatch = first job created − workflow created, separate
from runner queue. Job medians include success/failure; skipped/cancelled jobs
are counted separately and excluded from timing medians. Workflow medians
include every sampled terminal run, including cancelled runs. Matrices skipped
before expansion appear under their literal expression names. Samples are the
latest 20 completed CI main-push runs and latest 20 completed CI PR runs at
collection time; attempts use the latest available jobs. No success-only filter.

## main (20 runs)

Workflow wall median **168 s**; max **807 s**.
Initial dispatch median **1 s**; max **133 s**.

| Job | Timed n | Skipped | Cancelled | Wall median | Queue median | Queue max | Execution median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Affected targets | 20 | 0 | 0 | 6 | 2 | 4 | 4 |
| App tests | 6 | 0 | 0 | 6 | 2 | 3 | 3 |
| App tests (shard 0/3) | 20 | 0 | 0 | 88 | 2 | 38 | 84 |
| App tests (shard 1/3) | 20 | 0 | 0 | 68.5 | 3 | 3 | 65.5 |
| App tests (shard 2/3) | 20 | 0 | 0 | 79 | 2 | 4 | 76.5 |
| Browser e2e (Playwright) | 6 | 0 | 0 | 6 | 2 | 3 | 3.5 |
| Browser e2e (production) | 20 | 0 | 0 | 93.5 | 2 | 4 | 90.5 |
| Browser e2e (shard 1/2) | 20 | 0 | 0 | 145.5 | 2 | 3 | 143.5 |
| Browser e2e (shard 2/2) | 20 | 0 | 0 | 114 | 2 | 5 | 111 |
| Docker builds + Compose config smoke | 20 | 0 | 0 | 101 | 2 | 4 | 99 |
| Engine tests (py3.10) | 20 | 0 | 0 | 39 | 2 | 14 | 36.5 |
| Engine tests (py3.12) | 20 | 0 | 0 | 37 | 2 | 4 | 35 |
| Evaluations (parity + offline smoke) | 6 | 0 | 0 | 6 | 2 | 3 | 4 |
| Evaluations (tests + offline smoke) | 20 | 0 | 0 | 51 | 2 | 3 | 48 |
| Format and lint (ruff) | 20 | 0 | 0 | 13.5 | 2 | 3 | 11 |
| Frontend (lint + test + build) | 20 | 0 | 0 | 73.5 | 2 | 5 | 71 |
| MCP server tests | 20 | 0 | 0 | 31 | 2 | 39 | 28.5 |
| Required checks | 20 | 0 | 0 | 5 | 2 | 39 | 3 |
| Root config smoke (Makefile, vercel.json) | 20 | 0 | 0 | 38.5 | 2 | 4 | 35.5 |
| Typecheck (mypy, strict) | 20 | 0 | 0 | 119 | 2 | 4 | 117 |

### Sample provenance

- [Run 37635436858](https://github.com/guy915/Co-Scientist/actions/runs/37635436858): 2026-10-07T14:17:20Z, success, attempt 1, `09a405204ff5`
- [Run 37634742952](https://github.com/guy915/Co-Scientist/actions/runs/37634742952): 2026-10-07T14:12:18Z, failure, attempt 1, `c8129c223e06`
- [Run 37633576035](https://github.com/guy915/Co-Scientist/actions/runs/37633576035): 2026-10-07T14:03:51Z, success, attempt 1, `a90a5f348b1e`
- [Run 37632870192](https://github.com/guy915/Co-Scientist/actions/runs/37632870192): 2026-10-07T13:58:51Z, success, attempt 1, `b26806d456ec`
- [Run 37630156646](https://github.com/guy915/Co-Scientist/actions/runs/37630156646): 2026-10-07T13:38:49Z, success, attempt 1, `0f2236c32b65`
- [Run 37629908525](https://github.com/guy915/Co-Scientist/actions/runs/37629908525): 2026-10-07T13:36:59Z, success, attempt 1, `0478da30b75a`
- [Run 37628056794](https://github.com/guy915/Co-Scientist/actions/runs/37628056794): 2026-10-07T13:23:07Z, success, attempt 1, `739031c6245d`
- [Run 37627962323](https://github.com/guy915/Co-Scientist/actions/runs/37627962323): 2026-10-07T13:22:23Z, success, attempt 1, `b0a675144c41`
- [Run 37626664594](https://github.com/guy915/Co-Scientist/actions/runs/37626664594): 2026-10-07T13:12:17Z, success, attempt 1, `9bc3ffb57ff1`
- [Run 37626377943](https://github.com/guy915/Co-Scientist/actions/runs/37626377943): 2026-10-07T13:10:00Z, success, attempt 1, `66658076ac5f`
- [Run 37624355372](https://github.com/guy915/Co-Scientist/actions/runs/37624355372): 2026-10-07T12:53:58Z, success, attempt 1, `4c1b823e69b7`
- [Run 37623202182](https://github.com/guy915/Co-Scientist/actions/runs/37623202182): 2026-10-07T12:44:35Z, success, attempt 1, `db4be9cef6a2`
- [Run 37622695304](https://github.com/guy915/Co-Scientist/actions/runs/37622695304): 2026-10-07T12:40:25Z, success, attempt 1, `4ad544818736`
- [Run 37622482327](https://github.com/guy915/Co-Scientist/actions/runs/37622482327): 2026-10-07T12:38:42Z, failure, attempt 1, `423f5cf4a92f`
- [Run 37622052167](https://github.com/guy915/Co-Scientist/actions/runs/37622052167): 2026-10-07T12:35:08Z, success, attempt 1, `8b49c9870e81`
- [Run 37621540521](https://github.com/guy915/Co-Scientist/actions/runs/37621540521): 2026-10-07T12:30:56Z, success, attempt 1, `3c0a8891886b`
- [Run 37620552829](https://github.com/guy915/Co-Scientist/actions/runs/37620552829): 2026-10-07T12:22:42Z, success, attempt 1, `4fc3fd0a5edd`
- [Run 37619571485](https://github.com/guy915/Co-Scientist/actions/runs/37619571485): 2026-10-07T12:14:19Z, success, attempt 1, `8aeae7419554`
- [Run 37618894923](https://github.com/guy915/Co-Scientist/actions/runs/37618894923): 2026-10-07T12:08:26Z, success, attempt 1, `35d68bfc4812`
- [Run 37616977035](https://github.com/guy915/Co-Scientist/actions/runs/37616977035): 2026-10-07T11:51:52Z, success, attempt 1, `a5dfe068edda`

## PR (20 runs)

Workflow wall median **165.5 s**; max **255 s**.
Initial dispatch median **1 s**; max **75 s**.

| Job | Timed n | Skipped | Cancelled | Wall median | Queue median | Queue max | Execution median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Affected targets | 20 | 0 | 0 | 9 | 2 | 3 | 7 |
| App tests | 9 | 0 | 0 | 5 | 2 | 3 | 3 |
| App tests (shard ${{ matrix.shard }}/3) | 0 | 4 | 0 | — | — | — | — |
| App tests (shard 0/3) | 15 | 0 | 1 | 76 | 2 | 38 | 72 |
| App tests (shard 1/3) | 15 | 0 | 1 | 77 | 2 | 4 | 75 |
| App tests (shard 2/3) | 15 | 0 | 1 | 73 | 2 | 38 | 71 |
| Browser e2e (${{ matrix.name }}) | 0 | 4 | 0 | — | — | — | — |
| Browser e2e (Playwright) | 9 | 0 | 0 | 5 | 2 | 3 | 3 |
| Browser e2e (production) | 15 | 0 | 1 | 95 | 2 | 5 | 92 |
| Browser e2e (shard 1/2) | 15 | 0 | 1 | 158 | 2 | 3 | 155 |
| Browser e2e (shard 2/2) | 15 | 0 | 1 | 114 | 2 | 3 | 112 |
| Docker builds + Compose config smoke | 13 | 6 | 1 | 105 | 2 | 4 | 103 |
| Engine tests (py${{ matrix.python-version }}) | 0 | 6 | 0 | — | — | — | — |
| Engine tests (py3.10) | 13 | 0 | 1 | 39 | 2 | 3 | 37 |
| Engine tests (py3.12) | 13 | 0 | 1 | 37 | 2 | 3 | 34 |
| Evaluations (parity + offline smoke) | 9 | 0 | 0 | 6 | 2 | 3 | 4 |
| Evaluations (tests + offline smoke) | 18 | 1 | 1 | 51 | 2 | 3 | 49 |
| Format and lint (ruff) | 19 | 1 | 0 | 12 | 2 | 3 | 10 |
| Frontend (lint + test + build) | 5 | 15 | 0 | 78 | 2 | 2 | 76 |
| MCP server tests | 4 | 15 | 1 | 28 | 2 | 2 | 26 |
| Required checks | 20 | 0 | 0 | 5.5 | 2 | 4 | 3 |
| Root config smoke (Makefile, vercel.json) | 11 | 8 | 1 | 37 | 2 | 4 | 35 |
| Typecheck (mypy, strict) | 19 | 0 | 1 | 126 | 2 | 5 | 124 |

### Sample provenance

- [Run 37636038375](https://github.com/guy915/Co-Scientist/actions/runs/37636038375): 2026-10-07T14:21:41Z, success, attempt 1, `66921a4d2dcb`
- [Run 37635665463](https://github.com/guy915/Co-Scientist/actions/runs/37635665463): 2026-10-07T14:19:00Z, success, attempt 1, `6eba8663daf1`
- [Run 37633848329](https://github.com/guy915/Co-Scientist/actions/runs/37633848329): 2026-10-07T14:05:50Z, success, attempt 1, `158b09c1c151`
- [Run 37632996721](https://github.com/guy915/Co-Scientist/actions/runs/37632996721): 2026-10-07T13:59:46Z, success, attempt 1, `fa690f335b0f`
- [Run 37632557530](https://github.com/guy915/Co-Scientist/actions/runs/37632557530): 2026-10-07T13:56:32Z, success, attempt 1, `a23b02ec3d9e`
- [Run 37631463800](https://github.com/guy915/Co-Scientist/actions/runs/37631463800): 2026-10-07T13:48:32Z, success, attempt 1, `d19b0baa44b6`
- [Run 37631005152](https://github.com/guy915/Co-Scientist/actions/runs/37631005152): 2026-10-07T13:45:08Z, success, attempt 1, `6378fbcacb36`
- [Run 37629836921](https://github.com/guy915/Co-Scientist/actions/runs/37629836921): 2026-10-07T13:36:26Z, success, attempt 1, `23fbf360b061`
- [Run 37629273084](https://github.com/guy915/Co-Scientist/actions/runs/37629273084): 2026-10-07T13:32:15Z, success, attempt 1, `a29140cbbca0`
- [Run 37628700755](https://github.com/guy915/Co-Scientist/actions/runs/37628700755): 2026-10-07T13:28:01Z, success, attempt 1, `560434a80035`
- [Run 37628248070](https://github.com/guy915/Co-Scientist/actions/runs/37628248070): 2026-10-07T13:24:35Z, failure, attempt 1, `1fc05c58cbed`
- [Run 37627996532](https://github.com/guy915/Co-Scientist/actions/runs/37627996532): 2026-10-07T13:22:39Z, success, attempt 1, `2d1d23245c80`
- [Run 37627706449](https://github.com/guy915/Co-Scientist/actions/runs/37627706449): 2026-10-07T13:20:24Z, success, attempt 1, `3415ccbb3583`
- [Run 37626862058](https://github.com/guy915/Co-Scientist/actions/runs/37626862058): 2026-10-07T13:13:50Z, success, attempt 1, `a52bb7c5f783`
- [Run 37626728053](https://github.com/guy915/Co-Scientist/actions/runs/37626728053): 2026-10-07T13:12:46Z, success, attempt 1, `d3a15f475017`
- [Run 37626652718](https://github.com/guy915/Co-Scientist/actions/runs/37626652718): 2026-10-07T13:12:11Z, cancelled, attempt 1, `bd092f4e0afd`
- [Run 37625043992](https://github.com/guy915/Co-Scientist/actions/runs/37625043992): 2026-10-07T12:59:36Z, success, attempt 1, `ef3a1dcd1795`
- [Run 37623383739](https://github.com/guy915/Co-Scientist/actions/runs/37623383739): 2026-10-07T12:46:02Z, success, attempt 1, `180b48fdfb13`
- [Run 37623196768](https://github.com/guy915/Co-Scientist/actions/runs/37623196768): 2026-10-07T12:44:33Z, success, attempt 1, `96b31dffb96a`
- [Run 37622938387](https://github.com/guy915/Co-Scientist/actions/runs/37622938387): 2026-10-07T12:42:25Z, success, attempt 1, `8fbeae6809a3`
