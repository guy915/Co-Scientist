# Codebase Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut ~4,700 lines of dead/peripheral/duplicated code from `engine/` and `app/` with zero production behavior change.

**Architecture:** Six independent tasks, each its own commit on branch `refactor/trim-codebase`: (1) delete the app's dead legacy `/generate` API; (2) delete 11 unused engine tool-config YAMLs; (3) delete the engine's Rich `console.py` and simplify the CLI demo; (4) add characterization tests for untested prompt getters; (5) consolidate `prompts.py` getters behind one internal builder (guarded by task 4's tests); (6) sweep docs. Tasks 1–3 are pure deletion. Task 5 is a behavior-preserving internal refactor gated by a byte-identical diff harness. Task 4 must land before task 5.

**Tech Stack:** Python 3.10+ (engine, FastAPI app), pytest, mypy, pylint (repo-root `pylintrc`), yapf (Google style, 80 cols). The engine package is `co_scientist` under `engine/src/`; the app package is `app` under `app/app/`.

## Global Constraints

- **No production behavior change.** Deletions target code with zero live callers (verified); the prompts refactor must keep every public getter's signature and rendered output byte-identical.
- **Branch:** all work lands on `refactor/trim-codebase` (already checked out; the design spec is already committed there).
- **Style:** yapf `based_on_style = google`, 80 columns. `logger.debug()` lowercase; `info`/`warning`/`error` capitalized. No emojis or unicode decoration in code or logs. Rich library only in `dev/` (after this work; `examples/` no longer uses it).
- **Git hygiene (repo rule):** commit messages read as if written by the human developer. Format `<type>(<scope>): <subject>`. NO `Co-Authored-By` trailers, NO "Generated with" lines, NO mention of any AI tool anywhere in commits or PRs.
- **Engine gate (run from `engine/`):** `pytest`, `mypy .`, `pylint --rcfile=../pylintrc src/co_scientist`, `yapf -ir <changed files>`.
- **App gate (run from `app/`):** `make test`, `make typecheck`, `make lint`, `make format`.
- **`CLAUDE.md` is a symlink to `AGENTS.md`** — edit `AGENTS.md` only.
- Never hand-edit generated artifacts under `engine/src/co_scientist_engine.egg-info/` — they regenerate on `pip install -e`.

---

## Task 1: Delete the app's legacy generation API

Removes the four dead `/generate*` endpoints and everything used only by them from `app/app/main.py` (904 lines → ~285). The frontend and all tests use only `/api/runs/*`; nothing imports these symbols. Verified: no cross-module importer, no test reference, no frontend `fetch`/`EventSource` call.

**Files:**
- Modify: `app/app/main.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a `main.py` exposing only `GET /`, `/health`, `/config`, `/status`, the `lifespan` hook, the `/api/runs` router mount, and the `__main__` uvicorn block. No new public symbols.

**Deletion approach:** delete from the **bottom of the file upward** so earlier line numbers stay valid as you go. Identify each block by its quoted anchor line, not by trusting a stale line number. After deleting, the pylint gate flags any import that became unused — use it as the checklist for the import trim.

- [ ] **Step 1: Read the file and confirm anchors**

Run: `grep -n '@app.post("/generate"\|@app.post("/generate/start"\|@app.get("/generate/stream\|@app.post("/cancel_hypothesis_generation"\|^async def stream_generator\|^async def parse_research_goal_input\|^def _get_parse_cache_dir\|^def _get_cached_parse\|^def _cache_parse\|^class GenerateRequest\|^class GenerateResponse\|^class ParsedResearchGoal\|^class CancelRequest\|^_generator = None\|^_active_tasks\|^console = Console()' app/app/main.py`

Expected: one line number per anchor. These locate every block to delete.

- [ ] **Step 2: Delete the endpoint block (bottom-most first)**

Delete the single contiguous block that runs from the `@app.post("/generate", ...)` decorator (anchor `async def generate_hypotheses`) through the end of `cancel_generation` — i.e. from the `/generate` decorator line down to the blank line just before `if __name__ == "__main__":`. This one block contains: POST `/generate`, `stream_generator()`, POST `/generate/start`, GET `/generate/stream/{task_id}`, `class CancelRequest`, and POST `/cancel_hypothesis_generation`. (In the current file this is lines 494–895; verify the top boundary is the `@app.post("/generate",` decorator and the bottom boundary is immediately before `if __name__`.)

- [ ] **Step 3: Delete the parse helpers and models block**

Delete the contiguous block from `def _get_parse_cache_dir()` through the end of `async def parse_research_goal_input(...)` (current lines 259–429: `_get_parse_cache_dir`, `_get_cached_parse`, `_cache_parse`, `parse_research_goal_input`).

Then delete the two Pydantic models `class GenerateRequest(BaseModel):` and `class GenerateResponse(BaseModel):` (current 168–198) and `class ParsedResearchGoal(BaseModel):` (current 239–256). Keep `HealthResponse`, `ConfigResponse`, `SystemStatusResponse` and the `# Request/Response models` comment.

- [ ] **Step 4: Delete the module globals**

Delete `console = Console()` (anchor `^console = Console()`), the `_generator = None` global with its `# Global generator instance ...` comment, and the `_active_tasks: dict[...] = {}` + `_active_tasks_lock = asyncio.Lock()` pair with their comment lines.

- [ ] **Step 5: Trim the lifespan hook**

In `async def lifespan(app: FastAPI)`: delete the `global _generator` line, and delete the whole `if HypothesisGenerator is not None and provider == "engine": _generator = HypothesisGenerator(...) else: ... _generator = None` block (current 107–122). **Keep** the `provider = engine_adapter.select_provider()` line and its log line immediately above the deleted block — `provider` is still used. The rest of `lifespan` (env setup, `seed_demo_runs`, `yield`) is unchanged.

- [ ] **Step 6: Trim now-unused imports**

Remove these imports (each is used only by deleted code — confirm by grepping the remaining file):
- `import asyncio`, `import hashlib`, `import json`
- `from pathlib import Path`
- `from fastapi.responses import StreamingResponse`
- `from rich.console import Console`
- change `from fastapi import FastAPI, HTTPException` → `from fastapi import FastAPI`
- the `try: from litellm import acompletion / except ...: acompletion = None` block
- the `try: from co_scientist import HypothesisGenerator / except ...: HypothesisGenerator = None` block

Keep: `logging`, `os`, `AsyncGenerator`, `asynccontextmanager`, `Any`, `uvicorn`, `load_dotenv`, `FastAPI`, `CORSMiddleware`, `BaseModel`, `Field`, `engine_adapter`, `store`, `settings`, `runs_router`, `seed_demo_runs`.

Verify no dangling use: `grep -nE '\b(asyncio|hashlib|json|Path|StreamingResponse|Console|HTTPException|acompletion|HypothesisGenerator)\b' app/app/main.py` should return nothing (or only inside comments you also removed).

- [ ] **Step 7: Confirm routes and imports via smoke check**

Run: `cd app && python -c "from app.main import app; print(sorted(r.path for r in app.routes))"`
Expected: a list containing `/`, `/health`, `/config`, `/status`, and the `/api/runs...` paths, and **no** `/generate*` or `/cancel_hypothesis_generation`.

- [ ] **Step 8: Run the app gate**

Run: `cd app && make format && make lint && make typecheck && make test`
Expected: format clean, pylint clean (this is what catches a missed unused import), mypy clean, all tests pass. `test_health.py` still asserts `/health` + `/status`; the `/api/runs` suites still pass.

- [ ] **Step 9: Commit**

```bash
git add app/app/main.py
git commit -m "refactor(app): remove dead legacy /generate API"
```

---

## Task 2: Delete 11 unused engine tool-config YAMLs

Removes every `config/examples/*.yaml` except `indra_cancer.yaml` (the only one referenced anywhere — `app/docker-compose.yml` sets it as production `TOOLS_CONFIG`). No Python, test, packaging glob, Dockerfile, or Makefile references any of the 11. **`engine/tests/test_config_registry.py` needs NO edits** — it is self-contained (inline YAML fixtures + the surviving `config/tools.yaml`); the spec's "~130 test lines" estimate was inaccurate and is superseded by this plan.

**Files:**
- Delete: `engine/src/co_scientist/config/examples/{arxiv_and_google_scholar,arxiv_only,arxiv_research_focused,cybersecurity_hydra,google_scholar,indra_alzheimers,indra_hfpef,indra_ibd,multiple_sources,openalex_grounding,pubmed_arxiv_same_server}.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces: `config/examples/` containing only `indra_cancer.yaml` + `README.md` (README rewrite is in Task 6).

- [ ] **Step 1: Delete the 11 files**

```bash
cd engine/src/co_scientist/config/examples
git rm arxiv_and_google_scholar.yaml arxiv_only.yaml arxiv_research_focused.yaml \
       cybersecurity_hydra.yaml google_scholar.yaml indra_alzheimers.yaml \
       indra_hfpef.yaml indra_ibd.yaml multiple_sources.yaml \
       openalex_grounding.yaml pubmed_arxiv_same_server.yaml
```

- [ ] **Step 2: Confirm survivors and no code references**

Run: `cd /Users/guy/Code/Co-Scientist/engine && ls src/co_scientist/config/examples/`
Expected: `README.md  indra_cancer.yaml`

Run: `grep -rnE "arxiv_and_google_scholar|arxiv_only|arxiv_research_focused|cybersecurity_hydra|google_scholar\.yaml|indra_alzheimers|indra_hfpef|indra_ibd|multiple_sources|openalex_grounding|pubmed_arxiv_same_server" src tests pyproject.toml`
Expected: no matches (exit 1). (Doc references are handled in Task 6; `google_scholar_search` tool-name hits in `docs/` are a different string and out of scope here.)

- [ ] **Step 3: Confirm survivor still parses and config tests pass**

Run: `cd engine && python -c "import yaml; yaml.safe_load(open('src/co_scientist/config/examples/indra_cancer.yaml')); yaml.safe_load(open('src/co_scientist/config/tools.yaml')); print('ok')"`
Expected: `ok`

Run: `pytest tests/test_config_registry.py -q`
Expected: all pass (the file never referenced the deleted configs).

- [ ] **Step 4: Full engine suite (confirms nothing silently loaded an example)**

Run: `cd engine && pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(engine): drop unused example tool configs"
```

---

## Task 3: Delete `console.py` and simplify the CLI demo

Removes the 672-line Rich `ConsoleReporter` (imported only by `examples/run.py`, and forbidden in library code by the repo's own style rule), rewrites `examples/run.py` as a plain-`print` demo, and moves `rich` from core dependencies to the `dev` extra (the `dev/` standalone scripts still use it). No engine test imports `console.py`.

**Files:**
- Delete: `engine/src/co_scientist/console.py`
- Modify: `engine/src/co_scientist/__init__.py`
- Rewrite: `engine/examples/run.py`
- Modify: `engine/pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: `co_scientist.__all__` without `"ConsoleReporter"`; a dependency-light `examples/run.py` using only `co_scientist.HypothesisGenerator` + stdlib.

- [ ] **Step 1: Delete the module**

```bash
cd engine && git rm src/co_scientist/console.py
```

- [ ] **Step 2: Remove the export from `__init__.py`**

In `engine/src/co_scientist/__init__.py`, delete the line `from co_scientist.console import ConsoleReporter` and the `"ConsoleReporter",` entry inside `__all__`. Leave every other import and `__all__` entry byte-identical. The resulting `__all__` is:

```python
__all__ = [
    "HypothesisGenerator",
    "Hypothesis",
    "HypothesisReview",
    "ExecutionMetrics",
    "WorkflowState",
    "WorkflowConfig",
    "clear_cache",
    "get_cache_stats",
    "clear_node_cache",
    "get_node_cache_stats",
    "ToolRegistry",
    "get_tool_registry",
]
```

- [ ] **Step 3: Rewrite `examples/run.py`**

Replace the entire file with this (plain `print`, no Rich, no absl; preserves the current demo's model, config, and `opts`; hypotheses expose `text`/`explanation`, not `title`):

```python
"""Minimal interactive demo for the Co-Scientist hypothesis generator.

Prompts for a research goal, runs ``HypothesisGenerator`` with literature
review and tool-calling generation enabled, then prints the ranked
hypotheses and the synthesized research overview using plain ``print``.

Prerequisites:
    - An MCP server running (default http://localhost:8888/mcp) for the
      literature review and tool-calling generation steps. Without one
      the engine falls back to LLM-only mode.
    - The provider API key for ``MODEL_NAME`` set in the environment (for
      example GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY).
"""
import asyncio
from typing import Any

from co_scientist import HypothesisGenerator

MODEL_NAME = "gemini/gemini-2.5-flash"


async def _report_progress(phase: str, data: dict[str, Any]) -> None:
    """Print a one-line progress update for a workflow phase.

    Args:
        phase: Name of the workflow phase emitting the update.
        data: Payload dict; a human-readable string is read from
            ``data['message']`` when present.
    """
    message = data.get("message", "")
    if message:
        print(f"  [{phase}] {message}")


async def _run() -> None:
    """Prompt for a research goal, run the workflow, and print results."""
    research_goal = input("Enter a research goal: ").strip()
    if not research_goal:
        print("Error: research goal cannot be empty.")
        return

    generator = HypothesisGenerator(
        model_name=MODEL_NAME,
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
    )

    result = await generator.generate_hypotheses(
        research_goal=research_goal,
        progress_callback=_report_progress,
        opts={
            "enable_literature_review_node": True,
            "enable_tool_calling_generation": True,
        },
    )

    hypotheses = sorted(
        result.get("hypotheses", []),
        key=lambda h: h.get("elo_rating", 1200),
        reverse=True,
    )

    print()
    print("Ranked hypotheses")
    print("=================")
    for rank, hyp in enumerate(hypotheses, start=1):
        elo = hyp.get("elo_rating", 1200)
        print(f"\n{rank}. [Elo {elo}] {hyp.get('text', '')}")
        explanation = hyp.get("explanation")
        if explanation:
            print(f"   Summary: {explanation}")

    overview = result.get("research_overview", {}).get("overview", {})
    summary = overview.get("summary")
    if summary:
        print()
        print("Research overview")
        print("=================")
        print(summary)
        for direction in overview.get("research_directions", []):
            print(f"- {direction.get('title', '')}")


if __name__ == "__main__":
    asyncio.run(_run())
```

- [ ] **Step 4: Move `rich` to the `dev` extra in `pyproject.toml`**

In `engine/pyproject.toml`, remove `"rich~=14.2.0",` from `[project].dependencies`, and add `"rich~=14.2.0",` to the `dev` list under `[project.optional-dependencies]`. (The `dev/` standalone scripts import `rich`, so it must stay available under `.[dev]`.)

- [ ] **Step 5: Confirm nothing else references the deleted symbols**

Run: `cd engine && grep -rn "co_scientist.console\|ConsoleReporter\|run_console\|default_progress_callback" src tests examples dev`
Expected: no matches (exit 1).

Run: `grep -rn "import rich\|from rich" src`
Expected: no matches (exit 1) — `rich` is gone from the library.

- [ ] **Step 6: Confirm the package imports cleanly and rich isn't pulled in**

Run: `cd engine && python -c "import co_scientist; print(co_scientist.__all__)"`
Expected: the 12-entry list from Step 2, no `ConsoleReporter`.

Run: `python -c "import co_scientist, sys; assert 'rich' not in sys.modules, sorted(m for m in sys.modules if m.startswith('rich'))"`
Expected: no assertion error.

- [ ] **Step 7: Engine gate**

Run: `cd engine && yapf -d examples/run.py && pytest && mypy . && pylint --rcfile=../pylintrc src/co_scientist`
Expected: yapf clean, all pass. (After moving `rich` to `dev`, `pip install -e '.[dev]'` still provides it for the `dev/` scripts; re-run `pip install -e '.[dev]'` if the environment complains.)

- [ ] **Step 8: Commit**

```bash
git add engine/src/co_scientist/__init__.py engine/examples/run.py engine/pyproject.toml
git commit -m "refactor(engine): remove Rich console reporter from library"
```

---

## Task 4: Characterization tests for untested prompt getters

Before refactoring `prompts.py` (Task 5), lock the behavior of the getters that currently have **no** direct content test. These tests must pass against the **current, unrefactored** code — that is what makes them a safety net. This task adds only tests; no source changes.

**Files:**
- Modify: `engine/tests/test_prompts.py`

**Interfaces:**
- Consumes: current public getters `get_literature_review_query_generation_prompt`, `get_literature_review_synthesis_prompt`, `get_hypothesis_novelty_analysis_prompt`, `get_hypothesis_validation_synthesis_prompt`, `get_validation_synthesis_prompt_with_tools`, `get_review_prompt`.
- Produces: named tests Task 5 relies on staying green: `test_source_aware_query_prompt_selects_template_by_source_type`, `test_literature_synthesis_prompt_renders_paper_analyses`, `test_novelty_analysis_prompt_interpolates_metadata`, `test_validation_synthesis_prompt_renders_drafts_no_schema`, `test_validation_synthesis_with_tools_returns_schema`, `test_domain_injection_populates_domain_placeholders`.

- [ ] **Step 1: Verify the exact signatures/return shapes of the target getters**

Run: `cd engine && sed -n '748,995p;1014,1120p' src/co_scientist/prompts.py`
Read each target getter's signature and its keyword names (e.g. `source_type`, `paper_analyses`, `hypotheses_with_analyses`, `articles`, `max_iterations`) and whether it returns `str` or `tuple[str, dict|None]`. Adjust the test inputs below if any keyword differs from what is written here. Also confirm the domain-variable field names by reading `_get_domain_variables` and the `{{domain_*}}` placeholders in `src/co_scientist/prompts/review.md`.

- [ ] **Step 2: Add the characterization tests**

Append to `engine/tests/test_prompts.py` (add the imports to the existing `from co_scientist.prompts import ...` block):

```python
def test_source_aware_query_prompt_selects_template_by_source_type() -> None:
    """The source-aware query builder embeds the goal for each source type."""
    for source_type in ("knowledge_graph", "pubmed", "academic"):
        prompt = get_literature_review_query_generation_prompt(
            research_goal="find biomarkers for sepsis",
            source_type=source_type,
            user_literature=["Smith 2020 sepsis review"],
        )
        assert isinstance(prompt, str)
        assert prompt
        assert "find biomarkers for sepsis" in prompt
        assert "{{MISSING" not in prompt


def test_literature_synthesis_prompt_renders_paper_analyses() -> None:
    """The synthesis builder embeds the goal and each paper's findings."""
    prompt = get_literature_review_synthesis_prompt(
        research_goal="explain insulin resistance",
        paper_analyses=[{
            "metadata": {
                "title": "Hepatic glucose output revisited",
                "authors": ["P. First"],
                "year": 2019,
            },
            "analysis": {
                "key_findings": "gluconeogenesis is upregulated",
                "gaps_identified": "no in-vivo validation",
            },
        }],
    )
    assert isinstance(prompt, str)
    assert "explain insulin resistance" in prompt
    assert "Hepatic glucose output revisited" in prompt
    assert "{{MISSING" not in prompt


def test_novelty_analysis_prompt_interpolates_metadata() -> None:
    """The novelty-analysis builder embeds the hypothesis and metadata."""
    prompt = get_hypothesis_novelty_analysis_prompt(
        hypothesis_text="APOE4 impairs astrocyte lipid transport",
        title="Astrocyte lipid handling in AD",
        authors=["A. One", "B. Two"],
        year=2021,
        fulltext="Full text discussing APOE isoforms.",
    )
    assert isinstance(prompt, str)
    assert "APOE4 impairs astrocyte lipid transport" in prompt
    assert "Astrocyte lipid handling in AD" in prompt
    assert "2021" in prompt
    assert "{{MISSING" not in prompt


def test_validation_synthesis_prompt_renders_drafts_no_schema() -> None:
    """The (no-tools) validation synthesis builder returns a filled str."""
    prompt = get_hypothesis_validation_synthesis_prompt(
        research_goal="reduce tumor metastasis",
        hypotheses_with_analyses=[{
            "draft": {
                "text": "block CXCR4 signaling",
                "gap_reasoning": "under-studied in metastasis",
                "literature_sources": "[C1]",
            },
            "novelty_analyses": [{
                "paper_metadata": {"title": "CXCR4 in cancer", "year": 2020},
                "analysis": {"novelty_assessment": "complementary"},
            }],
        }],
    )
    assert isinstance(prompt, str)
    assert "reduce tumor metastasis" in prompt
    assert "block CXCR4 signaling" in prompt


def test_validation_synthesis_with_tools_returns_schema() -> None:
    """The tools variant embeds drafts and returns a non-None schema."""
    prompt, schema = get_validation_synthesis_prompt_with_tools(
        research_goal="reduce tumor metastasis",
        hypotheses_with_analyses=[{
            "draft": {
                "text": "block CXCR4 signaling",
                "gap_reasoning": "under-studied",
                "literature_sources": "[C1]",
            },
            "novelty_analyses": [],
        }],
        max_iterations=5,
    )
    assert isinstance(prompt, str)
    assert "reduce tumor metastasis" in prompt
    assert "block CXCR4 signaling" in prompt
    assert schema is not None


def test_domain_injection_populates_domain_placeholders() -> None:
    """A registry with prompts_config fills domain_* placeholders (review)."""

    class _StubPromptsConfig:
        domain_context = "ONCOLOGY-CONTEXT"
        generation_guidance = "GEN-G"
        review_guidance = "REVIEW-G"
        evolution_guidance = "EVO-G"
        reflection_guidance = "REFL-G"

    class _StubRegistry:

        def get_prompts_config(self) -> _StubPromptsConfig:
            return _StubPromptsConfig()

    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        tool_registry=_StubRegistry(),
    )
    assert "ONCOLOGY-CONTEXT" in prompt
    assert "REVIEW-G" in prompt
```

- [ ] **Step 3: Run the new tests against current code — they must PASS**

Run: `cd engine && pytest tests/test_prompts.py -q -k "source_aware or literature_synthesis or novelty_analysis or validation_synthesis or domain_injection"`
Expected: all pass. If a test fails, the fixture shape is wrong for the real getter (not a code bug) — fix the test input using Step 1's reading until it passes against unmodified `prompts.py`. In particular, `_StubRegistry` must match how `_get_domain_variables` accesses the registry (method name and the `prompts_config` field names); adjust the stub to match the real interface. Do not proceed until green.

- [ ] **Step 4: Full getter suite still green**

Run: `cd engine && pytest tests/test_prompts.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/tests/test_prompts.py
git commit -m "test(engine): characterize untested prompt getters"
```

---

## Task 5: Consolidate `prompts.py` getters behind `_build_prompt`

Introduce one internal `_build_prompt()` that captures the shared getter skeleton (base vars + optional supervisor/meta-review/run-guidance blocks + optional domain-variable injection + `load_prompt_with_schema`), then collapse the 8 simple getters and delegate the shared *tail* of 3 bespoke getters to it. **Every public signature and rendered output stays byte-identical** — guarded by a before/after diff harness and the tests from Task 4 plus the existing `test_prompts.py`/`test_meta_review_threading.py`.

Critical correctness rule (from reading `substitute_variables`): a variable in the dict but absent from the template is silently ignored; a placeholder in the template but absent from the dict renders as the literal `{{MISSING:name}}`. So the builder must add each optional key **only when the caller passes it** — never blanket-inject. Getters that today always call `_format_*(None) -> ""` still pass `""` (key present); getters that never set a key must still not set it.

**Files:**
- Modify: `engine/src/co_scientist/prompts.py`
- Temp (not committed): `engine/_prompt_baseline.py` harness + baseline output dir

**Interfaces:**
- Consumes: Task 4's characterization tests (must stay green).
- Produces: internal `_build_prompt(prompt_name, base_variables, *, supervisor_guidance=None, meta_review_context=None, run_guidance=None, tool_registry=None, include_domain=True) -> tuple[str, dict[str, Any] | None]`. No public API change.

- [ ] **Step 1: Write the byte-identical baseline harness**

Create `engine/_prompt_baseline.py` (temporary; deleted in Step 8). It renders every getter that Task 5 touches across an input matrix and writes each `(prompt, schema)` to `engine/_prompt_out/<label>.txt`. Cover the 8 simple getters + the 3 tail-delegated getters (`get_ranking_prompt`, `get_draft_prompt_with_tools`, `get_validation_synthesis_prompt_with_tools`), each with: no guidance, non-None supervisor/meta/run guidance, and a populated stub `tool_registry`. Use fixed literal inputs (mirror the fixtures in `tests/test_prompts.py` and Task 4). Write with `repr()` so schema dicts serialize deterministically. Example skeleton:

```python
"""Temporary harness: dump getter outputs for byte-identical diffing."""
import os
import co_scientist.prompts as p

OUT = "_prompt_out"
os.makedirs(OUT, exist_ok=True)


class _Cfg:
    domain_context = "CTX"
    generation_guidance = "GEN"
    review_guidance = "REV"
    evolution_guidance = "EVO"
    reflection_guidance = "REFL"


class _Reg:

    def get_prompts_config(self):
        return _Cfg()


def dump(label, value):
    with open(os.path.join(OUT, label + ".txt"), "w") as fh:
        fh.write(repr(value))


GUID = {"focus_areas": ["a"], "avoid": ["b"]}  # match real guidance shape

# For each touched getter, dump a few cases (None vs guidance vs registry).
dump("review_plain", p.get_review_prompt("g", "h"))
dump("review_guided",
     p.get_review_prompt("g", "h", supervisor_guidance=GUID,
                         meta_review={"summary": "m"}, tool_registry=_Reg(),
                         run_setup_guidance="rs", run_focus_guidance="rf"))
# ... repeat for review_batch, deep_verification, meta_review,
#     research_overview, proximity, supervisor, reflection, ranking,
#     draft_with_tools, validation_synthesis_with_tools ...
```

Before writing cases, read the real guidance-dict shape by grepping how nodes call these getters (`grep -rn "supervisor_guidance=" src/co_scientist/nodes`) and the `_GUIDANCE` fixture in `tests/test_prompts.py`, so `GUID` matches production. Fill in all 11 getters × their cases.

- [ ] **Step 2: Capture the baseline (pre-refactor)**

Run: `cd engine && rm -rf _prompt_out && python _prompt_baseline.py && mv _prompt_out _prompt_baseline_out`
Expected: `_prompt_baseline_out/` populated with one `.txt` per case. This is the ground truth.

- [ ] **Step 3: Add `_build_prompt` and refactor the 8 simple getters**

Insert `_build_prompt` immediately after `_get_domain_variables` (~line 201):

```python
def _build_prompt(
    prompt_name: str,
    base_variables: dict[str, Any],
    *,
    supervisor_guidance: str | None = None,
    meta_review_context: str | None = None,
    run_guidance: str | None = None,
    tool_registry: Any | None = None,
    include_domain: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """Assemble a prompt's variables and load it with its schema.

    Reproduces the shared getter skeleton: a caller-provided base of
    template-specific variables, plus the optional guidance/context blocks
    and the domain-variable injection that most node prompts share. Each
    optional block is added to the variables dict only when the caller
    passes a non-``None`` value, so a template placeholder the caller
    intentionally omits still renders as the ``{{MISSING:...}}`` sentinel
    (matching pre-consolidation behavior) rather than an empty string.

    Args:
        prompt_name: Prompt file stem passed to ``load_prompt_with_schema``.
        base_variables: Always-present, template-specific variables. Copied,
            not mutated.
        supervisor_guidance: Pre-formatted supervisor-guidance block (the
            caller selects the correct ``_format_supervisor_guidance_for_*``
            helper). Added under ``"supervisor_guidance"`` only when not
            ``None``; an empty string still adds the key.
        meta_review_context: Pre-formatted meta-review block. Added under
            ``"meta_review_context"`` only when not ``None``.
        run_guidance: Pre-formatted run setup/focus block. Added under
            ``"run_guidance"`` only when not ``None``.
        tool_registry: Tool registry forwarded to ``_get_domain_variables``
            when ``include_domain`` is true.
        include_domain: Whether to merge the five ``domain_*`` variables.
            Set false for prompts that never inject them (e.g. proximity).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or ``None``).
    """
    variables: dict[str, Any] = dict(base_variables)
    if supervisor_guidance is not None:
        variables["supervisor_guidance"] = supervisor_guidance
    if meta_review_context is not None:
        variables["meta_review_context"] = meta_review_context
    if run_guidance is not None:
        variables["run_guidance"] = run_guidance
    if include_domain:
        variables.update(_get_domain_variables(tool_registry))
    return load_prompt_with_schema(prompt_name, variables)
```

Then rewrite the bodies of these 8 getters — **keep each `def` line, parameter list, and docstring exactly as they are in the current file** (verified signatures; do not retype from memory — copy the existing signature), replacing only the body:

- `get_review_prompt` → base `{"research_goal", "hypothesis_text"}`, `supervisor_guidance=_format_supervisor_guidance_for_review(supervisor_guidance)`, `meta_review_context=_format_meta_review_context(meta_review)`, `run_guidance=_format_run_guidance(run_setup_guidance, run_focus_guidance)`, `tool_registry=tool_registry`, prompt `"review"`.
- `get_review_batch_prompt` → same as review but base `{"research_goal", "hypotheses_list"}`, prompt `"review_batch"`.
- `get_deep_verification_prompt` → base `{"research_goal", "hypothesis_text"}`, only `tool_registry=tool_registry`, prompt `"deep_verification"`.
- `get_meta_review_prompt` → base `{"research_goal", "all_reviews", "instructions": instructions or ""}`, `supervisor_guidance=_format_supervisor_guidance_for_meta_review(supervisor_guidance)`, `run_guidance=_format_run_guidance(...)`, `tool_registry=tool_registry`, prompt `"meta_review"`. (No `meta_review_context`.)
- `get_research_overview_prompt` → base `{"research_goal", "hypotheses_summary"}`, `meta_review_context=_format_meta_review_context(meta_review)`, `run_guidance=...`, `tool_registry=tool_registry`, prompt `"research_overview"`. (No supervisor.)
- `get_proximity_prompt` → base `{"hypotheses": json.dumps([...], indent=2)}` (keep the existing `import json` and list comprehension), `supervisor_guidance=_format_supervisor_guidance_for_proximity(supervisor_guidance)`, `include_domain=False`, prompt `"proximity"`. (No domain, no meta, no run.)
- `get_supervisor_prompt` → keep the `lit_review_description` branch, pass the full inline base dict, `run_guidance=_format_run_guidance(...)`, `tool_registry=tool_registry`, prompt `"supervisor"`. (No supervisor_guidance kwarg, no meta.)
- `get_reflection_prompt` → base `{"articles_with_reasoning", "hypothesis": hypothesis_text, "indra_evidence": indra_evidence}`, `meta_review_context=_format_meta_review_context(meta_review)`, `tool_registry=tool_registry`, prompt `"reflection_observations"`. (No supervisor, no run.)

- [ ] **Step 4: Delegate the shared tail of 3 bespoke getters**

Leave all bespoke base-dict assembly intact; replace only the trailing `variables[...] = ...; variables.update(_get_domain_variables(...)); return load_prompt_with_schema(...)` sequence with a `_build_prompt` call:

- `get_ranking_prompt`: keep building `variables` (review_context, reflection-note defaults, deep-verification pair). Then `return _build_prompt("ranking", variables, supervisor_guidance=_format_supervisor_guidance_for_ranking(supervisor_guidance), meta_review_context=_format_meta_review_context(meta_review), run_guidance=_format_run_guidance(run_setup_guidance, run_focus_guidance), tool_registry=tool_registry)`.
- `get_draft_prompt_with_tools`: keep tool/citation/format assembly (supervisor pre-baked into base). Then `return _build_prompt("generation_draft_with_tools", variables, meta_review_context=_format_meta_review_context(meta_review), run_guidance=_format_run_guidance(run_setup_guidance, run_focus_guidance), tool_registry=tool_registry)` (no supervisor_guidance kwarg).
- `get_validation_synthesis_prompt_with_tools`: keep the per-hypothesis loop and tool/already-validated assembly. Then `return _build_prompt("hypothesis_validation_synthesis_with_tools", variables, tool_registry=tool_registry)` (all optionals default None).

**Do not touch** `get_debate_generation_prompt` or the six `load_prompt`/`str` getters (#10–15) — they return `str` or fork the load path; forcing them through `_build_prompt` changes return types.

- [ ] **Step 5: Capture post-refactor outputs and diff against baseline**

Run: `cd engine && rm -rf _prompt_out && python _prompt_baseline.py && diff -r _prompt_baseline_out _prompt_out && echo "BYTE-IDENTICAL"`
Expected: `BYTE-IDENTICAL` with no diff output. Any diff means a getter's variable mapping changed — fix the getter until the diff is clean.

- [ ] **Step 6: Run the getter test suites**

Run: `cd engine && pytest tests/test_prompts.py tests/test_meta_review_threading.py -q`
Expected: all pass, including Task 4's characterization tests and `test_ranking_prompt_empty_optional_slots_are_byte_clean`.

- [ ] **Step 7: Full engine gate**

Run: `cd engine && pytest && mypy . && pylint --rcfile=../pylintrc src/co_scientist/prompts.py && yapf -ir src/co_scientist/prompts.py`
Expected: all pass; yapf reformats to 80-col Google style if needed (re-run pytest if yapf changed anything).

- [ ] **Step 8: Remove the harness and commit**

```bash
cd engine && rm -rf _prompt_baseline.py _prompt_out _prompt_baseline_out
git add engine/src/co_scientist/prompts.py
git status   # confirm no _prompt_* artifacts staged
git commit -m "refactor(engine): consolidate prompt getters behind builder"
```

---

## Task 6: Documentation sweep

Update every doc that referenced a deleted endpoint, config, or `console.py`. `CLAUDE.md` is a symlink to `AGENTS.md` — edit `AGENTS.md`. All line numbers are approximate; match on the quoted text.

**Files:**
- Modify: `AGENTS.md`, `app/README.md`, `docs/ARCHITECTURE.md`, `docs/EXPLAINER.md`, `engine/README.md`, `engine/docs/DEVELOPMENT.md`, `engine/docs/DOMAIN_CUSTOMIZATION.md`, `engine/src/co_scientist/config/examples/README.md`

**Interfaces:**
- Consumes: the deletions from Tasks 1–3.
- Produces: docs consistent with the trimmed code.

- [ ] **Step 1: `AGENTS.md`**
  - In the `WorkflowState`/prompts paragraph, change the trailing sentence about config examples "per domain (biomed/cyber/etc.)" to: "with a bundled example config in `config/examples/` (`indra_cancer.yaml`)."
  - In "Key supporting modules", delete the `` , `console.py` (Rich-based terminal reporter) `` clause; keep the rest of the list.
  - In the app table, change the `main.py` row to: `| `main.py` | App setup, lifespan, diagnostics endpoints (`/health`, `/config`, `/status`) |`.
  - Change the `Legacy (in `main.py`):` heading to `Diagnostics (in `main.py`):` and delete the three bullet lines for `POST /generate`, `POST /generate/start` + `GET /generate/stream/{task_id}`, and `POST /cancel_hypothesis_generation`. Keep the `GET /health`, `/config`, `/status` bullet.

- [ ] **Step 2: `app/README.md`**
  - Change the `main.py` file-tree comment to: `App setup and diagnostics endpoints (/health, /config, /status)`.
  - Delete the four `/generate*` + `/cancel_hypothesis_generation` rows from the endpoints table. Keep `/health`, `/config`, `/status`.

- [ ] **Step 3: `docs/ARCHITECTURE.md`**
  - Change "the new router is mounted alongside the existing `/generate` endpoints." to "…alongside the diagnostics endpoints (`/health`, `/config`, `/status`)."

- [ ] **Step 4: `docs/EXPLAINER.md`**
  - In the "Domain configs" bullet, reduce the config list to: "making the engine domain-agnostic (e.g. `indra_cancer.yaml`)." — drop `indra_alzheimers.yaml`, `cybersecurity_hydra.yaml`, and the multi-source mention.

- [ ] **Step 5: `engine/README.md`**
  - Delete the entire `ConsoleReporter` subsection (the "For rich terminal output, use the built-in `ConsoleReporter`:" sentence through its closing code fence). The preceding plain-`print` streaming example is sufficient.
  - Change "Pre-built examples in `.../examples/` cover:" to "A pre-built example in `.../examples/` covers:" and delete the `arxiv_only.yaml`, `multi_source.yaml`, and `google_scholar.yaml` bullets; reduce the `indra_*` bullet to: `- `indra_cancer.yaml` — biomedical config extending PubMed with INDRA CoGex knowledge-graph tools`.

- [ ] **Step 6: `engine/docs/DEVELOPMENT.md`**
  - Change the `run.py` file-tree comment from `# CLI example with Console Reporter` to `# CLI example`.

- [ ] **Step 7: `engine/docs/DOMAIN_CUSTOMIZATION.md`**
  - Delete the Alzheimer's subsection (`### Biomedical — Alzheimer's Drug Repurposing (`indra_alzheimers.yaml`)` through its yaml fence).
  - Reword the Cancer subsection so it stands alone (it currently says "Similar to the Alzheimer's config"): "Extends the default PubMed config with INDRA CoGex knowledge graph tools, adapted for oncology hypothesis generation with cancer-specific prompt guidance. INDRA provides curated causal statements from literature, supplementing PubMed full-text search with structured mechanistic knowledge."
  - Delete the Cybersecurity subsection (`### Cybersecurity (`cybersecurity_hydra.yaml`)` through its yaml fence).
  - Delete the Multi-source subsection (`### Multi-source Academic (...)` through the line before the `---` divider).

- [ ] **Step 8: `engine/src/co_scientist/config/examples/README.md` (full rewrite to the single survivor)**
  - Delete the standalone `### <file>.yaml` sections for `arxiv_only.yaml`, `multi_source.yaml`, `google_scholar.yaml`, `pubmed_arxiv_same_server.yaml`, `arxiv_and_google_scholar.yaml`, `arxiv_research_focused.yaml`, `indra_ibd.yaml`, `indra_hfpef.yaml`.
  - Rewrite the "INDRA CoGex Biomedical Domain Configurations" intro (currently "These four configs …") and its table to describe only `indra_cancer.yaml`.
  - Keep the intro paragraph and the generic `content_params` docs. The result documents only `indra_cancer.yaml`.

- [ ] **Step 9: Verify no stale references remain**

Run:
```bash
cd /Users/guy/Code/Co-Scientist && grep -rnE "POST /generate|generate/start|generate/stream|cancel_hypothesis_generation|ConsoleReporter|console\.py|arxiv_and_google_scholar|arxiv_only|arxiv_research_focused|cybersecurity_hydra|google_scholar\.yaml|indra_alzheimers|indra_hfpef|indra_ibd|multiple_sources|multi_source|openalex_grounding|pubmed_arxiv_same_server" AGENTS.md app/README.md docs engine/README.md engine/docs engine/src/co_scientist/config/examples/README.md
```
Expected: no matches (exit 1). (The design spec under `docs/specs/` legitimately mentions these — it is out of scope; if it appears, ignore it. `references/` and `.remember/` are out of scope and not searched here.)

- [ ] **Step 10: Commit**

```bash
git add AGENTS.md app/README.md docs/ARCHITECTURE.md docs/EXPLAINER.md engine/README.md engine/docs/DEVELOPMENT.md engine/docs/DOMAIN_CUSTOMIZATION.md engine/src/co_scientist/config/examples/README.md
git commit -m "docs: reconcile docs with trimmed code"
```

---

## Final verification (after all tasks)

- [ ] **Engine:** `cd engine && pytest && mypy . && pylint --rcfile=../pylintrc src/co_scientist`
- [ ] **App:** `cd app && make test && make typecheck && make lint`
- [ ] **Frontend (sanity — no source changes expected):** `cd app/frontend && bun run build && bun run test`
- [ ] **End-to-end mock run:** start the app with the mock provider (`COSCIENTIST_FORCE_MOCK=1`), create a run via `POST /api/runs`, start it, stream `GET /api/runs/{id}/events` to completion; confirm `/status` responds and no legacy route exists.
- [ ] **LOC delta report:** `git diff --stat main` to confirm the net reduction (~4,700 lines, dominated by the 11 YAML deletions, `console.py`, and the legacy API).

## Notes on what is intentionally NOT changed (guardrails)

- `app/frontend/src/styles/home_surface.css` and `shell_surface.css` are **live** (imported via `src/styles/surfaces.css`, classes consumed through `chat_home_classes.ts`). Do not delete.
- `save_prompt_to_disk` / `get_prompt_save_path` in `prompts.py` are **live** (called by six node modules). Do not delete.
- `mock_workflow.py`, `run_modes.py`, `seed.py`, `engine_adapter.py`, frontend `src/public/` pages, all graph nodes, `mcp_server/`, and `engine/dev/` scripts stay.
- `schemas.py` is not rewritten. `test_config_registry.py` is not edited.
