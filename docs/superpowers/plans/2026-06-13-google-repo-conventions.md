# Google Repo Conventions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the whole repository read like a google-deepmind org project: Apache-2.0 licensing with per-file headers, DeepMind repo furniture (CITATION, CONTRIBUTING, .github, README ritual), Google Python style (yapf + pylint + Google docstrings), Google TypeScript style (gts), and Google docs style.

**Architecture:** Pure conventions migration — no behavior changes. Five phases, each its own commit on `main`, with the existing test suites as the safety net (app: 59 tests; engine: no committed tests; frontend: `tsc && vite build`). The vendored real DeepMind repo at `references/antigravity-science-skills/` is the source of truth for wording.

**Tech Stack:** Apache-2.0, CITATION.cff, yapf (`based_on_style=google`), pylint with Google's published `pylintrc`, mypy (unchanged), gts v7 (ESLint flat config + Google Prettier config), Bun, GNU make, pixi.

**Spec:** `docs/superpowers/specs/2026-06-13-google-repo-conventions-design.md`

**Constraints (apply to every task):**

- Work directly on `main`.
- Commit messages read as human-written. Never mention AI tools. No
  `Co-Authored-By` trailers, no "Generated with" lines.
- Copyright owner is "The Co-Scientist Authors" everywhere except
  CITATION.cff, which cites Guy Barel by name.

---

## Reference blocks used by multiple tasks

**Apache header — Python files** (referred to below as PY_HEADER):

