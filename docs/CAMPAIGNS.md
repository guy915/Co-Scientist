# Parallel campaigns

Three campaigns run at the same time, one per Claude account, so v0 finishes
in days rather than weeks: the production cuts (`docs/PROD-CUTS.md`), the
production shrink (`docs/PROD-SHRINK.md`) and the optimization campaign
(`docs/OPTIMIZATION.md`). Each plan keeps its own scope and rules. This file
sets the schedule, who edits what and when, and how the campaigns coordinate.

**Status:** planned 6 October 2026. The test campaign finished on 6 October
2026; day 1 is the night of 6 October.

## Accounts

| Account | Campaign | Sessions |
|---|---|---|
| Main | Production cuts | One lead |
| Second | Production shrink | One lead |
| Third | Optimization | Two leads: the model lane and the delivery lane |

Each lead plans, reviews and merges. Subagents implement, each on its own
branch (see Sessions and usage). To finish fast, keep three to five
subagents busy whenever independent work is ready, and keep working
around the clock. When an account reaches its usage limit, its campaign
pauses until the reset; its open PRs keep their claims.

## Schedule

| Day | Cuts | Shrink | Optimization |
|---|---|---|---|
| Before | No PRs | Read-only preparation: clone scan, typed-model design | Benchmark baseline; delivery lane: audit, CI, launch-readiness files |
| 1 | Starts after the format PR, in four streams, engine and MCP first | Format PR, alone. Engine and MCP levers once their cuts merge | Model lane starts once the engine cuts merge |
| 2 | Remaining cuts; legacy-migration PR, then the owner runs the migration | App and frontend levers as their cuts merge | Batches of model changes; backend and frontend fixes |
| 3 | Legacy deletion PR. Done | LLM retry merge (6), engine move (11), typed models (10) | Launch readiness; final check, which does not block |
| 4 | | Typed models finish; final line counts | Done |

If day 4 slips, typed models move to after v0 instead of delaying the launch.

### Early starts

- **Benchmark baseline:** as soon as the `Benchmark` workflow has its secret.
- **Optimization delivery lane:** as soon as its account is ready. The audit
  is read-only, and CI, the `Makefile`, Dockerfiles and new repository files
  do not touch tests.
- **Shrink:** read-only preparation only; no PR before day 1.

### Day 1 order

1. The shrink lead opens the format PR (shrink lever 1) as the only open PR
   that changes Python files, and merges it once CI is green. It holds the
   new ruff settings and the `ruff format` output, nothing else.
2. Then the cuts start, engine and MCP first, so the shrink and the model
   lane get the engine early.

## Who edits what

- **Cuts go first.** A folder belongs to the cuts until its rows in
  `docs/PROD-CUTS.md` are merged. The streams are listed there.
- **Shrink takes a folder once its cuts merge:** engine and MCP after stream
  1; the app backend after streams 2 and 3 and the demo snapshot; the frontend
  after the frontend parts of streams 2 to 4; evaluations after the
  evaluation cut. The legacy deletion PR merges `main` and resolves its
  conflicts with shrink work.
- **Optimization:**
  - Owns `.github/`, the `Makefile`, Dockerfiles, `requirements/` and new
    repository files throughout. Other campaigns edit them only to remove what
    a cut deletes.
  - The model lane owns `engine/src/co_scientist/llm/` and the prompt
    templates from the day the engine cuts merge until it finishes. Shrink
    lever 6 waits for it.
  - Backend and frontend fixes are targeted, start after that folder's cuts
    and claim their files through the open PR. Frontend fetching and polling
    belong to shrink lever 9; optimization measures them after it lands.
- **Shared files** (`AGENTS.md` files, `docs/*.md`, `.env.example` files,
  `README.md`, `app/app/config.py`, `app/app/main.py`): anyone may make small
  edits. Do not reorder or reformat them. On a conflict, merge `main` and keep
  both sides.

