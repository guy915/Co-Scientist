# Codebase Reduction Design

**Date:** 2026-07-03
**Goal:** Reduce code complexity in `engine/` (~35.5k lines) and `app/` (~21.5k lines) by deleting dead code, removing peripheral features, and consolidating duplicated patterns — with zero production behavior change. `references/`, `docs/`, and repo footprint are out of scope.

**Expected net effect:** roughly 4,700–5,000 lines removed (~9% of source), one low-risk internal refactor guarded by existing tests.

## Scope decisions (from brainstorming)

- Pain point: code complexity, not repo/clone footprint.
- Peripheral features may be trimmed; core hypothesis-generation functionality must not regress.
- Chosen approach: "Delete + consolidate" — pure deletions plus the `prompts.py` getter consolidation; the riskier `schemas.py` rewrite and `dev/` script deletion were explicitly rejected.

## Evidence base

All deletions below were verified by direct reference checks (grep across `engine/`, `app/`, Dockerfiles, compose files, Makefiles), not just audit-agent claims. Two audit claims were **rejected** after verification and are recorded here so they are not re-attempted:

- `app/frontend/src/styles/home_surface.css` + `shell_surface.css` (1,434 lines) are **live**, imported via `src/styles/surfaces.css` (from `main.tsx`) with class names consumed through `chat_home_classes.ts` in four page components. Do not delete.
- `save_prompt_to_disk` in `engine/src/co_scientist/prompts.py` is **live**, called by six node modules as a debug-logging feature. Do not delete.

Also verified as keep-as-is: `mock_workflow.py` (tests + demo seeding), `run_modes.py` (active config normalization), `seed.py`, `engine_adapter.py`, frontend `src/public/` pages, all graph nodes (all wired in `generator.py`), `mcp_server/` (production Railway service), `dev/` scripts, `examples/run.py` (simplified, not deleted).

## Section 1 — App: remove the legacy generation API (~620 lines)

Delete from `app/app/main.py` (904 lines → ~280):

- Endpoints: `POST /generate`, `POST /generate/start`, `GET /generate/stream/{task_id}`, `POST /cancel_hypothesis_generation`.
- Private machinery used only by them: `_active_tasks` registry + lock + `_generator` global, `stream_generator()`, `parse_research_goal_input()`, `_get_cached_parse()` / `_cache_parse()` and the parse cache dir helper.
- Pydantic models used only by them: `GenerateRequest`, `GenerateResponse`, `ParsedResearchGoal`, `CancelRequest`.
- Now-unused imports (`hashlib`, `pathlib.Path`, `litellm.acompletion`, etc. — verify each after deletion).

Keep: `GET /health`, `/config`, `/status`, lifespan setup, the `/api/runs` router mount.

Evidence: the frontend (`app/frontend/src/api/runs.ts`, `use_run_stream.ts`) calls only `/api/runs/*`; no app test references any legacy endpoint.

## Section 2 — Engine: delete 11 unused tool configs (~3,000 lines YAML + ~130 test lines)

In `engine/src/co_scientist/config/examples/`, keep **`indra_cancer.yaml`** (referenced by `app/docker-compose.yml`; production `TOOLS_CONFIG`). Delete the other 11: `arxiv_and_google_scholar.yaml`, `arxiv_only.yaml`, `arxiv_research_focused.yaml`, `cybersecurity_hydra.yaml`, `google_scholar.yaml`, `indra_alzheimers.yaml`, `indra_hfpef.yaml`, `indra_ibd.yaml`, `multiple_sources.yaml`, `openalex_grounding.yaml`, `pubmed_arxiv_same_server.yaml`.

- Trim the portions of `engine/tests/test_config_registry.py` that merely load the deleted files; keep registry-logic tests (they may load `indra_cancer.yaml` or inline fixtures instead).
- Update `engine/docs/LITERATURE_REVIEW_TOOLS_CONFIGURATION.md`, `engine/docs/DOMAIN_CUSTOMIZATION.md`, and README pointers to reference only the surviving config.