```python
# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

**Apache header — TypeScript files** (referred to below as TS_HEADER):

```typescript
/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
```

**Google docstring rules** (used in Tasks 7–9):

1. The summary starts on the same line as the opening `"""`, is one line,
   descriptive third person ("Fetches…", "Runs…", not "Fetch…"), and ends
   with a period.
2. A blank line separates the summary from any further prose.
3. Parameter/return/exception documentation uses Google sections, each entry
   indented 4 spaces:

   ```python
   def run(self, goal: str, max_iterations: int = 3) -> dict:
       """Runs the full hypothesis-generation pipeline.

       Args:
           goal: The research goal to generate hypotheses for.
           max_iterations: Maximum number of evolve/rank iterations.

       Returns:
           The final workflow state as a dictionary.

       Raises:
           ValueError: If goal is empty.
       """
   ```

4. The most common existing offense is the summary on its own line. Real
   example from `engine/src/co_scientist/generator.py` — before:

   ```python
   """
   Main HypothesisGenerator class.

   Provides an interface inspired by the original AI-CoScientist integration,
   but uses LangGraph under the hood.
   ```

   after:

   ```python
   """Main HypothesisGenerator class.

   Provides an interface inspired by the original AI-CoScientist integration,
   but uses LangGraph under the hood.
   ```

**Docstring checker** (used in Tasks 7–9). Lists docstrings whose summary is
not on the first line or doesn't end with terminal punctuation; review every
hit, fix per the rules above (the punctuation heuristic has rare false
positives — use judgment):

```bash
python3 - DIRS... <<'EOF'
import ast, pathlib, sys
bad = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob("*.py")):
        tree = ast.parse(p.read_text())
        nodes = [tree] + [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for node in nodes:
            doc = ast.get_docstring(node, clean=False)
            if doc and (doc.startswith("\n")
                        or not doc.split("\n")[0].rstrip().endswith((".", "?", "!", ":"))):
                print(f"{p}:{getattr(node, 'lineno', 1)} {getattr(node, 'name', '<module>')}")
                bad += 1
print(f"{bad} docstrings to review")
EOF
```

(Replace `DIRS...` with the package directories named in each task.)

---

### Task 1: Apache-2.0 license

**Files:**
- Modify: `LICENSE` (replace MIT text entirely)
- Modify: `engine/pyproject.toml:11` (license field), `:13-19` (classifiers)
- Modify: `app/pyproject.toml` (add license field after line 9)
- Modify: `engine/mcp_server/pyproject.toml:11` (license field), `:13-17` (classifiers)

- [ ] **Step 1: Replace LICENSE with the Apache-2.0 text from the vendored DeepMind repo**

```bash
cp references/antigravity-science-skills/LICENSE LICENSE
head -3 LICENSE
```

Expected: first lines contain "Apache License" / "Version 2.0, January 2004".

- [ ] **Step 2: Fix engine license metadata**

In `engine/pyproject.toml`, replace `license = {file = "LICENSE"}` (line 11 —
note: this currently points at a file that does not exist in `engine/`; this
fixes that wart too) with:

```toml
license = {text = "Apache-2.0"}
```

and add to the `classifiers` list:

```toml
    "License :: OSI Approved :: Apache Software License",
```

- [ ] **Step 3: Add app license metadata**

In `app/pyproject.toml`, after `requires-python = ">=3.10"` (line 9), add:

```toml
license = {text = "Apache-2.0"}
```

- [ ] **Step 4: Fix mcp_server license metadata**

In `engine/mcp_server/pyproject.toml`, replace
`license = {text = "Proprietary"}` (line 11) with:

```toml
license = {text = "Apache-2.0"}
```

and add to the `classifiers` list:

```toml
    "License :: OSI Approved :: Apache Software License",
```

- [ ] **Step 5: Verify the three pyprojects still parse**

```bash
python3 -c "import tomllib,pathlib;[tomllib.loads(pathlib.Path(p).read_text()) and print(p,'ok') for p in ['engine/pyproject.toml','app/pyproject.toml','engine/mcp_server/pyproject.toml']]"
```

Expected: three `ok` lines.

- [ ] **Step 6: Commit**

```bash
git add LICENSE engine/pyproject.toml app/pyproject.toml engine/mcp_server/pyproject.toml
git commit -m "Relicense under Apache 2.0"
```

---

### Task 2: Citation metadata

**Files:**
- Create: `CITATION.cff`

- [ ] **Step 1: Create CITATION.cff**

```yaml
cff-version: 1.2.0
message: If you use this software, please cite it using these metadata.
title: "AI Co-Scientist: A multi-agent hypothesis-generation workbench"
authors:
  - family-names: Barel
    given-names: Guy
repository-code: "https://github.com/guy915/Co-Scientist"
license: Apache-2.0
date-released: "2026-06-13"
```

- [ ] **Step 2: Validate it is parseable YAML**

```bash
python3 -c "import yaml;print(yaml.safe_load(open('CITATION.cff'))['title'])"
```

Expected: the title string. (If pyyaml is unavailable in the system python,
run via `.venv/bin/python`.)

- [ ] **Step 3: Commit**

```bash
git add CITATION.cff
git commit -m "Add citation metadata"
```

---

### Task 3: Contributing guide

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Create CONTRIBUTING.md** (Google OSS template structure,
  adapted: no Google CLA link — contributions are accepted under the project
  license instead)

```markdown
# How to contribute

We would love to accept your patches and contributions to this project.

## Before you begin

### Review our community guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

### License

By contributing, you agree that your contributions will be licensed under the
Apache License, Version 2.0, the same license that covers the project. New
source files must start with the Apache 2.0 header used throughout the
repository (copyright "The Co-Scientist Authors").

## Contribution process

### Code reviews

All submissions, including submissions by project members, require review. We
use [GitHub pull requests](https://docs.github.com/articles/about-pull-requests)
for this purpose.

### Style

-   Python code follows the
    [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
    Format with `yapf` (`based_on_style = google`, 80 columns) and lint with
    `pylint` using the repository `pylintrc`.
-   Docstrings are Google style: a one-line summary on the first line, ending
    with a period, followed by `Args:`, `Returns:`, and `Raises:` sections as
    applicable.
-   TypeScript code follows the
    [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html),
    enforced with [gts](https://github.com/google/gts).
-   `logger.debug()` messages are lowercase; `info`, `warning`, and `error`
    messages are capitalized full sentences.
-   No emojis or unicode decoration in code or logs.
-   The Rich library is used only in `engine/examples/` and `engine/dev/`,
    never in core library code.
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "Add contributing guide"
```

---

### Task 4: GitHub repo metadata

**Files:**
- Create: `.github/CODEOWNERS`
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`

- [ ] **Step 1: Create `.github/CODEOWNERS`**

```
* @guy915
```

- [ ] **Step 2: Create `.github/ISSUE_TEMPLATE/bug_report.md`**

```markdown
---
name: Bug report
about: Report a problem with the engine, API, or workbench UI
labels: bug
---

**Describe the bug**

A clear and concise description of what the bug is.

**To reproduce**

Steps to reproduce the behavior.

**Expected behavior**

What you expected to happen.

**Environment**

-   OS:
-   Python version:
-   Browser (for UI issues):

**Additional context**

Logs, screenshots, or `/status` output.
```

- [ ] **Step 3: Create `.github/ISSUE_TEMPLATE/feature_request.md`**

```markdown
---
name: Feature request
about: Suggest an improvement to the engine, API, or workbench UI
labels: enhancement
---

**Problem**

A clear and concise description of the problem this feature would solve.

**Proposed solution**

What you would like to happen.

**Alternatives considered**

Other approaches you have considered, if any.

**Additional context**

Anything else that helps explain the request.
```

- [ ] **Step 4: Commit**

```bash
git add .github
git commit -m "Add CODEOWNERS and issue templates"
```

---

### Task 5: README restructure (hybrid)

**Files:**
- Modify: `README.md` (full rewrite — content below)

- [ ] **Step 1: Replace README.md with exactly this content**

````markdown
<h1 align="center">AI Co-Scientist</h1>

<p align="center">
  A locally runnable, multi-agent hypothesis-generation workbench, based on
  the AI Co-Scientist system published by Google DeepMind.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-59_passing-brightgreen" alt="Tests"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue" alt="License"/></a>
</p>

<table align="center">
<tr>
<td align="center"><strong>Pipeline architecture</strong></td>
<td align="center"><strong>Workbench UI</strong></td>
</tr>
<tr>
<td><img src="docs/pipeline.svg" alt="Multi-agent hypothesis pipeline" width="440"/></td>
<td><img src="docs/screenshots/chat.png" alt="Co-Scientist workbench" width="440"/></td>
</tr>
</table>

## Overview

AI Co-Scientist generates, reviews, ranks, and evolves research hypotheses
with a LangGraph multi-agent pipeline and streams every step into a web
workbench. The implementation preserves the core invariants of the published
system: 11 agent-equivalent pipeline steps, Elo-1200 starting scores,
append-only evolution lineage, four-state citation classification, and dual
safety gates. See [`docs/FIDELITY.md`](docs/FIDELITY.md) for the full
invariant list with paper sources.

The system is deliberately not a chat wrapper over papers, an autonomous
wet-lab executor, a medical or regulatory decision system, or a multi-tenant
SaaS. It is a local-first research tool.

## Features

<table>
<tr>
<td width="33%" valign="top">

**Elo tournament**<br/>
<sub>Pairwise ranking with the standard Elo formula. K-factor
configurable.</sub>

</td>
<td width="33%" valign="top">

**Dual safety gates**<br/>
<sub>Intake and final-output safety screening. Blocks weaponisation
patterns.</sub>

</td>
<td width="33%" valign="top">

**Citation audit**<br/>
<sub>Four-state classification: verified, partial, unsupported,
unavailable.</sub>

</td>
</tr>
<tr>
<td valign="top">

**Mock mode**<br/>
<sub>Full pipeline without an LLM key. Deterministic, free, instant.</sub>

</td>
<td valign="top">

**Evolution lineage**<br/>
<sub>Append-only: evolved hypotheses are new rows with <code>parent_id</code>
tracing to gen-0.</sub>

</td>
<td valign="top">

**Scientist-in-the-loop**<br/>
<sub>Chat tab with auto-steering, manual steering, and QA modes.</sub>

</td>
</tr>
</table>

## Installation

```bash
make setup          # Python venv + frontend deps
make dev            # API on :8008, UI on :5173
open http://localhost:5173
```

Run `make help` for all targets. See [`.env.example`](.env.example) for
configuration.

## Usage

Click **New run**, type a research goal, pick Standard or Advanced, and hit
**Start**. The pipeline streams live across six tabs:

| Tab | Shows |
| --- | --- |
| **Overview** | Live pipeline timeline with progress bar and event counters |
| **Ideas** | Ranked hypotheses by Elo. Click any row for the detail modal: statement, mechanism, experimental design, lineage |
| **Evidence** | Retrieved sources with abstracts, links, and 4-state citation classification |
| **Tournament** | Leaderboard + per-iteration matchup log with Elo deltas and judge rationale |
| **Report** | Server-generated Markdown report with download buttons (MD / JSON) and safety verdict |
| **Chat** | Scientist-in-the-loop steering: auto, manual, and QA conversation modes |

### Mock mode vs real engine

The system reports its mode at `/status`:

| | Mock mode | Real engine |
| - | - | - |
| **Trigger** | No LLM key in `.env` | Any provider key set (`GEMINI_API_KEY`, `OPENAI_API_KEY`, …) |
| **Behaviour** | Deterministic seed → 11 agent steps, stable hypotheses and Elo | LangGraph engine, real LLM calls |
| **Cost** | Free | Provider billing applies |

Force mock mode for development with `COSCIENTIST_FORCE_MOCK=1`. Check the
current mode with `curl localhost:8008/status | jq .mock_mode`.

### Environment

Copy `.env.example` to `.env`. Empty keys keep you in mock mode.

```
GEMINI_API_KEY=                      # empty = mock mode; any key triggers real engine
MODEL_NAME=deepseek/deepseek-chat    # LiteLLM format
COSCIENTIST_DB_PATH=./coscientist.db
SAFETY_MODE=standard                 # 'strict' for dual-use filtering
```

See [`.env.example`](.env.example) for the full variable list (CORS, Elo
tuning, MCP, cache).

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="System architecture" width="600"/>
</p>

Full diagrams and module map in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Acknowledgements

This project is based on
[AI Co-Scientist](https://research.google/blog/accelerating-scientific-discovery-with-ai-co-scientist/)
by Google DeepMind. See [`references/`](references/) for the original
research papers and product analysis.

## Citing this work

If you use this software in your research, please cite:

```bibtex
@software{barel2026coscientist,
  author = {Barel, Guy},
  title = {AI Co-Scientist: A multi-agent hypothesis-generation workbench},
  year = {2026},
  url = {https://github.com/guy915/Co-Scientist}
}
```

## License and disclaimer

Copyright 2026 The Co-Scientist Authors.

All software is licensed under the Apache License, Version 2.0 (Apache 2.0);
you may not use this file except in compliance with the Apache 2.0 license.
You may obtain a copy of the Apache 2.0 license at:
https://www.apache.org/licenses/LICENSE-2.0

All other materials are licensed under the Creative Commons Attribution 4.0
International License (CC-BY). You may obtain a copy of the CC-BY license at:
https://creativecommons.org/licenses/by/4.0/legalcode

Unless required by applicable law or agreed to in writing, all software and
materials distributed here under the Apache 2.0 or CC-BY licenses are
distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied. See the licenses for the specific language
governing permissions and limitations under those licenses.

This is not an official Google product.
````

- [ ] **Step 2: Sanity-check rendering locally**

```bash
grep -c '🏆\|🛡️\|📚\|🧪\|🧬\|💬' README.md || echo "no emojis"
grep -n "not an official Google product" README.md
```

Expected: "no emojis" and one hit for the disclaimer line.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Restructure README with citation and license sections"
```

---

### Task 6: Apache headers on all source files

**Files:**
- Create: `scripts/add_license_headers.py`
- Modify: every `.py` under `engine/src`, `engine/dev`, `engine/examples`,
  `engine/mcp_server`, `app/app`, `app/tests` (~87 files) and every
  `.ts`/`.tsx` under `app/frontend/src` (~40 files)

- [ ] **Step 1: Create `scripts/add_license_headers.py`**

```python
# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Adds the Apache 2.0 license header to source files that lack one."""

