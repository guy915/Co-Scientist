# User Audience Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three self-declared audience modes (general / google / sbi_ucd) to the Co-Scientist workbench that tailor the header control, home suggestions, a Google recommendations page, and — for SBI/UCD only — inject lab context into run planning and chat Q&A prompts.

**Architecture:** A localStorage-backed React context (`audience_context.tsx`, mirroring `theme_context.tsx`) drives all frontend variation. A first-visit modal sets the choice; Settings re-opens it. The backend gains an optional `audience` field on run-create and ask requests; when it is `sbi_ucd`, a cached markdown loader (`app/app/audience.py`) supplies context that is stored in the durable run `setup` block (rendered by `setup_guidance`) and appended to the chat system prompt. All other audiences are behaviorally identical to today.

**Tech Stack:** Backend — FastAPI, pydantic, pytest (asyncio_mode=auto), ruff (80 cols). Frontend — React 19, Vite, TypeScript, Tailwind v4, Vitest + React Testing Library, gts (Google TS style).

## Global Constraints

- Python: ruff format + lint, 80 columns; Google-style docstrings (`Args:`/`Returns:`), capitalized full sentences; `logger.debug()` lowercase, `info`/`warning`/`error` capitalized; no emojis/unicode in code or logs; no Rich in core library.
- TypeScript: gts (ESLint + Prettier); colocated `*.test.tsx`; import alias `@/` = `src/`.
- Audience values are exactly `general | google | sbi_ucd`. Regex for backend pattern validation: `^(general|google|sbi_ucd)$`. Frontend storage key: `cosci-audience`.
- Backend behavior changes ONLY for `sbi_ucd`. `general` and `google` requests must resolve identically to today.
- Never add Claude/AI co-author trailers or attribution to commits (repo rule). Commit format: `<type>(<scope>): <subject>`.
- Run backend commands from `app/`; frontend commands from `app/frontend/`.
- Content ships as clearly-marked drafts in dedicated files.

---

## File Structure

**Backend (create):**
- `app/app/audience.py` — audience validation constant + cached markdown context loader.
- `app/app/content/sbi_ucd_context.md` — drafted lab background injected into `sbi_ucd` prompts.
- `app/tests/test_audience.py` — loader tests.

**Backend (modify):**
- `app/app/run_modes.py` — `setup_config` accepts `audience_context`; `setup_guidance` renders it.
- `app/app/runs_models.py` — `CreateRunRequest.audience`, `AskRequest.audience`; thread audience through `_build_create_run_config`.
- `app/app/qa.py` — `build_system_prompt` accepts `audience_context`.
- `app/app/runs.py` — `ask_question` loads audience context and passes it to `build_system_prompt`.
- `app/tests/` — extend `test_run_modes.py`, `test_qa.py` / add cases.

**Frontend (create):**
- `app/frontend/src/workbench/audience_context.tsx` — `Audience` type, provider, `useAudience`.
- `app/frontend/src/workbench/audience_context.test.tsx`
- `app/frontend/src/workbench/components/audience_dialog.tsx` — first-visit + re-open modal.
- `app/frontend/src/workbench/components/audience_dialog.test.tsx`
- `app/frontend/src/workbench/audience_content.ts` — Google message, recommendations copy, pilot copy + feedback email, SBI suggestions.
- `app/frontend/src/workbench/layout_google_control.tsx` — `GoogleTeamControl`.
- `app/frontend/src/workbench/layout_pilot_control.tsx` — `PilotControl`.
- `app/frontend/src/workbench/pages/recommendations_page.tsx` — `/recommendations` route.

**Frontend (modify):**
- `app/frontend/src/workbench/workbench_app.tsx` — mount `AudienceProvider`; add `/recommendations` route.
- `app/frontend/src/workbench/layout.tsx` — render `AudienceDialog`; pass audience to header.
- `app/frontend/src/workbench/layout_header.tsx` — audience-conditional header control.
- `app/frontend/src/workbench/components/settings_dialog.tsx` — "Affiliation" section.
- `app/frontend/src/workbench/pages/chat_home_stage.tsx` — audience-aware `SUGGESTIONS`.
- `app/frontend/src/api/runs.ts` — `audience` on `createRun` and `askRunQuestion`.
- `app/frontend/src/workbench/hooks/chat_session_start_run.ts` — send audience on create.

---

## Task 1: Audience context loader (backend)

**Files:**
- Create: `app/app/audience.py`
- Create: `app/app/content/sbi_ucd_context.md`
- Test: `app/tests/test_audience.py`

**Interfaces:**
- Produces:
  - `VALID_AUDIENCES: tuple[str, ...] = ("general", "google", "sbi_ucd")`
  - `AUDIENCE_PATTERN: str = "^(general|google|sbi_ucd)$"`
  - `audience_context(audience: str | None) -> str` — returns the `sbi_ucd` markdown for `"sbi_ucd"`, `""` otherwise or on read failure.

- [ ] **Step 1: Write the drafted content file**

Create `app/app/content/sbi_ucd_context.md`:

```markdown
<!-- DRAFT: first-pass SBI/UCD lab context. Replace with the lab's real
background and research summaries. This text is injected into run planning
and chat answers when a user selects the SBI/UCD audience. -->

# SBI / UCD research context

The user is a researcher affiliated with the Systems Biology Ireland (SBI)
institute at University College Dublin (UCD). SBI focuses on network and
systems approaches to cell signalling, with an emphasis on cancer cell
biology, computational modelling of signalling pathways, and translational
oncology.

When generating hypotheses or answering questions for this user:

- Favour mechanistic hypotheses grounded in cell-signalling network biology
  (for example MAPK/ERK, PI3K/AKT, and receptor tyrosine kinase pathways).
- Prefer directions that are experimentally testable with the assays common
  to a systems-biology wet lab (proteomics, phospho-signalling readouts,
  perturbation screens, single-cell measurements).
- Connect proposals to translational cancer relevance where possible.
- Treat this context as background about the user's field, not as a
  constraint that overrides the user's stated research goal.
```

- [ ] **Step 2: Write the failing test**

Create `app/tests/test_audience.py`:

```python
"""Tests for the audience context loader."""

from __future__ import annotations

from app import audience


def test_sbi_ucd_returns_nonempty_context() -> None:
    text = audience.audience_context("sbi_ucd")
    assert "SBI" in text
    assert len(text) > 0


def test_other_audiences_return_empty() -> None:
    assert audience.audience_context("general") == ""
    assert audience.audience_context("google") == ""
    assert audience.audience_context(None) == ""
    assert audience.audience_context("bogus") == ""


def test_pattern_and_values_exposed() -> None:
    assert audience.VALID_AUDIENCES == ("general", "google", "sbi_ucd")
    assert audience.AUDIENCE_PATTERN == "^(general|google|sbi_ucd)$"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app && .venv/bin/python -m pytest tests/test_audience.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.audience'`.

- [ ] **Step 4: Write the implementation**

Create `app/app/audience.py`:

