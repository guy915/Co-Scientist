# Optimization and launch readiness

Co-Scientist was built by rapid prototyping. Performance, efficiency and polish
lagged behind features: in the engine, in the app, in how the models are called
and in how the repository is built, tested and shipped. Before going public,
make it a production-ready, professional-grade product.

This plan sets the goal, the guardrails and the starting evidence. It does not
list every task. The campaign finds them, ranks them and works through them.

**Status:** started 6 October 2026. CI and delivery work runs now; engine,
model and app work starts after the engine cuts merge (see Lanes).

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
- **Internal files stay:** `AGENTS.md` guides, `.remember/`, `PLAN.md`, the
  campaign plans and `docs/test-campaign/` remain in the public repository.
- **Priorities:** run speed, quality per token, app feel and development
  speed matter equally.
- **Models:** tune reasoning effort, token budgets, prompts, caching and
  retries per call type. Free routes stay the only defaults; do not switch to
  other models.
- **Run time:** no fixed target. A standard run takes over three hours; any
  improvement without quality loss is wanted, and a minimal quality loss is
  acceptable for a non-trivial speed gain, stated in the PR with the
  benchmark scores.
- **Monitoring:** add free-tier error tracking for the backend and frontend
  and an external uptime check for the site and API. New accounts, keys and
  env vars are set up by the owner.

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

- **Quality holds.** At the start, record a baseline with the quality
  benchmark: `evaluations/golden_run.py` on eight runs, two at each run size
  (Express, Standard, Extended, Ultra), scored with `claim_support_eval.py`
  and `citation_usefulness_eval.py`; the spread between paired runs is the
  noise floor. After that, check model-affecting changes with a lighter run
  (one Express run, or more when the change is risky) and re-run the full
  baseline at milestones. Revert a change whose scores fall beyond the noise
  floor unless it is a non-trivial speed gain with a minimal, stated loss.
  Record the scores in the PR.
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

Coordinates with `PLAN.md`, `docs/PROD-CUTS.md` and `docs/PROD-SHRINK.md`:

1. **Now:** CI and delivery (`.github/`, `Makefile`, Dockerfiles, Railway and
   Vercel settings with the owner's confirmation), and the audit itself,
   which is read-only.
2. **After the engine cuts merge:** model usage and engine run time. This runs
   before the shrink touches the LLM stack, so the shrink simplifies the
   optimized code.
3. **After each folder's cuts:** backend, frontend and infrastructure work in
   that folder.
4. **Launch readiness** throughout, in docs and repository files no other
   lane owns.