import sys
from pathlib import Path

HEADER_LINES = [
    "Copyright 2026 The Co-Scientist Authors",
    "",
    'Licensed under the Apache License, Version 2.0 (the "License");',
    "you may not use this file except in compliance with the License.",
    "You may obtain a copy of the License at",
    "",
    "    http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    'distributed under the License is distributed on an "AS IS" BASIS,',
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "See the License for the specific language governing permissions and",
    "limitations under the License.",
]

PY_HEADER = "\n".join(f"# {l}".rstrip() for l in HEADER_LINES) + "\n\n"
TS_HEADER = ("/**\n" + "\n".join(f" * {l}".rstrip() for l in HEADER_LINES) +
             "\n */\n\n")


def add_header(path: Path) -> bool:
    """Prepends the license header to one file.

    Args:
        path: The source file to update.

    Returns:
        True if the file was modified, False if it already had a header.
    """
    text = path.read_text()
    if "Licensed under the Apache License" in text[:1024]:
        return False
    if path.suffix == ".py":
        if text.startswith("#!"):
            shebang, _, rest = text.partition("\n")
            path.write_text(shebang + "\n" + PY_HEADER + rest)
        else:
            path.write_text(PY_HEADER + text)
    else:
        path.write_text(TS_HEADER + text)
    return True