```python
"""Audience-specific prompt context, loaded from bundled markdown files.

Only the ``sbi_ucd`` audience carries injected context today; the loader is
written generically so adding another audience's file is a one-line change.
The file is read once and cached, since it never changes at runtime.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_AUDIENCES: tuple[str, ...] = ("general", "google", "sbi_ucd")
AUDIENCE_PATTERN: str = "^(general|google|sbi_ucd)$"

# Audiences with a bundled context file, mapped to their filename under
# ``content/``. Absent audiences contribute no context.
_CONTEXT_FILES: dict[str, str] = {"sbi_ucd": "sbi_ucd_context.md"}

_CONTENT_DIR = Path(__file__).parent / "content"


@lru_cache(maxsize=None)
def _load_context_file(filename: str) -> str:
    """Read and cache one context markdown file, or return empty on failure.

    Args:
        filename: The file's name under the ``content/`` directory.

    Returns:
        The file's text, or an empty string if it cannot be read.
    """
    path = _CONTENT_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Could not read audience context %s: %s", path, exc)
        return ""


def audience_context(audience: str | None) -> str:
    """Return the prompt context for an audience, or empty when it has none.

    Args:
        audience: The self-declared audience value, possibly None or unknown.

    Returns:
        The audience's injected context text, or an empty string when the
        audience has no bundled context (all but ``sbi_ucd`` today).
    """
    filename = _CONTEXT_FILES.get(audience or "")
    if filename is None:
        return ""
    return _load_context_file(filename)
```

- [ ] **Step 5: Ensure content is packaged**

Confirm `app/app/content/` markdown ships with the package. Inspect `app/pyproject.toml` for `[tool.setuptools.package-data]` (or equivalent). If package-data globs exist and do not already include `content/*.md`, add:

```toml
[tool.setuptools.package-data]
app = ["content/*.md"]
```

If the project uses `include-package-data`/`MANIFEST.in` or reads the file via a runtime path only (as this loader does — `Path(__file__).parent`), no change is needed; the runtime path works from an editable install regardless. Note the decision in the commit message.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd app && .venv/bin/python -m pytest tests/test_audience.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Lint and commit**

```bash
cd app && ruff format app/audience.py tests/test_audience.py && ruff check app/audience.py tests/test_audience.py
git add app/app/audience.py app/app/content/sbi_ucd_context.md app/tests/test_audience.py
git commit -m "feat(audience): add sbi_ucd prompt context loader"
```

---

## Task 2: Render audience context in run setup guidance

**Files:**
- Modify: `app/app/run_modes.py` (`setup_config`, `setup_guidance`)
- Test: `app/tests/test_run_modes.py` (create — there is no dedicated run_modes test module today)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `setup_config(..., audience_context: str = "")` — stores non-empty context under `setup["audience_context"]`.
  - `setup_guidance(setup)` renders an `Audience context:` section when `setup["audience_context"]` is non-empty.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_run_modes.py`:

```python
"""Tests for run-mode setup config and guidance."""

from __future__ import annotations

from app import run_modes


def test_setup_config_stores_audience_context() -> None:
    setup = run_modes.setup_config(
        research_goal="goal",
        audience_context="LAB BACKGROUND",
    )
    assert setup["audience_context"] == "LAB BACKGROUND"


def test_setup_config_omits_empty_audience_context() -> None:
    setup = run_modes.setup_config(research_goal="goal")
    assert "audience_context" not in setup


def test_setup_guidance_renders_audience_context() -> None:
    setup = run_modes.setup_config(
        research_goal="goal",
        audience_context="LAB BACKGROUND",
    )
    guidance = run_modes.setup_guidance(setup)
    assert "Audience context:" in guidance
    assert "LAB BACKGROUND" in guidance


def test_setup_guidance_without_audience_context() -> None:
    setup = run_modes.setup_config(research_goal="goal")
    assert "Audience context:" not in run_modes.setup_guidance(setup)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && .venv/bin/python -m pytest tests/test_run_modes.py -k audience -v`
Expected: FAIL — `setup_config()` got an unexpected keyword `audience_context`.

- [ ] **Step 3: Implement in `run_modes.py`**

Change `setup_config` signature and body (add the parameter and conditional key). Replace the current `def setup_config(...)` signature line to add `audience_context: str = "",` after `tier`, and add before the `return`:

```python
def setup_config(
    *,
    research_goal: str,
    requirements: list[str] | None = None,
    attributes: list[str] | None = None,
    criteria: list[str] | None = None,
    focus: str | None = None,
    tier: str | None = None,
    audience_context: str = "",
) -> dict[str, Any]:
    """Build the durable setup block persisted inside run config JSON.

    Callers that omit requirements/attributes/criteria (a direct API call, a
    seeded demo) fall back to the client-independent planning baseline so the
    engine always receives guidance regardless of which client created the run.
    A non-empty audience_context is stored so setup_guidance can surface it to
    the planning and generation agents.
    """
    setup: dict[str, Any] = {
        "goal": research_goal.strip(),
        "requirements": clean_string_list(requirements)
        or list(DEFAULT_REQUIREMENTS),
        "attributes": clean_string_list(attributes) or list(DEFAULT_ATTRIBUTES),
        "criteria": clean_string_list(criteria) or list(DEFAULT_CRITERIA),
        "focus": normalize_run_focus(focus),
        "tier": normalize_run_tier(tier),
    }
    if audience_context.strip():
        setup["audience_context"] = audience_context.strip()
    return setup
```

In `setup_guidance`, after the `for title, key in (...)` loop that appends Requirements/Attributes/Criteria, add before `return "\n".join(lines)`:

```python
    context = setup.get("audience_context")
    if isinstance(context, str) and context.strip():
        lines.append("Audience context:")
        lines.append(context.strip())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && .venv/bin/python -m pytest tests/test_run_modes.py -k audience -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full run_modes suite (no regressions)**

Run: `cd app && .venv/bin/python -m pytest tests/test_run_modes.py -v`
Expected: PASS (all).

- [ ] **Step 6: Lint and commit**

```bash
cd app && ruff format app/run_modes.py tests/test_run_modes.py && ruff check app/run_modes.py tests/test_run_modes.py
git add app/app/run_modes.py app/tests/test_run_modes.py
git commit -m "feat(run-modes): surface audience context in setup guidance"
```

---

## Task 3: Thread audience through run creation

**Files:**
- Modify: `app/app/runs_models.py` (`CreateRunRequest`, `_build_create_run_config`)
- Test: `app/tests/test_runs_models.py` (create if absent) or the existing run-create test module.

**Interfaces:**
- Consumes: `audience.audience_context`, `audience.AUDIENCE_PATTERN` (Task 1); `setup_config(audience_context=...)` (Task 2).
- Produces: `CreateRunRequest.audience: str | None`; the resolved config's `setup` carries `audience_context` only for `sbi_ucd`.

- [ ] **Step 1: Write the failing test**

Add `app/tests/test_runs_models.py` (or extend the existing module that constructs `CreateRunRequest`):

