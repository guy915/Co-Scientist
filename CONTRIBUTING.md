# How to contribute

We would love to accept your patches and contributions to this project.

## Before you begin

### Review our community guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## Getting set up

Install Python 3.12, Node.js 22.13+, and Bun 1.3.14, then run from the repo root:

```bash
make setup          # one Python venv (engine + app, editable) and frontend deps
make start          # API on :8008, UI on :5173, MCP on :8888
```

See [`docs/RUNNING-LOCALLY.md`](docs/RUNNING-LOCALLY.md) for running individual
pieces and the git-worktree gotchas. [`AGENTS.md`](AGENTS.md) is the full
repository guide (layout, gotchas, environment); per-project detail lives in
[`app/AGENTS.md`](app/AGENTS.md) and [`engine/AGENTS.md`](engine/AGENTS.md),
and production hosting in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Testing

```bash
make check          # full offline validation, including browser tests
make test-all       # backend + frontend suites plus the parity ledger gate
make e2e            # Playwright end-to-end suite
cd app/frontend && bun run test   # frontend unit tests
```

## Contribution process

### Code reviews

All submissions, including submissions by project members, require review. We
use [GitHub pull requests](https://docs.github.com/articles/about-pull-requests)
for this purpose.

### Commits, branches, and pull requests

-   Commit messages follow `<type>(<scope>): <subject>`, where `<type>` is one
    of `feat`, `fix`, `docs`, `refactor`, `test`, or `chore` (e.g.
    `fix(report-tab): handle missing markdown gracefully`).
-   Branch names follow `<type>/<description>` using the same type vocabulary
    (e.g. `docs/restructure-engine-docs`).
-   PR titles are short, standalone, imperative summaries — no Conventional
    Commit prefix in the title. PR bodies explain what changed, why, and how it
    was tested.

### Style

-   Python code follows the
    [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
    Format with `ruff format` (80 columns) and lint with `ruff check`
    (config in each project's `pyproject.toml`). Both projects are
    mypy-strict; `Any` is reserved for genuinely dynamic data — JSON-shaped
    LLM responses, event payloads, and YAML config fragments
    (`dict[str, Any]`) — and should not appear on interfaces whose types
    are known.
-   Size ceilings are gated, not conventional: 500 lines per source file and
    40 lines of code per function (docstrings excluded), both checked by
    `make parity`; ruff enforces a cyclomatic complexity of 5 and at most
    five arguments per function.
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

## Licensing

By submitting a contribution, you agree to license your first-party changes
under the project's [Apache 2.0 license](LICENSE). Preserve third-party notices
and do not reformat or silently modify `vendor/`.

Keep the package-local `LICENSE` and `NOTICE` copies in `app/`, `engine/`,
and `engine/mcp_server/` synchronized with their root counterparts so standalone
distributions retain them.

Report vulnerabilities privately through [SECURITY.md](SECURITY.md).