def main() -> None:
    """Walks the directories given on argv and adds missing headers."""
    changed = 0
    for root in sys.argv[1:]:
        for pattern in ("*.py", "*.ts", "*.tsx"):
            for path in sorted(Path(root).rglob(pattern)):
                if add_header(path):
                    changed += 1
                    print(f"added: {path}")
    print(f"{changed} files updated")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
python3 scripts/add_license_headers.py \
  engine/src engine/dev engine/examples engine/mcp_server \
  app/app app/tests app/frontend/src
```

Expected: roughly "127 files updated" (87 py + 40 ts; the exact count may
drift a few files).

- [ ] **Step 3: Verify nothing broke**

```bash
python3 -m compileall -q engine/src engine/dev engine/examples engine/mcp_server app/app app/tests && echo PY-OK
cd app/frontend && bun run build && cd ../..
```

Expected: `PY-OK` and a successful vite build.

- [ ] **Step 4: Run the app test suite**

```bash
make test
```

Expected: 59 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts engine/src engine/dev engine/examples engine/mcp_server app/app app/tests app/frontend/src
git commit -m "Add Apache license headers to source files"
```

---

### Task 7: Engine — Google Python toolchain

**Files:**
- Create: `pylintrc` (repo root, downloaded)
- Modify: `engine/pyproject.toml:33-41` (dev deps), `:54-60` (tool sections)
- Modify: docstrings across `engine/src/`, `engine/dev/`, `engine/examples/`