```python
"""Tests for create-run config resolution with audience context."""

from __future__ import annotations

from app.runs_models import CreateRunRequest, _build_create_run_config


def test_sbi_ucd_injects_audience_context() -> None:
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")
    config, _focus, _tier = _build_create_run_config(req)
    assert "SBI" in config["setup"]["audience_context"]


def test_general_audience_has_no_context() -> None:
    req = CreateRunRequest(research_goal="goal", audience="general")
    config, _focus, _tier = _build_create_run_config(req)
    assert "audience_context" not in config["setup"]


def test_missing_audience_has_no_context() -> None:
    req = CreateRunRequest(research_goal="goal")
    config, _focus, _tier = _build_create_run_config(req)
    assert "audience_context" not in config["setup"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && .venv/bin/python -m pytest tests/test_runs_models.py -v`
Expected: FAIL — `CreateRunRequest` has no `audience` field (pydantic raises on the kwarg, or the field is silently ignored and the context assertion fails).

- [ ] **Step 3: Implement in `runs_models.py`**

Add the import near the top:

```python
from app.audience import AUDIENCE_PATTERN, audience_context
```

Add the field to `CreateRunRequest` (after `notify_on_completion`):

```python
    # Self-declared audience (honor system). Only "sbi_ucd" changes behavior:
    # it injects lab context into planning. Persisted for provenance.
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)
```

In `_build_create_run_config`, pass the loaded context into `setup_config`:

```python
    setup = setup_config(
        research_goal=req.research_goal,
        requirements=req.requirements,
        attributes=req.attributes,
        criteria=req.criteria,
        focus=focus,
        tier=tier,
        audience_context=audience_context(req.audience),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && .venv/bin/python -m pytest tests/test_runs_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Verify audience persists in run config**

Confirm `audience` reaches `config_json`. Since `audience` is not consumed elsewhere in `_run_overrides_from_request`, add it to the persisted overrides so provenance is retained. In `_run_overrides_from_request`, after the `overrides` dict literal, add:

```python
    if req.audience is not None:
        overrides["audience"] = req.audience
```

And in `run_modes.resolved_run_config`, audience is an unknown key routed to `_apply_numeric_override`, which would try `int("sbi_ucd")` and drop it. To carry it through verbatim, register a passthrough handler. In `run_modes.py` add:

```python
def _apply_audience_override(
    base: dict[str, Any], unused_key: str, raw_value: Any
) -> None:
    """Carry the audience through verbatim, in place."""
    base["audience"] = raw_value
```

and add `"audience": _apply_audience_override,` to `_OVERRIDE_HANDLERS`.

Add a test to `app/tests/test_runs_models.py`:

```python
def test_audience_persisted_in_config() -> None:
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")
    config, _focus, _tier = _build_create_run_config(req)
    assert config["audience"] == "sbi_ucd"
```

- [ ] **Step 6: Run tests**

Run: `cd app && .venv/bin/python -m pytest tests/test_runs_models.py tests/test_run_modes.py -v`
Expected: PASS (all).

- [ ] **Step 7: Lint and commit**

```bash
cd app && ruff format app/runs_models.py app/run_modes.py tests/test_runs_models.py && ruff check app/runs_models.py app/run_modes.py tests/test_runs_models.py
git add app/app/runs_models.py app/app/run_modes.py app/tests/test_runs_models.py
git commit -m "feat(runs): inject sbi_ucd audience context into run setup"
```

---

## Task 4: Inject audience context into chat Q&A

**Files:**
- Modify: `app/app/qa.py` (`build_system_prompt`)
- Modify: `app/app/runs_models.py` (`AskRequest.audience`)
- Modify: `app/app/runs.py` (`ask_question`)
- Test: `app/tests/test_qa.py`

**Interfaces:**
- Consumes: `audience.audience_context` (Task 1).
- Produces: `build_system_prompt(..., audience_context: str = "")` appends a context block when non-empty; `AskRequest.audience: str | None`.

- [ ] **Step 1: Write the failing test**

Add to `app/tests/test_qa.py`:

```python
def test_system_prompt_includes_audience_context() -> None:
    prompt = qa.build_system_prompt(
        "goal", [], [], [], [], [], audience_context="LAB BACKGROUND"
    )
    assert "LAB BACKGROUND" in prompt


def test_system_prompt_without_audience_context() -> None:
    prompt = qa.build_system_prompt("goal", [], [], [], [], [])
    assert "LAB BACKGROUND" not in prompt
```

(Match the existing `qa` import in `test_qa.py` — likely `from app import qa`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && .venv/bin/python -m pytest tests/test_qa.py -k audience -v`
Expected: FAIL — `build_system_prompt()` got an unexpected keyword `audience_context`.

- [ ] **Step 3: Implement in `qa.py`**

Add `audience_context: str = ""` as the final parameter of `build_system_prompt`, document it in the docstring `Args:`, and inject it into the returned string. Change the `return (...)` to build a base then append context:

```python
    prompt = (
        f"You are a concise research assistant helping the user understand "
        f"an ongoing AI-driven hypothesis generation run.\n\n"
        f"Research goal: {research_goal}\n\n"
        f"Top hypotheses by Elo:\n{hyp_lines or '(none yet)'}\n\n"
        f"Recent reviews:\n{review_lines or '(none yet)'}\n\n"
        f"Recent tournament matches:\n{match_lines or '(none yet)'}\n\n"
        # ... keep every remaining line of the existing return verbatim ...
    )
    if audience_context.strip():
        prompt += (
            f"\n\nBackground about the user's field:\n"
            f"{audience_context.strip()}"
        )
    return prompt
```

