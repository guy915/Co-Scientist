# How to contribute

We would love to accept your patches and contributions to this project.

## Before you begin

### Review our community guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## Getting set up

From the repo root:

```bash
make setup          # Python venvs (engine + app) and frontend deps
make start          # API on :8008, UI on :5173, MCP on :8888
```

See [`docs/RUNNING-LOCALLY.md`](docs/RUNNING-LOCALLY.md) for running individual
pieces and the git-worktree gotchas, and [`AGENTS.md`](AGENTS.md) for the full
repository guide.

## Testing

```bash
make test-all       # engine + app pytest suites plus the parity ledger gate
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