- [ ] **Step 1: Download Google's pylintrc to the repo root**

```bash
curl -fsSL https://raw.githubusercontent.com/google/styleguide/gh-pages/pylintrc -o pylintrc
head -5 pylintrc
```

Expected: the Google styleguide pylintrc banner comment.

- [ ] **Step 2: Swap engine dev dependencies**

In `engine/pyproject.toml`, in `[project.optional-dependencies] dev`, replace
the lines

```toml
    "black~=25.12.0",
    "ruff~=0.14.11",
```

with

```toml
    "yapf~=0.43.0",
    "pylint~=3.3",
```

- [ ] **Step 3: Swap engine tool config**

In `engine/pyproject.toml`, replace

```toml
[tool.black]
line-length = 100
target-version = ["py310"]

[tool.ruff]
line-length = 100
target-version = "py310"
```

with

```toml
[tool.yapf]
based_on_style = "google"
column_limit = 80
```

- [ ] **Step 4: Install and reformat**

```bash
.venv/bin/pip install 'yapf~=0.43.0' 'pylint~=3.3'
cd engine && ../.venv/bin/yapf -ir src dev examples && cd ..
git -C . diff --stat engine | tail -1
```

Expected: a large mechanical diff (most engine files, 100→80 columns).

- [ ] **Step 5: First pylint run; prune incompatible rcfile options**

```bash
cd engine && ../.venv/bin/pylint --rcfile=../pylintrc src/co_scientist | tail -20 && cd ..
```

