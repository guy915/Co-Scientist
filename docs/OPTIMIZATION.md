# Optimization and launch readiness

Co-Scientist was built by rapid prototyping. Performance, efficiency and polish
lagged behind features: in the engine, in the app, in how the models are called
and in how the repository is built, tested and shipped. Before going public,
make it a production-ready, professional-grade product.

This plan sets the goal, the guardrails and the starting evidence. It does not
list every task. The campaign finds them, ranks them and works through them.

**Status:** in progress since 6 October 2026. The audit is recorded in
`docs/optimization/findings.md`; CI speed and launch-readiness PRs are open.
The first baselines ran without retrieval and are being re-run; model changes
start after the engine cuts merge. Live progress is on the
`Campaign board: optimization` issue.

## Scope

Everything that affects speed, cost, reliability or quality of experience:

- **Model usage:** tokens, reasoning budgets, retries, prompt size and
  structure, caching, tool-loop transcripts, model and route choice per call.
- **Engine and runs:** end-to-end run time, parallelism, wasted or repeated
  work, failure and retry paths.
- **Backend:** endpoint latency, database queries and indexes, startup time,
  memory, background work, payload sizes.
- **Frontend:** bundle size, load time, rendering, network requests, polling,
  accessibility and mobile behavior.
- **Infrastructure:** image size, build and deploy time, cold starts, resource
  limits, logs and monitoring.
- **Development:** CI time and cost, caching, flaky tests, local setup and
  test speed, release flow, dependency hygiene.
- **Launch readiness:** README and docs a newcomer can follow, security
  posture, error messages, observability, licensing and anything else a
  public, professional repository is expected to have.

## Owner decisions (6 October 2026)

- **Public scope:** the GitHub repository and the product both go public.
  Prepare the repository for open source: license and notice check,
  `SECURITY.md`, a contributing guide, issue and PR templates, a README a
  newcomer can follow, and a secret scan of the current tree. Git history
  will be reset before publication, so do not scan or rewrite it.
- **Internal files stay:** `AGENTS.md` guides, `.remember/` and the campaign
  plans remain in the public repository.
- **Priorities:** run speed, quality per token, app feel and development
  speed matter equally.
- **Models:** tune reasoning effort, token budgets, prompts, caching and
  retries per call type. Free routes stay the only defaults. On 6 October 2026
  the owner chose Ling 3.1 Flash (`openrouter/inclusionai/ling-3.1-flash`) as
  the default, with the Nemotron free routes as fallbacks; do not switch to
  other models. Its zero price is a trial: if it ends, report it to the owner
  rather than picking a replacement.
- **Run time:** no fixed target. A standard run takes over three hours; any
  improvement without quality loss is wanted, and a minimal quality loss is
  acceptable for a non-trivial speed gain, stated in the PR with the
  benchmark scores.
- **Monitoring:** add free-tier error tracking for the backend and frontend
  and an external uptime check for the site and API. New accounts, keys and
  env vars are set up by the owner.
- **Benchmark:** no paid routes and no multi-week waits. The small benchmark
  under Guardrails replaces the eight-run baseline.

## Starting evidence (6 October 2026)

Measured in production and CI. Each number is a starting point to confirm and
measure again, not a finished diagnosis.

| Area | Finding |
|---|---|
| Tool loops | The draft agent re-sent about 383k tokens before its 360k budget stopped it; review loops hit their 45k budget repeatedly. The whole transcript is re-sent on every iteration. |
| Caching | `cached_prompt_tokens` is 0 on every logged call. |
| Reasoning waste | Many calls spend their full 18k-token budget reasoning without answering, then retry with the same 14–39k-token prompt, up to four times in a row. |
| Prompt size | One interview turn sends about 55k prompt tokens. |
| Run time | A standard run took over three hours. |
| Free route | OpenRouter allows 20 requests a minute and 1,000 a day on free models, for the whole account, so the owner's own use shares the benchmark's allowance. A daily cap parks durable work until the UTC reset. |
| API | p50 8 ms, but p90 about 500 ms and p99 about 1.1 s on successful requests. Memory averages 0.28 GB and peaks at 1 GB. |
| CI | About 7 minutes per run. App tests are one 6.3-minute job on the critical path; each job spends about 30 s setting up; the root-config job repeats lint and typecheck. |

## Method

1. **Audit** each area above. Measure before changing anything, and record
   findings with their evidence in `docs/optimization/findings.md`.
2. **Rank** findings by impact for the effort and risk.
3. **Fix** in small PRs, one theme each, measuring before and after.
4. **Repeat** until the remaining findings are not worth their risk, then
   record what was left and why.

## Guardrails

- **Quality holds, within the free allowance.** The quality benchmark is one
  run driven by `evaluations/claim_support_eval.py --live` on its fixed goal,
  on the free default route. It reports the unsupported-claim rate, requests
  and wall time. The manual `Benchmark` workflow runs it with the
  `OPENROUTER_API_KEY` repository secret. `citation_usefulness_eval.py` checks
  the citation judge. Live runs are rationed to the free allowance:
  - **Baseline,** now: two Express runs, whose spread is the noise floor, and
    one Standard run.
  - **No live run** for changes that cannot change model output: caching,
    removing duplicate or wasted calls, backend, frontend, CI and
    infrastructure. Measure them offline.
  - **Batches** for changes that can: prompts, reasoning and token budgets,
    retry policy, context and tool-loop limits. Check each batch with one
    Express run, as many a day as the allowance holds, and bisect only a batch
    whose scores fall beyond the noise floor.
  - **Final check:** one Express and one Standard run on the final code. It
    does not block other work.
  - Extended and Ultra get no live runs; check their call envelopes offline.

  Revert a change whose scores fall beyond the noise floor unless it is a
  non-trivial speed gain with a minimal, stated loss. Record the scores in the
  PR.
- **Behavior stays identical** unless a change is the point of the PR and says
  so. Every invariant in `docs/OPERATIONS.md` holds: durable task idempotency,
  leases, retry budgets, bounded calls, spend caps, evidence gates,
  append-only lineage, trust boundaries.
- **Measure, don't guess.** Every performance PR shows numbers before and
  after. No change ships on intuition alone.
- **Free routes stay free.** Never add paid fallbacks under free routes.
- **Production.** Never change Railway variables or run anything against the
  production database without the owner's confirmation. Read-only logs and
  metrics are fine. Check production health after each merge.
- **One theme per PR;** run `make lint`, `make typecheck`, `make test-all` and
  `make e2e` before each.

## Lanes

One lead session runs both lanes as parallel subagent streams;
`docs/CAMPAIGNS.md` sets the schedule, who edits what and the merge rules:

1. **Delivery lane,** as soon as its account is ready: the audit, which is
   read-only; CI and delivery (`.github/`, `Makefile`, Dockerfiles, Railway and
   Vercel settings with the owner's confirmation); launch readiness in files no
   other campaign owns; then backend, frontend and infrastructure fixes in each
   folder after its cuts.
2. **Model lane:** the benchmark baseline now; model usage and engine run time
   after the engine cuts merge. This runs before the shrink touches the LLM
   stack, so the shrink simplifies the optimized code.