Evidence: no Python, Dockerfile, compose, or Makefile references any of the 11 (grep hits for "openalex"/"google_scholar"/"arxiv" are MCP-server tool implementations, unrelated to these config files).

## Section 3 — Engine: evict the Rich console from the library (~670 lines)

- Delete `engine/src/co_scientist/console.py` (672 lines) and its export in `src/co_scientist/__init__.py`.
- Rewrite `engine/examples/run.py` as a minimal plain-print interactive demo (~40 lines): read a research goal, run `HypothesisGenerator`, print hypotheses/summary with plain `print()`.
- Remove `rich` from the engine's core dependencies if nothing else in the library uses it (verify; keep as a dev/examples extra only if still needed).

Rationale: `console.py` is imported only by `examples/run.py`, and CLAUDE.md's own rule is "Rich only in examples/ and dev/, never in core library code". User approved dropping the fancy CLI rendering.

Risk note: anyone importing `co_scientist.ConsoleReporter` externally would break; accepted (package is not published to PyPI).

## Section 4 — Engine: consolidate `prompts.py` getters (~250–350 lines saved)

`prompts.py` (1,588 lines) has 20+ `get_*_prompt()` functions sharing one skeleton: assemble base variables → optionally apply guidance formatters (`_format_supervisor_guidance_for_*`, `_format_meta_review_context`, `_format_run_guidance`) → merge `_get_domain_variables(tool_registry)` → `load_prompt_with_schema(name, variables)`.

Design:

- Add one internal builder, e.g.
  `_build_prompt(name, base_vars, *, supervisor_formatter=None, supervisor_guidance=None, meta_review=None, run_setup_guidance=None, run_focus_guidance=None, tool_registry=None) -> tuple[str, dict | None]`
  which applies exactly the shared steps (each context key only added when the corresponding kwarg is provided, preserving current template-variable sets per prompt).
- Collapse each simple getter (`get_review_prompt`, `get_review_batch_prompt`, `get_deep_verification_prompt`, `get_meta_review_prompt`, `get_research_overview_prompt`, `get_proximity_prompt`, `get_reflection_prompt`, lit-review getters, etc.) into a thin 3–8 line wrapper around `_build_prompt`.
- Bespoke getters (`get_ranking_prompt`, debate/tools prompts, validation-synthesis prompts) keep their extra assembly but call `_build_prompt` for the shared portion where it fits naturally; do not force-fit.
- **Public getter signatures and return values stay byte-identical** — no node file changes; existing `test_prompts.py` (490 lines) validates the refactor. Formatter helpers (`_format_*`) are unchanged.
- `save_prompt_to_disk` / `get_prompt_save_path` stay untouched.

Risk: low — pure internal refactor with unchanged API, covered by existing tests. If a getter's variable set is subtly order- or presence-sensitive, tests comparing rendered prompts will catch it; add a characterization test first if coverage is missing for a given getter.

## Section 5 — Docs & handoff

- `CLAUDE.md` / `AGENTS.md`: remove the legacy `/generate*` endpoint documentation; remove `console.py` references; update the config-examples mention.
- `engine/README.md`, `engine/docs/*`: remove `run_console` / `ConsoleReporter` references; update tool-config docs per Section 2.
- `app/.env.example` and `README.md`: no changes expected, verify no legacy-endpoint mentions.

## Verification plan

After each section (each lands as its own commit on a `refactor/trim-codebase` branch):

- Engine: `pytest`, `mypy .`, `pylint --rcfile=../pylintrc src/co_scientist`, `yapf` check.
- App backend: `make test`, `mypy`, `pylint`.
- Frontend: `bun run build`, `bun run test`, `bun run lint` (Sections 1/5 only; no frontend source changes expected).
- Final: start the app with the mock provider, create and stream a run end-to-end, confirm `/status` and `/api/runs` behave; run `engine/examples/run.py` once to confirm the simplified demo works.

## Out of scope (explicitly rejected)

- `schemas.py` Pydantic-generation rewrite (medium risk to LLM output parsing).
- Deleting `engine/dev/` standalone scripts (endorsed development workflow).
- Any change to `references/`, mock workflow, run modes, seeding, public pages, MCP server, or graph topology.