(Preserve every existing line of the current `return` expression inside the `prompt = (...)` assignment — only the trailing append and `return prompt` are new.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && .venv/bin/python -m pytest tests/test_qa.py -k audience -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Add `audience` to `AskRequest` and wire `ask_question`**

In `app/app/runs_models.py`, extend `AskRequest`:

```python
class AskRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages/ask (Q&A)."""

    question: str = Field(..., min_length=1)
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)
```

In `app/app/runs.py`, `ask_question`, add the import at top if not present (`from app.audience import audience_context` — check existing import block) and pass it into `build_system_prompt`:

```python
    system_prompt = qa.build_system_prompt(
        run.research_goal,
        hypotheses,
        reviews,
        matches,
        history,
        manifest,
        audience_context=audience_context(req.audience),
    )
```

- [ ] **Step 6: Run backend suite**

Run: `cd app && .venv/bin/python -m pytest tests/test_qa.py tests/test_runs_models.py -v`
Expected: PASS (all).

- [ ] **Step 7: Typecheck, lint, commit**

```bash
cd app && ruff format app/qa.py app/runs_models.py app/runs.py tests/test_qa.py && ruff check app/qa.py app/runs_models.py app/runs.py tests/test_qa.py && mypy .
git add app/app/qa.py app/app/runs_models.py app/app/runs.py app/tests/test_qa.py
git commit -m "feat(qa): ground chat answers in sbi_ucd audience context"
```

---

## Task 5: Frontend audience context

**Files:**
- Create: `app/frontend/src/workbench/audience_context.tsx`
- Create: `app/frontend/src/workbench/audience_context.test.tsx`
- Modify: `app/frontend/src/workbench/workbench_app.tsx`

**Interfaces:**
- Produces:
  - `export type Audience = 'general' | 'google' | 'sbi_ucd'`
  - `export function AudienceProvider({children}: {children: ReactNode})`
  - `export function useAudience(): {audience: Audience | null; setAudience: (a: Audience) => void}`
  - Storage key `cosci-audience`.

- [ ] **Step 1: Write the failing test**

Create `app/frontend/src/workbench/audience_context.test.tsx`:

```tsx
import {act, renderHook} from '@testing-library/react';
import type {ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider, useAudience} from './audience_context';

const STORAGE_KEY = 'cosci-audience';

function wrapper({children}: {children: ReactNode}) {
  return <AudienceProvider>{children}</AudienceProvider>;
}

describe('audience_context', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('starts null when nothing is stored', () => {
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBeNull();
  });

  it('persists a chosen audience to localStorage', () => {
    const {result} = renderHook(() => useAudience(), {wrapper});
    act(() => result.current.setAudience('sbi_ucd'));
    expect(result.current.audience).toBe('sbi_ucd');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('sbi_ucd');
  });

  it('reads a stored audience on mount', () => {
    window.localStorage.setItem(STORAGE_KEY, 'google');
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBe('google');
  });

  it('treats an unknown stored value as null', () => {
    window.localStorage.setItem(STORAGE_KEY, 'bogus');
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- audience_context`
Expected: FAIL — cannot resolve `./audience_context`.

- [ ] **Step 3: Implement `audience_context.tsx`**

```tsx
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

// Self-declared audience. Persisted in localStorage; honor system, no server
// verification. `null` means the user has not chosen yet (show the dialog).
export type Audience = 'general' | 'google' | 'sbi_ucd';

const STORAGE_KEY = 'cosci-audience';
const VALID: readonly Audience[] = ['general', 'google', 'sbi_ucd'];

interface AudienceContextValue {
  audience: Audience | null;
  setAudience: (a: Audience) => void;
}

const AudienceContext = createContext<AudienceContextValue | null>(null);

// Reads the stored audience; unknown/absent values (and non-browser
// environments) read as null so the first-visit dialog shows.
function readStoredAudience(): Audience | null {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return VALID.includes(stored as Audience) ? (stored as Audience) : null;
}

/**
 * Provides the self-declared audience and persists changes to localStorage.
 *
 * @param props.children The subtree that consumes the audience context.
 */
export function AudienceProvider({children}: {children: ReactNode}) {
  const [audience, setAudienceState] = useState<Audience | null>(
    readStoredAudience,
  );

  useEffect(() => {
    if (audience) window.localStorage.setItem(STORAGE_KEY, audience);
  }, [audience]);

  const setAudience = useCallback((a: Audience) => setAudienceState(a), []);

  const value = useMemo(
    () => ({audience, setAudience}),
    [audience, setAudience],
  );

  return (
    <AudienceContext.Provider value={value}>
      {children}
    </AudienceContext.Provider>
  );
}

/**
 * Returns the current audience and its setter from {@link AudienceProvider}.
 *
 * @returns The active audience (or null if unchosen) and its setter.
 */
export function useAudience(): AudienceContextValue {
  const ctx = useContext(AudienceContext);
  if (!ctx) throw new Error('useAudience used outside AudienceProvider');
  return ctx;
}
```

- [ ] **Step 4: Mount the provider**

In `app/frontend/src/workbench/workbench_app.tsx`, import and nest `AudienceProvider` inside `ThemeProvider`, wrapping `RunHistoryProvider`:

```tsx
import {AudienceProvider} from './audience_context';
```

```tsx
      <ThemeProvider>
        <AudienceProvider>
          <RunHistoryProvider>
            {/* ...existing Layout + Routes... */}
          </RunHistoryProvider>
        </AudienceProvider>
      </ThemeProvider>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- audience_context`
Expected: PASS (4 tests).

- [ ] **Step 6: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/audience_context.tsx src/workbench/audience_context.test.tsx src/workbench/workbench_app.tsx
git commit -m "feat(audience): add frontend audience context and provider"
```

---

## Task 6: Affiliation dialog (first-visit + content)

**Files:**
- Create: `app/frontend/src/workbench/audience_content.ts`
- Create: `app/frontend/src/workbench/components/audience_dialog.tsx`
- Create: `app/frontend/src/workbench/components/audience_dialog.test.tsx`
- Modify: `app/frontend/src/workbench/layout.tsx`

**Interfaces:**
- Consumes: `useAudience` (Task 5).
- Produces:
  - `audience_content.ts`: `AUDIENCE_OPTIONS: {value: Audience; title: string; blurb: string}[]`, plus `GOOGLE_MESSAGE`, `GOOGLE_RECOMMENDATIONS`, `PILOT_GUIDE`, `PILOT_FEEDBACK_EMAIL`, `SBI_SUGGESTIONS` (drafts used by later tasks).
  - `AudienceDialog`: modal that calls `setAudience` and closes; controlled via `open`/`onClose` OR self-gated on first visit — this task uses a self-contained `<AudienceGate>` that renders the dialog when `audience` is null.

- [ ] **Step 1: Write the drafted content module**

Create `app/frontend/src/workbench/audience_content.ts`:

```ts
import {type Audience} from './audience_context';

// DRAFT copy for the audience modes. Edit freely — no logic depends on the
// wording, only on the exported shapes.

export const AUDIENCE_OPTIONS: {
  value: Audience;
  title: string;
  blurb: string;
}[] = [
  {
    value: 'google',
    title: 'Google AI Co-Scientist team',
    blurb: 'A note from the author and recommendations for the product.',
  },
  {
    value: 'sbi_ucd',
    title: 'SBI / UCD researcher',
    blurb: 'Early-access mode tailored to your lab and research.',
  },
  {
    value: 'general',
    title: 'General',
    blurb: 'The standard Co-Scientist workspace.',
  },
];

// DRAFT: personal message shown to the Google team in the header popover.
export const GOOGLE_MESSAGE =
  'Thank you for the AI Co-Scientist work that inspired this project. ' +
  'This is an independent replication built to study the architecture. ' +
  'I would love your feedback — see my recommendations for the product.';

// DRAFT: recommendations page copy (heading + bullet points).
export const GOOGLE_RECOMMENDATIONS: {heading: string; points: string[]} = {
  heading: 'Recommendations for the official Co-Scientist',
  points: [
    'Surface the tournament reasoning to end users, not just final ranks.',
    'Make literature-grounding failures visible instead of silent.',
    'Offer a lightweight express tier for fast iteration.',
  ],
};

// DRAFT: SBI/UCD early-access pilot guide shown in the header popover.
export const PILOT_GUIDE: {
  title: string;
  intro: string;
  tryThese: string[];
  limitations: string[];
} = {
  title: 'Early access',
  intro:
    'Welcome to the SBI/UCD pilot. Co-Scientist is tailored to your ' +
    'signalling and cancer-biology work.',
  tryThese: [
    'Ask for mechanistic hypotheses grounded in signalling networks.',
    'Request an experiment plan for a promising hypothesis.',
  ],
  limitations: [
    'Literature grounding is best-effort and may miss recent work.',
    'Runs can take several minutes at higher tiers.',
  ],
};

// DRAFT: feedback address for the pilot.
export const PILOT_FEEDBACK_EMAIL = 'guybarel2006@gmail.com';

// DRAFT: SBI/UCD-tailored home suggestions. Same shape as the default
// SUGGESTIONS in chat_home_stage.tsx.
export const SBI_SUGGESTIONS: readonly {
  preview: string;
  prompt: string;
  icon: 'search' | 'lightbulb' | 'stars';
}[] = [
  {
    preview: 'Propose a resistance mechanism to a MAPK-pathway inhibitor.',
    prompt:
      'A novel resistance mechanism to MAPK-pathway inhibition in cancer.\n\n' +
      'Develop a mechanistic hypothesis for how tumor cells acquire ' +
      'resistance to a MEK or ERK inhibitor through signalling-network ' +
      'rewiring. Explain the pathway-level mechanism and a phospho-signalling ' +
      'readout that would detect it.\n\n' +
      'Prioritize hypotheses testable with proteomic and perturbation ' +
      'assays common to a systems-biology lab.',
    icon: 'lightbulb',
  },
  {
    preview: 'Find a synthetic-lethal partner for a common oncogenic driver.',
    prompt:
      'A synthetic-lethal vulnerability for an oncogenic driver.\n\n' +
      'Identify a candidate synthetic-lethal gene or pathway for a common ' +
      'oncogenic driver (for example KRAS or PIK3CA), grounded in ' +
      'signalling-network biology. Describe the mechanism and a CRISPR or ' +
      'small-molecule perturbation screen to validate it.',
    icon: 'search',
  },
  {
    preview: 'Explain cell-to-cell signalling heterogeneity in a tumor.',
    prompt:
      'A mechanistic hypothesis for signalling heterogeneity in tumors.\n\n' +
      'Propose why genetically similar tumor cells show heterogeneous ' +
      'signalling-pathway activity, focusing on network-level feedback. ' +
      'Specify a single-cell measurement that would test the hypothesis.',
    icon: 'stars',
  },
];
```

- [ ] **Step 2: Write the failing test**

Create `app/frontend/src/workbench/components/audience_dialog.test.tsx`:

```tsx
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider} from '../audience_context';
import {AudienceGate} from './audience_dialog';