## Windows

Changes that touch nearly every file run in short windows. The shrink lead
announces each window on its board at least two hours ahead. During a window,
the other campaigns do not open or merge PRs in the named folders, and merge
or park the ones they have open.

- **Format change (lever 1):** day 1, first. Python files.
- **Engine move (lever 11):** two to three hours on day 3, between two model
  batches. `engine/` and `app/`.
- **Typed models (lever 10):** one PR per concept; concepts whose files do not
  overlap run at once. App-side concepts first; engine-side ones after the
  model lane releases its files.

## Coordination

- **Boards.** Each lead opens one GitHub issue, `Campaign board: <campaign>`,
  on its first day and keeps its body current: open PRs, claims outside the
  ownership above, next PRs, windows and blockers. The owner follows progress
  there.
- **Before each new PR,** read every board and the open PRs with their files
  (`gh pr list`, `gh pr diff --name-only`). Do not edit a file that another
  campaign's open PR changes.
- **Claims.** An open PR claims its files. Open the PR as soon as the branch
  has its first commit; a draft is fine.
- Never edit another campaign's PR, branch or board.

## Merging, CI and production

- **Merging.** The owner authorized bypassing `main`'s review requirement for
  these campaigns on 6 October 2026, which overrides the branch-protection
  rule in AGENTS.md: squash-merge with
  `gh pr merge --squash --delete-branch --admin` once CI is green on the
  latest commit.
- **Fresh base.** Before merging, if `main` changed files in the same folders
  since the PR's last CI run, merge `main` and wait for CI again.
- **Red `main`.** The campaign whose merge broke it fixes or reverts within
  30 minutes. Nobody merges into that folder until `main` is green again.
- **Deploys.** Every merge to `main` that touches deployed code deploys
  production. After it, confirm the GitHub deployment statuses for the merge
  commit (`gh api`), `https://api.ai-co-scientist.com/health` and
  `https://ai-co-scientist.com/`. If one is unhealthy, ship a revert PR first
  and resume once production is healthy.
- **Git.** Follow AGENTS.md. Keep every commit additive: make follow-up fixes
  in new commits. Run the app and engine pytest suites one after the other,
  and record each gate's exit status on its own line.
- **CI capacity.** All campaigns share the runners. Run local checks before
  pushing, push when a PR is ready rather than after every commit, and keep at
  most two benchmark runs going at once.
- **Local checks.** Subagents share the lead's container, its ports and its
  CPU, so only the lead runs `make e2e` and the full suites, one at a time.

## Sessions and usage

- Each lead runs at high effort; it plans, reviews and merges.
- Subagents implement, each on its own branch with disjoint files. Mechanical
  work runs on the faster, cheaper model; risky levers and model-usage changes
  run on the strongest model or in the lead itself. Each subagent gets these
  rules and confirms its files are on disk before it reports.
- Pick the number of subagents from the independent work ready and the
  account's remaining usage, so the campaign never stalls on the usage limit.
- Keep each PR body current with what changed, numbers before and after, and
  the checks run. After a context compaction, re-read this file, your plan
  and the merged PR history before resuming.

## Owner actions

- **Now:** add the `OPENROUTER_API_KEY` repository secret for the `Benchmark`
  workflow. While benchmark runs are queued, avoid large runs in the app: they
  share the free daily allowance.
- **Before day 1:** set up the two new accounts with the same cloud
  environment: internet access to GitHub, the production domains and the
  package registries; Python 3.12, Node.js 22.13+ and Bun 1.3.14 with
  `make setup`; and a GitHub token with admin rights on the repository and the
  `repo` and `workflow` scopes, so `gh` can push, open PRs and merge with
  `--admin`.
- **During the campaigns:** run the legacy-data migration on production when
  the cuts ask for it. Confirm Railway watch-path changes for the engine move,
  and delete retired variables. Create the monitoring accounts the
  optimization campaign asks for.
