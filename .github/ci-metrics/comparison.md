# CI timing comparison

Baseline: latest 20 completed main-push and 20 completed PR CI runs collected
before the changes. Follow-up: completed runs using the new selector/cache
workflow available by 7 October 2026, 15:39 UTC (4 main, 12 PR). Runs using an
older workflow are excluded by inspecting the affected-target job's steps.
The zero-job main cancellation is included because its commit follows the
merged speed-up. Raw observations and per-job tables are in
[before.json](before.json), [before.md](before.md), [after.json](after.json)
and [after.md](after.md). Failed/cancelled observations remain included;
this is a small follow-up cohort, not a matched benchmark.

| Median seconds | Before main | After main | Before PR | After PR |
|---|---:|---:|---:|---:|
| Workflow wall | 168 | 183 | 165.5 | 45 |
| Typecheck job wall | 119 | 55 | 126 | 61 |
| Typecheck job queue | 2 | 2 | 2 | 2.5 |
| Ruff job wall (now also MCP) | 13.5 | 37 | 12 | 14 |
| Ruff job queue | 2 | 3 | 2 | 2 |
| Browser production wall | 93.5 | 92 | 95 | 78 |
| Browser shard 1 wall | 145.5 | 153 | 158 | 332.5 |
| Browser shard 2 wall | 114 | 104 | 114 | 108.5 |

The PR wall decrease reflects documentation-only target exclusion as well as
caching; this cohort has many docs PRs. Mypy now shares a runner with root
config checks, and Ruff shares one with MCP. Their commands are unchanged.
Full CI needs **19 runner jobs instead of the immediately preceding 20**.
The older baseline contains both 17-job and 20-job configurations, so comparing
those counts without the intervening required-context change would mislead.
Excluded-engine contexts are reported separately from real interpreter tests.
CodeQL adds a separate analysis workflow; it is not part of these CI timings.

Median runner queue remains about 2–3 seconds. The baseline queue maximum of
143 seconds was a burst, not the median; fewer jobs reduce runner demand, but
this snapshot does not demonstrate a general main wall-time reduction.

The 538-second cold PR run includes a 385-second Chromium install step dominated
by Ubuntu apt mirror/font downloads. Cache restoration does not remove system
dependency installation. GitHub's 15:06–15:16 incident interrupted dependent-job
scheduling in two runs. A further main run was canceled with zero jobs when the
shared concurrency group replaced a pending run; the final PR corrects that
scheduling behavior. These observations explain the tails and remain in the data.

Warm-cache evidence from [main run 37644532845](https://github.com/guy915/Co-Scientist/actions/runs/37644532845):
logs show mypy restored a main cache and its typecheck step took **9 seconds**;
Chromium restored the exact OS/architecture/lock cache and two install steps
took **13 and 14 seconds**. The third browser worker remained blocked on apt
when this snapshot was collected. Those step observations verify cache use;
they do not replace the per-job or workflow measurements above.

Owner activation of the merge queue and removal of the strict up-to-date rule
is required to eliminate branch-update re-run chains. No settings were changed.