Google's pylintrc targets pylint 2.x. If pylint 3 reports
`unrecognized-option` or `unknown-option-value` (E0015/W0012) for specific
entries, delete those entries from `pylintrc` and re-run until the rcfile
itself loads silently. Codebase findings remain at this point — that is the
next step.

- [ ] **Step 6: Fix pylint findings**

Fix all error-category (`E....`) messages by correcting the code. For
warning/convention messages, fix them where mechanical (unused imports,
naming, line length missed by yapf); where a fix would change behavior or
churn an API, add a targeted
`# pylint: disable=<rule>` comment on the offending line instead. Re-run
until:

```bash
cd engine && ../.venv/bin/pylint --rcfile=../pylintrc src/co_scientist dev examples; cd ..
```

exits with score output and no `E` messages.

- [ ] **Step 7: Convert docstrings to Google style**

Run the docstring checker from the reference section with dirs
`engine/src engine/dev engine/examples`, and fix every hit using the
Google docstring rules. Re-run until the count is 0 (or only deliberate
false positives remain).

- [ ] **Step 8: Verify the engine still imports and tests pass**

```bash
.venv/bin/python -c "from co_scientist.generator import HypothesisGenerator; print('import ok')"
cd engine && ../.venv/bin/python -m pytest -q && cd ..
make test
```

Expected: `import ok`; engine pytest exits clean (no committed tests); app
suite 59 passed (the app imports the engine, so this catches regressions).

- [ ] **Step 9: Commit**

```bash
git add pylintrc engine
git commit -m "Adopt Google Python style in engine (yapf, pylint, docstrings)"
```

---

### Task 8: App backend — Google Python toolchain

**Files:**
- Modify: `app/pyproject.toml:20-28` (dev deps), `:41-47` (pixi tasks),
  `:58-66` (tool sections)
- Modify: `app/Makefile:16-22`
- Modify: docstrings across `app/app/`, `app/tests/`

- [ ] **Step 1: Swap app dev dependencies**

In `app/pyproject.toml` dev extras, replace

```toml
    "black>=23.0.0",
    "ruff>=0.1.0",
```

with

```toml
    "yapf>=0.43.0",
    "pylint>=3.3",
```

- [ ] **Step 2: Swap app tool config**

Replace

```toml
[tool.black]
line-length = 100
target-version = ["py310"]

[tool.ruff]
line-length = 100
target-version = "py310"
select = ["E", "F", "I", "N", "W", "UP"]
ignore = ["E501"]
```

with

```toml
[tool.yapf]
based_on_style = "google"
column_limit = 80
```

- [ ] **Step 3: Update pixi tasks**

In `[tool.pixi.tasks]`, replace

```toml
format = "black . && ruff check --fix ."
lint = "ruff check ."
```

with

```toml
format = "yapf -ir app tests"
lint = "pylint --rcfile=../pylintrc app tests"
```

- [ ] **Step 4: Update app/Makefile**

Replace the `format:` and `lint:` targets:

```make
format:
	yapf -ir app tests

lint:
	pylint --rcfile=../pylintrc app tests
```

- [ ] **Step 5: Reformat and lint**

```bash
cd app && ../.venv/bin/yapf -ir app tests && cd ..
cd app && ../.venv/bin/pylint --rcfile=../pylintrc app tests; cd ..
```

Fix findings per the same policy as Task 7 step 6 (all E-category fixed;
targeted disables only where a fix changes behavior).

- [ ] **Step 6: Convert docstrings to Google style**

Run the docstring checker with dirs `app/app app/tests`; fix every hit.

- [ ] **Step 7: Run the test suite**

```bash
make test
```

Expected: 59 passed.

- [ ] **Step 8: Commit**

```bash
git add app
git commit -m "Adopt Google Python style in app backend"
```

---

### Task 9: MCP server — Google Python toolchain

**Files:**
- Modify: `engine/mcp_server/pyproject.toml:30-36` (dev deps), `:43-47`
  (tool sections)
- Modify: docstrings across `engine/mcp_server/`

- [ ] **Step 1: Swap dev dependencies**

In `engine/mcp_server/pyproject.toml` dev extras, replace

```toml
    "black>=23.0.0",
    "ruff>=0.1.0",
```