function renderGate() {
  return render(
    <AudienceProvider>
      <AudienceGate />
    </AudienceProvider>,
  );
}

describe('AudienceGate', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('shows the dialog when no audience is stored', () => {
    renderGate();
    expect(
      screen.getByRole('dialog', {name: /affiliation/i}),
    ).toBeInTheDocument();
  });

  it('hides the dialog after a choice and persists it', async () => {
    renderGate();
    await userEvent.click(
      screen.getByRole('button', {name: /SBI \/ UCD researcher/i}),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(window.localStorage.getItem('cosci-audience')).toBe('sbi_ucd');
  });

  it('does not show the dialog when an audience is already stored', () => {
    window.localStorage.setItem('cosci-audience', 'general');
    renderGate();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- audience_dialog`
Expected: FAIL — cannot resolve `./audience_dialog`.

- [ ] **Step 4: Implement `audience_dialog.tsx`**

Reuse the settings dialog's scrim/panel class names for a native look (inspect `settings_dialog.tsx` for the exact `ucs-settings-dialog-*` classes; the structure below mirrors it).

```tsx
import {type Audience, useAudience} from '../audience_context';
import {AUDIENCE_OPTIONS} from '../audience_content';

/**
 * Renders the affiliation modal. Controlled purely by props; the gate below
 * decides when to show it.
 *
 * @param props.onChoose Called with the picked audience.
 * @param props.dismissible When true, Escape / scrim click closes without a
 *   forced choice (used by the Settings re-open path); the first-visit gate
 *   passes false so a concrete value is always set.
 * @param props.onDismiss Called when a dismissible dialog is closed.
 */
export function AudienceDialog({
  onChoose,
  dismissible = false,
  onDismiss,
}: {
  onChoose: (a: Audience) => void;
  dismissible?: boolean;
  onDismiss?: () => void;
}) {
  return (
    <div className="ucs-settings-dialog-root">
      <div
        className="ucs-settings-dialog-scrim"
        onClick={dismissible ? onDismiss : undefined}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Choose your affiliation"
        className="ucs-settings-dialog-panel mx-auto grid max-w-md content-center gap-4 p-6"
      >
        <h2 className="text-2xl font-normal">Choose your affiliation</h2>
        <p className="text-cosci-muted">
          This tailors the workspace. You can change it later in Settings.
        </p>
        <div className="grid gap-3">
          {AUDIENCE_OPTIONS.map(option => (
            <button
              key={option.value}
              type="button"
              className="rounded-xl border border-cosci-border p-4 text-left hover:bg-cosci-hover"
              onClick={() => onChoose(option.value)}
            >
              <span className="block font-semibold">{option.title}</span>
              <span className="block text-cosci-muted">{option.blurb}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * First-visit gate: renders {@link AudienceDialog} until an audience is set.
 */
export function AudienceGate() {
  const {audience, setAudience} = useAudience();
  if (audience) return null;
  return <AudienceDialog onChoose={setAudience} />;
}
```

(If class names like `cosci-hover`/`cosci-border`/`cosci-muted` differ, use the tokens already present in `researcher_access.tsx` and `settings_dialog.tsx`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- audience_dialog`
Expected: PASS (3 tests).

- [ ] **Step 6: Mount the gate in the layout**

In `app/frontend/src/workbench/layout.tsx`, import `AudienceGate` and render it near the `SettingsDialog` block:

```tsx
import {AudienceGate} from './components/audience_dialog';
```

Add `<AudienceGate />` just before the closing tag of the outer layout `div` (sibling to the `settingsSection && <SettingsDialog .../>` block).

- [ ] **Step 7: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/audience_content.ts src/workbench/components/audience_dialog.tsx src/workbench/components/audience_dialog.test.tsx src/workbench/layout.tsx
git commit -m "feat(audience): add first-visit affiliation dialog"
```

---

## Task 7: Switch affiliation from Settings

**Files:**
- Modify: `app/frontend/src/workbench/components/settings_dialog.tsx`
- Test: extend `app/frontend/src/workbench/components/audience_dialog.test.tsx` or add a settings test.

**Interfaces:**
- Consumes: `AudienceDialog` (Task 6), `useAudience`.
- Produces: a new `'affiliation'` settings section that shows the three-way chooser inline.

- [ ] **Step 1: Write the failing test**

Add to `audience_dialog.test.tsx`:

```tsx
import {AffiliationSection} from './settings_dialog';

describe('AffiliationSection', () => {
  beforeEach(() => window.localStorage.clear());

  it('changes the stored audience when a new option is picked', async () => {
    window.localStorage.setItem('cosci-audience', 'general');
    render(
      <AudienceProvider>
        <AffiliationSection />
      </AudienceProvider>,
    );
    await userEvent.click(
      screen.getByRole('button', {name: /Google AI Co-Scientist team/i}),
    );
    expect(window.localStorage.getItem('cosci-audience')).toBe('google');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- audience_dialog`
Expected: FAIL — `AffiliationSection` is not exported from `settings_dialog`.

- [ ] **Step 3: Implement in `settings_dialog.tsx`**

Extend the `SettingsSection` union and `SETTINGS_SECTIONS` list:

```tsx
export type SettingsSection =
  | 'appearance'
  | 'model'
  | 'affiliation'
  | 'help';
```

```tsx
export const SETTINGS_SECTIONS: {
  section: SettingsSection;
  icon: IconName;
  label: string;
}[] = [
  {section: 'appearance', icon: 'palette', label: 'Appearance'},
  {section: 'model', icon: 'neurology', label: 'Model'},
  {section: 'affiliation', icon: 'group', label: 'Affiliation'},
  {section: 'help', icon: 'help', label: 'Help'},
];
```

Add the section component (reuses the option buttons via `AUDIENCE_OPTIONS`):

```tsx
import {useAudience} from '../audience_context';
import {AUDIENCE_OPTIONS} from '../audience_content';

/** Settings section letting the user change their declared affiliation. */
export function AffiliationSection() {
  const {audience, setAudience} = useAudience();
  return (
    <div className="grid gap-3">
      {AUDIENCE_OPTIONS.map(option => (
        <button
          key={option.value}
          type="button"
          aria-pressed={audience === option.value}
          className="rounded-xl border border-cosci-border p-4 text-left hover:bg-cosci-hover aria-pressed:border-cosci-primary"
          onClick={() => setAudience(option.value)}
        >
          <span className="block font-semibold">{option.title}</span>
          <span className="block text-cosci-muted">{option.blurb}</span>
        </button>
      ))}
    </div>
  );
}
```

Render `<AffiliationSection />` in the dialog body's section switch where `section === 'affiliation'` (match the existing appearance/model/help conditional rendering pattern in the file).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- audience_dialog`
Expected: PASS.

- [ ] **Step 5: Run the full settings/dialog tests (no regression)**

Run: `cd app/frontend && bun run test -- settings audience`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/components/settings_dialog.tsx src/workbench/components/audience_dialog.test.tsx
git commit -m "feat(settings): add affiliation switch section"
```

---

## Task 8: Audience-conditional header control

**Files:**
- Create: `app/frontend/src/workbench/layout_google_control.tsx`
- Create: `app/frontend/src/workbench/layout_pilot_control.tsx`
- Modify: `app/frontend/src/workbench/layout_header.tsx`
- Modify: `app/frontend/src/workbench/layout.tsx` (pass audience down, if not via hook)
- Test: `app/frontend/src/workbench/layout_header.test.tsx` (extend existing `layout.test.tsx` if header cases live there)

**Interfaces:**
- Consumes: `useAudience`, `GOOGLE_MESSAGE`, `PILOT_GUIDE`, `PILOT_FEEDBACK_EMAIL`, `GOOGLE_RECOMMENDATIONS` (heading link target `/recommendations`).
- Produces: `GoogleTeamControl`, `PilotControl`, each with the same `{open, onToggle, renderPopover}` contract `DiagnosticsControl` uses (minus `runId`).

- [ ] **Step 1: Write the failing test**

Create `app/frontend/src/workbench/layout_header.test.tsx`:

```tsx
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider} from './audience_context';
import {ShellHeader} from './layout_header';

function renderHeader() {
  return render(
    <MemoryRouter>
      <AudienceProvider>
        <ShellHeader
          navOpen={false}
          toggleNav={() => {}}
          startNewChat={() => {}}
          headerTitle=""
          activePanel={null}
          onTogglePanel={() => {}}
          logsControlRef={{current: null}}
        />
      </AudienceProvider>
    </MemoryRouter>,
  );
}

describe('ShellHeader audience control', () => {
  beforeEach(() => window.localStorage.clear());

  it('shows Logs for the general audience', () => {
    window.localStorage.setItem('cosci-audience', 'general');
    renderHeader();
    expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
  });

  it('shows the pilot control for sbi_ucd', () => {
    window.localStorage.setItem('cosci-audience', 'sbi_ucd');
    renderHeader();
    expect(
      screen.getByRole('button', {name: /Early access/i}),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /Logs/i})).toBeNull();
  });

  it('shows the team control for google', () => {
    window.localStorage.setItem('cosci-audience', 'google');
    renderHeader();
    expect(
      screen.getByRole('button', {name: /Team note/i}),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- layout_header`
Expected: FAIL — header always renders `DiagnosticsControl`; no "Early access"/"Team note" button.

- [ ] **Step 3: Implement the two controls**

Create `app/frontend/src/workbench/layout_pilot_control.tsx`:

```tsx
import {type ReactNode} from 'react';
import {Icon} from '@/components/icon';
import {PILOT_FEEDBACK_EMAIL, PILOT_GUIDE} from './audience_content';
import {tooltipClassNames} from './tooltip';

const BUTTON_CLASSES =
  'ucs-logs-button relative inline-flex h-[2.35rem] min-w-max ' +
  'cursor-pointer items-center gap-[0.45rem] rounded-full border-0 ' +
  'bg-cosci-logs-accent-bg px-[0.72rem] font-[inherit] text-[0.88rem] ' +
  'font-semibold whitespace-nowrap text-cosci-logs-accent-fg ' +
  'hover:bg-cosci-logs-accent-hover ' +
  '[&[aria-expanded=true]]:bg-cosci-logs-accent-hover';

/**
 * Header control replacing Logs for SBI/UCD: an early-access pilot guide.
 *
 * @param props.open Whether the popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Wraps the panel in the shell's positioned popover.
 */
export function PilotControl({
  open,
  onToggle,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  return (
    <>
      <button
        type="button"
        className={tooltipClassNames({className: BUTTON_CLASSES, placement: 'left'})}
        data-tooltip="Early access"
        aria-expanded={open}
        onClick={onToggle}
      >
        <Icon aria-hidden="true" className="text-[1.05rem]" name="science" />
        <span>Early access</span>
      </button>
      {open &&
        renderPopover(
          <div className="grid gap-3 p-4">
            <h2 className="text-base font-semibold">{PILOT_GUIDE.title}</h2>
            <p className="text-cosci-muted">{PILOT_GUIDE.intro}</p>
            <div>
              <h3 className="font-semibold">Try these</h3>
              <ul className="list-disc pl-5">
                {PILOT_GUIDE.tryThese.map(item => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="font-semibold">Known limitations</h3>
              <ul className="list-disc pl-5">
                {PILOT_GUIDE.limitations.map(item => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <a
              className="text-cosci-primary underline"
              href={`mailto:${PILOT_FEEDBACK_EMAIL}?subject=Co-Scientist%20pilot%20feedback`}
            >
              Send feedback
            </a>
          </div>,
          'ucs-popover--logs top-[calc(100%+0.45rem)] right-0 ' +
            '!w-[min(28rem,calc(100vw-2rem))] !p-0',
        )}
    </>
  );
}
```

Create `app/frontend/src/workbench/layout_google_control.tsx` (same shell; button label "Team note", panel shows `GOOGLE_MESSAGE` and a `<Link to="/recommendations">`):

```tsx
import {type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {Icon} from '@/components/icon';
import {GOOGLE_MESSAGE} from './audience_content';
import {tooltipClassNames} from './tooltip';

const BUTTON_CLASSES =
  'ucs-logs-button relative inline-flex h-[2.35rem] min-w-max ' +
  'cursor-pointer items-center gap-[0.45rem] rounded-full border-0 ' +
  'bg-cosci-logs-accent-bg px-[0.72rem] font-[inherit] text-[0.88rem] ' +
  'font-semibold whitespace-nowrap text-cosci-logs-accent-fg ' +
  'hover:bg-cosci-logs-accent-hover ' +
  '[&[aria-expanded=true]]:bg-cosci-logs-accent-hover';

/**
 * Header control replacing Logs for the Google team: a personal note and a
 * link to the recommendations page.
 *
 * @param props.open Whether the popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.renderPopover Wraps the panel in the shell's positioned popover.
 */
export function GoogleTeamControl({
  open,
  onToggle,
  renderPopover,
}: {
  open: boolean;
  onToggle: () => void;
  renderPopover: (children: ReactNode, className: string) => ReactNode;
}) {
  return (
    <>
      <button
        type="button"
        className={tooltipClassNames({className: BUTTON_CLASSES, placement: 'left'})}
        data-tooltip="Team note"
        aria-expanded={open}
        onClick={onToggle}
      >
        <Icon aria-hidden="true" className="text-[1.05rem]" name="waving_hand" />
        <span>Team note</span>
      </button>
      {open &&
        renderPopover(
          <div className="grid gap-3 p-4">
            <p>{GOOGLE_MESSAGE}</p>
            <Link className="text-cosci-primary underline" to="/recommendations">
              View recommendations
            </Link>
          </div>,
          'ucs-popover--logs top-[calc(100%+0.45rem)] right-0 ' +
            '!w-[min(28rem,calc(100vw-2rem))] !p-0',
        )}
    </>
  );
}
```

- [ ] **Step 4: Swap the control in `layout_header.tsx`**

Import `useAudience`, `GoogleTeamControl`, `PilotControl`. Replace the `<DiagnosticsControl .../>` element with a switch:

```tsx
import {useAudience} from './audience_context';
import {GoogleTeamControl} from './layout_google_control';
import {PilotControl} from './layout_pilot_control';
```

```tsx
        {(() => {
          const {audience} = useAudience();
          const renderPopover = (children: ReactNode, className: string) => (
            <ShellPopover className={className}>{children}</ShellPopover>
          );
          const open = activePanel === 'logs';
          const onToggle = () => onTogglePanel('logs');
          if (audience === 'google') {
            return (
              <GoogleTeamControl
                open={open}
                onToggle={onToggle}
                renderPopover={renderPopover}
              />
            );
          }
          if (audience === 'sbi_ucd') {
            return (
              <PilotControl
                open={open}
                onToggle={onToggle}
                renderPopover={renderPopover}
              />
            );
          }
          return (
            <DiagnosticsControl
              open={open}
              onToggle={onToggle}
              runId={activeRunId}
              renderPopover={renderPopover}
            />
          );
        })()}
```

Add the `ReactNode` type import if missing. (A hook inside an IIFE runs on every render unconditionally, so it is rules-of-hooks safe; if the linter objects to `useAudience` inside the IIFE, hoist `const {audience} = useAudience();` to the top of `ShellHeader` and keep only the branch selection in the render.) **Prefer hoisting** `const {audience} = useAudience();` to the top of the `ShellHeader` function body to satisfy the linter cleanly.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- layout_header`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the existing layout suite (no regression)**

Run: `cd app/frontend && bun run test -- layout`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/layout_google_control.tsx src/workbench/layout_pilot_control.tsx src/workbench/layout_header.tsx src/workbench/layout_header.test.tsx
git commit -m "feat(header): swap logs control per audience"
```

---

## Task 9: Recommendations page + route

**Files:**
- Create: `app/frontend/src/workbench/pages/recommendations_page.tsx`
- Modify: `app/frontend/src/workbench/workbench_app.tsx`
- Test: `app/frontend/src/workbench/pages/recommendations_page.test.tsx`

**Interfaces:**
- Consumes: `GOOGLE_RECOMMENDATIONS` (Task 6).
- Produces: `RecommendationsPage`; route `/recommendations`.

- [ ] **Step 1: Write the failing test**

```tsx
import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {RecommendationsPage} from './recommendations_page';

describe('RecommendationsPage', () => {
  it('renders the recommendations heading and points', () => {
    render(<RecommendationsPage />);
    expect(
      screen.getByRole('heading', {name: /Recommendations/i}),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- recommendations_page`
Expected: FAIL — cannot resolve module.

- [ ] **Step 3: Implement the page**

```tsx
import {GOOGLE_RECOMMENDATIONS} from '../audience_content';

/** Static recommendations page linked from the Google team header control. */
export function RecommendationsPage() {
  return (
    <main className="mx-auto grid w-[min(100%_-_2rem,44rem)] gap-6 py-12">
      <h1 className="font-gsans text-4xl font-normal">
        {GOOGLE_RECOMMENDATIONS.heading}
      </h1>
      <ul className="grid list-disc gap-3 pl-6 text-lg">
        {GOOGLE_RECOMMENDATIONS.points.map(point => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </main>
  );
}
```

- [ ] **Step 4: Add the route**

In `workbench_app.tsx`, import and add a route inside `<Routes>` (mirroring the `/access` route's `NoIndex` wrapper):

```tsx
import {RecommendationsPage} from './pages/recommendations_page';
```

```tsx
              <Route
                path="/recommendations"
                element={
                  <>
                    <NoIndex title="Recommendations" />
                    <RecommendationsPage />
                  </>
                }
              />
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- recommendations_page`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/pages/recommendations_page.tsx src/workbench/pages/recommendations_page.test.tsx src/workbench/workbench_app.tsx
git commit -m "feat(recommendations): add product recommendations page"
```

---

## Task 10: Audience-aware home suggestions

**Files:**
- Modify: `app/frontend/src/workbench/pages/chat_home_stage.tsx`
- Test: `app/frontend/src/workbench/pages/chat_home_stage.test.tsx` (create)

**Interfaces:**
- Consumes: `useAudience`, `SBI_SUGGESTIONS` (Task 6), existing `SUGGESTIONS`.
- Produces: home suggestions come from `SBI_SUGGESTIONS` for `sbi_ucd`, else the default `SUGGESTIONS`.

- [ ] **Step 1: Write the failing test**

```tsx
import {render, screen} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider} from '../audience_context';
import {activeSuggestions} from './chat_home_stage';

describe('activeSuggestions', () => {
  beforeEach(() => window.localStorage.clear());

  it('returns SBI suggestions for sbi_ucd', () => {
    expect(activeSuggestions('sbi_ucd')[0].preview).toMatch(/MAPK/i);
  });

  it('returns default suggestions otherwise', () => {
    expect(activeSuggestions('general')[0].preview).toMatch(/glioblastoma/i);
    expect(activeSuggestions(null)[0].preview).toMatch(/glioblastoma/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/frontend && bun run test -- chat_home_stage`
Expected: FAIL — `activeSuggestions` is not exported.

- [ ] **Step 3: Implement in `chat_home_stage.tsx`**

Add the import and a selector, and read audience in `HomeStage`:

```tsx
import {type Audience, useAudience} from '../audience_context';
import {SBI_SUGGESTIONS} from '../audience_content';
```

```tsx
/** Home suggestions for an audience: SBI's tailored set, else the default. */
export function activeSuggestions(
  audience: Audience | null,
): typeof SUGGESTIONS {
  return audience === 'sbi_ucd' ? SBI_SUGGESTIONS : SUGGESTIONS;
}
```

In `HomeStage`, call `const {audience} = useAudience();` and pass `activeSuggestions(audience)` into `HomeSuggestionRow` as a new `suggestions` prop; `HomeSuggestionRow` maps over the prop instead of the module-level `SUGGESTIONS`. (`SBI_SUGGESTIONS`'s element type matches `SUGGESTIONS`'s `{preview, prompt, icon}` — the `icon` union is a subset of `IconName`, so it is assignable.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- chat_home_stage`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd app/frontend && bun run fix && bun run lint
git add src/workbench/pages/chat_home_stage.tsx src/workbench/pages/chat_home_stage.test.tsx
git commit -m "feat(home): tailor suggestions for sbi_ucd audience"
```

---

## Task 11: Send audience on run creation

**Files:**
- Modify: `app/frontend/src/api/runs.ts` (`createRun`, `askRunQuestion`)
- Modify: `app/frontend/src/workbench/hooks/chat_session_start_run.ts`
- Test: extend an existing runs api test, or add a targeted assertion.

**Interfaces:**
- Consumes: `Audience` (Task 5).
- Produces: `createRun` and `askRunQuestion` accept an optional `audience`.

- [ ] **Step 1: Add `audience` to the API signatures**

In `app/frontend/src/api/runs.ts`, add `audience?: 'general' | 'google' | 'sbi_ucd';` to the `createRun` input object type (it is passed through in the request body as-is by `fetchJson('/api/runs', jsonRequest(input, true))`). Add an optional `audience` param to `askRunQuestion` and include it in the body:

```ts
export async function askRunQuestion(
  id: string,
  question: string,
  audience?: 'general' | 'google' | 'sbi_ucd',
): Promise<string> {
  const res = await fetch(
    `${API_BASE_URL}/api/runs/${id}/messages/ask`,
    jsonRequest({question, audience}, true),
  );
  // ...unchanged...
}
```

- [ ] **Step 2: Thread audience from the start-run call site**

`chat_session_start_run.ts`'s `executeStart` runs outside React (it takes deps as args), so read the audience where the handler is wired and pass it through `ExecuteStartDeps`. Simplest correct approach: read `cosci-audience` from localStorage at the create call, since the context already persists there.

Add a tiny helper import or inline read in `executeStart` and include it in the `createRun` payload:

```ts
import {type Audience} from '../audience_context';

function storedAudience(): Audience | undefined {
  const value = window.localStorage.getItem('cosci-audience');
  return value === 'general' || value === 'google' || value === 'sbi_ucd'
    ? value
    : undefined;
}
```

```ts
  const created = await createRun({
    research_goal: specToStart.goal,
    interview_id: specToStart.interviewId,
    requirements: specToStart.requirements,
    attributes: specToStart.attributes,
    criteria: specToStart.criteria,
    focus: specToStart.focus,
    tier: specToStart.tier,
    notify_on_completion: Boolean(specToStart.notifyOnCompletion),
    completion_email: specToStart.notifyOnCompletion
      ? specToStart.completionEmail
      : undefined,
    enable_literature_review: pubmedEnabled,
    audience: storedAudience(),
  });
```

- [ ] **Step 3: Write/adjust a test**

Add `app/frontend/src/workbench/hooks/chat_session_start_run.test.ts` (or extend an existing one) that mocks `@/api/runs` `createRun` and asserts the audience is forwarded:

```ts
import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('@/api/runs', () => ({
  createRun: vi.fn(async () => ({id: 'r1'})),
  startRun: vi.fn(async () => {}),
  uploadRunDocument: vi.fn(async () => {}),
}));

// Import after the mock is registered.
import {createRun} from '@/api/runs';
import {promoteDraftToRun} from './chat_session_start_run';

describe('start run forwards audience', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('sends the stored audience on createRun', async () => {
    window.localStorage.setItem('cosci-audience', 'sbi_ucd');
    await promoteDraftToRun({
      draft: {
        spec: {goal: 'g', requirements: [], attributes: [], criteria: []},
        createdAt: 0,
      },
      pubmedEnabled: false,
      reloadHistory: async () => {},
      setIsStarting: () => {},
      setError: () => {},
      setToast: () => {},
      setConfirmed: () => {},
      setDraft: () => {},
      setMessages: () => {},
      setStartedSession: () => {},
      pendingAttachments: [],
      setPendingAttachments: () => {},
    } as never);
    expect(vi.mocked(createRun).mock.calls[0][0].audience).toBe('sbi_ucd');
  });
});
```

(Adjust the `draft.spec` shape to the real `DraftSpec`/`HandlerDeps` types in `chat_session_types.ts`; the `as never` cast keeps the test focused on the audience assertion without reconstructing every dep type. If the real types are cheap to satisfy, prefer satisfying them over the cast.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/frontend && bun run test -- chat_session_start_run`
Expected: PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
cd app/frontend && bun run fix && bun run lint && bun run build
git add src/api/runs.ts src/workbench/hooks/chat_session_start_run.ts src/workbench/hooks/chat_session_start_run.test.ts
git commit -m "feat(runs): forward selected audience on run creation"
```

---

## Task 12: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend tests + typecheck**

Run: `cd app && .venv/bin/python -m pytest -q && mypy .`
Expected: PASS, mypy clean.

- [ ] **Step 2: Frontend tests + build**

Run: `cd app/frontend && bun run test && bun run build`
Expected: All tests pass; `tsc && vite build` succeeds.

- [ ] **Step 3: Manual smoke via the run skill**

Start the app (`make start` from repo root per the run-app-locally memory; run the backend from the main checkout, not this worktree, since worktrees lack the gitignored `.env`/`.venv`). Verify:
- First load shows the affiliation dialog; picking General dismisses it and shows Logs.
- Switching to SBI/UCD in Settings swaps the header to "Early access" and changes the three home suggestions.
- Switching to Google swaps the header to "Team note"; its popover links to `/recommendations`.
- Reload preserves the choice (localStorage).

- [ ] **Step 4: Final commit if smoke revealed fixes**

Commit any fixes with an appropriate `fix(...)` message.

---

## Self-Review Notes

- **Spec coverage:** audience model (T5), popup (T6), settings switch (T7), header swap google/sbi/general (T8), recommendations page (T9), run planning injection (T2, T3), chat Q&A injection (T4), home suggestions (T10), content files (T1, T6), provenance persistence (T3), testing (each task + T12). Error handling: missing content file → `""` (T1 loader), corrupt localStorage → null (T5), old runs without audience → general (T2/T3 omit key).
- **Behavioral guard:** `general`/`google` never load context (T1 returns `""`; T3/T4 verified by "no context" tests), so their runs resolve identically to today.
- **Type consistency:** `Audience` union identical across `audience_context.tsx`, `audience_content.ts`, api and hook signatures; backend `AUDIENCE_PATTERN`/`VALID_AUDIENCES` single-sourced in `audience.py`; `build_system_prompt` and `setup_config` gain `audience_context: str = ""` consistently.
