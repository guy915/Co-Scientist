# Google repo conventions — design

**Date:** 2026-06-13
**Status:** Approved
**Goal:** Make the whole repository and codebase read like it came out of the
google-deepmind GitHub org, the same way the frontend UI is already
indistinguishable from an official Google product.

## Scope and anchor

Anchor on **google-deepmind org conventions**. The primary source is the real
DeepMind repo vendored at `references/antigravity-science-skills/` — copy its
wording, markdown list style, and license footer verbatim where applicable.
Where it is silent, fall back to Google's published style guides
(`google/styleguide`) and standard Google OSS templates.

**Non-goals:**

-   Bazel BUILD files, absl flags/logging, pytype (deferred "full cosplay"
    tier).
-   Rewriting git history.
-   Any false identity claim. Copyright is attributed to "The Co-Scientist
    Authors" (the Google/DeepMind multi-contributor form — e.g. "The AlphaFold
    Authors"), which is both authentic-looking and factually accurate. The
    README ends with the canonical disclaimer: "This is not an official Google
    product."

**Process constraints:**

-   All work happens on `main`.
-   No AI tools mentioned in commits, PRs, or pushes (per AGENTS.md git
    hygiene).

## 1. Repo furniture

### LICENSE

Replace the MIT `LICENSE` with the full Apache-2.0 text, byte-for-byte from
`references/antigravity-science-skills/LICENSE`.

### README (hybrid restructure)

Keep the visual identity, adopt the DeepMind ritual structure:

-   **Keep:** hero table (pipeline SVG + workbench screenshot), feature grid.
-   **Strip:** emojis (🏆🛡️📚 etc.), marketing tone ("Not a chatbot. Not a
    summariser."), decorative badge colors.
-   **Badges:** trim to a utilitarian pair — tests and license (now
    Apache-2.0).
-   **Section order:** overview → features → installation → usage →
    architecture → "Citing this work" → license.
-   **"Citing this work":** BibTeX block (DeepMind staple).
-   **License footer:** copy the reference repo's wording — "All software is
    licensed under the Apache License, Version 2.0 …; all other materials are
    licensed under the Creative Commons Attribution 4.0 International License
    (CC-BY)" — ending with the line: *This is not an official Google product.*

### CITATION.cff

Add at repo root so GitHub renders the "Cite this repository" button. Fields:
title "AI Co-Scientist", author Guy Barel, year 2026, repository URL,
license Apache-2.0. Keep consistent with the README BibTeX.

### CONTRIBUTING.md

Add at repo root from Google's standard OSS template: CLA-style paragraph,
code-review process (all submissions via GitHub pull requests), community
guidelines reference. Fold in the existing engine style rules (capitalized
docstrings, lowercase `logger.debug` messages, no emojis or unicode decoration
in code/logs, Rich only in `examples/` and `dev/`) — these are already
Google-compatible.

### .github/

-   `CODEOWNERS`: `* @guy915`.
-   Issue templates: bug report and feature request, in Google's dry house
    style.
-   No CI exists today; nothing to migrate.

### AGENTS.md / CLAUDE.md

Update all documented commands and style conventions to match the new
toolchain (sections 3–4 below).

## 2. Apache headers on source files

Add the standard Apache 2.0 comment block to the top of every source file:

```
Copyright 2026 The Co-Scientist Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

-   **Python** (`#` comments): `engine/src/`, `engine/dev/`,
    `engine/examples/`, `engine/mcp_server/`, `app/app/`, `app/tests/`.
-   **TypeScript** (`/** … */`): `app/frontend/src/` (`.ts`, `.tsx`).
-   **Excluded:** config files, generated files, markdown, YAML, JSON, CSS,
    SVG.

Header goes above the module docstring (Python) or first import (TS), below
any shebang line.

## 3. Python style — engine, app, mcp_server

-   **Formatter:** black → **yapf**, `based_on_style = google`,
    `column_limit = 80`. Current line lengths are 100 (engine, app) and 88
    (mcp_server), so this is a large mechanical reformat.
-   **Linter:** ruff → **pylint** with Google's published `pylintrc` from
    `google/styleguide`.
-   **Type checker:** mypy stays.
-   **Docstrings:** Google format — one-line summary, then `Args:` /
    `Returns:` / `Raises:`. Enforced via pylint docstring checks. Existing
    multi-line summary docstrings are converted.
-   **Configs updated:** `engine/pyproject.toml`, `app/pyproject.toml`,
    `engine/mcp_server/pyproject.toml` (`[tool.black]`/`[tool.ruff]` →
    `[tool.yapf]` + `pylintrc`), dev dependencies, `app/Makefile`, pixi tasks.

## 4. TypeScript style — frontend

-   **Biome → gts** (Google TypeScript Style: ESLint + Google's Prettier
    config).
-   `package.json` scripts remapped to gts equivalents (`lint`, `fix`,
    `check`, `clean`); Biome config and dependency removed.
-   One mechanical reformat commit. React/JSX is supported under gts.

## 5. Docs style

ARCHITECTURE.md, FIDELITY.md, and README prose follow the Google
developer-documentation style as observed in the reference repo:

-   Sentence-case headings.
-   Second person, present tense.
-   80-column hard wrap.
-   `-` bullets with 4-space continuation indent.

## 6. Rollout order

Each phase is its own commit on `main`; tests run between phases.

1.  Repo furniture + README (zero code risk).
2.  Apache headers on all source files.
3.  Python toolchain swap + reformat, one package at a time (engine, app,
    mcp_server), `pytest` after each.
4.  Frontend gts swap + reformat; verify with `bun run build`.
5.  Docs restyle (ARCHITECTURE.md, FIDELITY.md).

## Verification

-   `app/`: `make test` (59 tests) passes after each Python phase.
-   `engine/`: `pytest` exits clean (no committed tests); `python
    examples/run.py` still imports and starts.
-   Frontend: `tsc && vite build` succeeds; gts `lint` passes.
-   Visual check: README renders correctly on GitHub (hero table, citation
    section, footer).