with

```toml
    "yapf>=0.43.0",
    "pylint>=3.3",
```

- [ ] **Step 2: Swap tool config**

Replace

```toml
[tool.black]
line-length = 88

[tool.ruff]
line-length = 88
```

with

```toml
[tool.yapf]
based_on_style = "google"
column_limit = 80
```

- [ ] **Step 3: Reformat, lint, fix docstrings**

```bash
cd engine/mcp_server && ../../.venv/bin/yapf -ir mcp_server tests 2>/dev/null || ../../.venv/bin/yapf -ir mcp_server; cd ../..
cd engine/mcp_server && ../../.venv/bin/pylint --rcfile=../../pylintrc mcp_server; cd ../..
```

(The `tests` directory may not exist; the fallback handles that.) Fix pylint
findings per the Task 7 policy, then run the docstring checker with dir
`engine/mcp_server` and fix hits.

- [ ] **Step 4: Verify it still parses as a package**

```bash
python3 -m compileall -q engine/mcp_server && echo OK
```

Expected: `OK`. (Runtime needs Python 3.12 + deps; compile check is the
gate here, consistent with how this package is treated elsewhere.)

- [ ] **Step 5: Commit**

```bash
git add engine/mcp_server
git commit -m "Adopt Google Python style in MCP server"
```

---

### Task 10: Root Makefile

**Files:**
- Modify: `Makefile` (help text line ~25, `setup` pip line ~42, `lint`
  target ~96)

- [ ] **Step 1: Update the hardcoded dev-tools install in `setup`**

Replace

```make
	@$(PIP) install pytest pytest-asyncio black ruff mypy
```

with

```make
	@$(PIP) install pytest pytest-asyncio yapf pylint mypy
```

- [ ] **Step 2: Update the `lint` target**

Replace

```make
lint:
	@cd "$(APP)" && "$(PY)" -m ruff check app/ tests/ || true
```

with

```make
lint:
	@cd "$(APP)" && "$(PY)" -m pylint --rcfile=../pylintrc app tests || true
```

- [ ] **Step 3: Update the help line**

Replace `@echo "  make lint         Lint backend (ruff)"` with
`@echo "  make lint         Lint backend (pylint)"`.

- [ ] **Step 4: Verify and commit**

```bash
make lint
git add Makefile
git commit -m "Point root lint and setup targets at yapf and pylint"
```

Expected: pylint output (non-fatal — the target keeps `|| true`).

---

### Task 11: Frontend — gts

**Files:**
- Modify: `app/frontend/package.json` (scripts + devDependencies)
- Create: `app/frontend/eslint.config.cjs`
- Create: `app/frontend/.prettierrc.cjs`
- Delete: `app/frontend/biome.json`
- Modify: every `.ts`/`.tsx` under `app/frontend/src` (reformat)

Note: the frontend `package.json` has `"type": "module"`, so the gts/ESLint
config files must use the `.cjs` extension with CommonJS syntax.

- [ ] **Step 1: Swap dependencies**

```bash
cd app/frontend
bun remove @biomejs/biome
bun add -d gts
rm biome.json
```

- [ ] **Step 2: Update package.json scripts**

Replace the `scripts` block with:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build && node scripts/prerender.mjs",
    "preview": "vite preview",
    "lint": "gts lint",
    "fix": "gts fix",
    "clean": "gts clean"
  },
```

- [ ] **Step 3: Create `eslint.config.cjs`**

```javascript
/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
module.exports = [
  {
    ignores: ['dist/**', 'node_modules/**', 'scripts/**'],
  },
  ...require('gts'),
];
```

- [ ] **Step 4: Create `.prettierrc.cjs`**

```javascript
module.exports = require('gts/.prettierrc.json');
```

If that require fails at runtime (package `exports` restriction), inline the
values instead — copy them from `node_modules/gts/.prettierrc.json` verbatim
(`cat node_modules/gts/.prettierrc.json`).

- [ ] **Step 5: Reformat**

```bash
bun run fix
```

Expected: a large diff across `src/`. If `gts fix` reports unfixable lint
errors, fix them by hand; for rules that fight React idioms (if any), add a
rule override to the first object in `eslint.config.cjs` with the rule name
set to `'off'` — keep overrides to the minimum needed.

- [ ] **Step 6: Lint and build**

```bash
bun run lint
bun run build
cd ../..
```

Expected: lint exits 0; tsc + vite build succeed (the build script is
unchanged, so the Vercel deploy is unaffected).

- [ ] **Step 7: Run app tests (API contract untouched, belt-and-braces)**

```bash
make test
```

Expected: 59 passed.

- [ ] **Step 8: Commit**

```bash
git add app/frontend
git commit -m "Replace Biome with gts in frontend"
```

---

### Task 12: Docs restyle

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/FIDELITY.md`

