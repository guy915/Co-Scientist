# Contributing

Thanks for helping with Co-Scientist. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as
described in [SECURITY.md](SECURITY.md), never in a public issue.

## Prerequisites

- Python 3.12
- Node.js 22.13 or newer
- Bun exactly 1.3.14:

  ```bash
  curl -fsSL https://bun.sh/install | bash -s "bun-v1.3.14"
  ```

## Set up and run

```bash
git clone https://github.com/guy915/Co-Scientist.git && cd Co-Scientist
make setup   # Python venv and locked frontend dependencies
make start   # API :8008, UI :5173, MCP :8888
```

`make start` stops whatever is listening on ports 8008, 5173 and 8888.
No API key is needed: with no provider key set, the deterministic offline
backend runs the whole pipeline. See
[docs/RUNNING-LOCALLY.md](docs/RUNNING-LOCALLY.md) for details.

## Checks

Run these before opening a pull request:

```bash
make lint
make typecheck
make test-all
make e2e
```

`make check` runs all of them plus the evaluation smoke test and the
production build. CI is hermetic, so tests must not need network access or a
provider key.

## Commits, branches and pull requests

- Commit messages: `<type>(<scope>): <subject>`, for example
  `fix(report-tab): handle missing markdown gracefully`. Types are `feat`,
  `fix`, `docs`, `refactor`, `test` and `chore`.
- Branch names: `<type>/<description>`, for example
  `fix/report-tab-empty-state`.
- Pull request titles are a short, imperative summary without a type prefix,
  such as `Remove unused generate endpoints`. The body says what changed, why,
  and how you tested it.
- One theme per pull request.
- Changes that affect model behavior should include benchmark scores before
  and after; see [docs/OPTIMIZATION.md](docs/OPTIMIZATION.md).

## Documentation style

Add a comment or docstring only for a reason the code cannot show: why,
an invariant, or an outside fact. Keep it to about two lines, and do not
restate the code.

## Deeper rules

[AGENTS.md](AGENTS.md) holds the repository-wide conventions and operational
invariants. Read [app/AGENTS.md](app/AGENTS.md) before changing the API or
frontend and [engine/AGENTS.md](engine/AGENTS.md) before changing the engine.
Do not reformat anything under `vendor/`.

## License

Contributions are licensed under the [Apache License 2.0](LICENSE), as
described in section 5 of the license. There is no separate contributor
license agreement.