- [ ] **Step 1: Apply Google docs style to both files**

Rules (matching `references/antigravity-science-skills/README.md`):

1. Headings in sentence case ("## Data flow", not "## Data Flow").
2. Prose hard-wrapped at 80 columns. Tables, code blocks, and long URLs are
   exempt.
3. Bulleted lists use `-` followed by three spaces, with continuation lines
   indented four spaces:

   ```markdown
   -   **WorkflowState** — shared state that flows through the graph and
       auto-dedupes hypotheses on every update.
   ```

4. Second person, present tense ("You configure…", "The supervisor plans…");
   remove first-person-plural narration where it appears.

Content is otherwise unchanged — this is a formatting/tone pass, not a
rewrite.

- [ ] **Step 2: Check the wrap**

```bash
awk 'length($0) > 80 && $0 !~ /\|/ && $0 !~ /http/ && $0 !~ /^```/' docs/ARCHITECTURE.md docs/FIDELITY.md
```

Expected: no output (or only lines inside code blocks — verify each
remaining hit by eye).

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md docs/FIDELITY.md
git commit -m "Restyle architecture and fidelity docs"
```

---

### Task 13: AGENTS.md, final verification, push

**Files:**
- Modify: `AGENTS.md` (CLAUDE.md is a symlink to it — edit AGENTS.md only)

- [ ] **Step 1: Update AGENTS.md to match the new toolchain**

Make these edits:

1. Engine commands block: replace
   `black . && ruff check --fix .     # format` and
   `ruff check .                      # lint` with

   ```bash
   yapf -ir src dev examples         # format (Google style, 80 cols)
   pylint --rcfile=../pylintrc src/co_scientist   # lint
   ```

2. Engine style conventions: add as the first bullet:
   `- Code follows the Google Python Style Guide: yapf (based_on_style =
   google, 80 columns), pylint with the repo-root pylintrc, Google-format
   docstrings (Args:/Returns:/Raises:).`

3. App backend commands comment: change
   `make format / lint / typecheck   # black+ruff / ruff / mypy` to
   `make format / lint / typecheck   # yapf / pylint / mypy`.

4. Frontend section: change `Linter/formatter is **Biome**, not
   ESLint/Prettier.` to `Linter/formatter is **gts** (Google TypeScript
   Style: ESLint + Prettier).` and update the commands block:

   ```bash
   bun run lint         # gts lint
   bun run fix          # gts fix (format + autofix)
   ```

   (remove the `bun run check` line).

5. "Working in this repo" section: add the bullet
   `- All source files carry the Apache 2.0 header (copyright "The
   Co-Scientist Authors"); new files must too. Repo license is Apache-2.0.`

- [ ] **Step 2: Full verification sweep**

```bash
make test                                  # 59 passed
cd engine && ../.venv/bin/python -m pytest -q && cd ..   # clean
cd app/frontend && bun run lint && bun run build && cd ../..
make lint                                  # pylint, non-fatal
```

- [ ] **Step 3: Commit and push**

```bash
git add AGENTS.md
git commit -m "Update agent docs for Google style toolchain"
git push
```

- [ ] **Step 4: Watch the production deploys**

The push triggers Vercel (frontend) and Railway (api, mcp) builds from
`main`. Verify:

```bash
curl -s https://api-production-97eb.up.railway.app/health
```

and load https://co-scientist-ui.vercel.app. Both should behave exactly as
before — this migration changes no behavior.
