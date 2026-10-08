# app

The workbench and the API's packaging. The server code itself is the
`co_scientist` package in [`engine/src/`](../engine/src/co_scientist/); its
composition root is `co_scientist.main`.

| Path | Contents |
| --- | --- |
| `frontend/` | React workbench; see [its README](frontend/README.md) |
| `tests/` | API test suite (`make test-app`) |
| `dev/` | Operator scripts: `backup_db.py` (consistent SQLite backups, see [launch](../docs/LAUNCH.md#backup-and-restore)) and `refresh_retractions.py` (rebuilds the committed retraction extract) |
| `pyproject.toml`, `requirements-app.txt` | The API's runtime dependencies; keep the two lists in sync |
| `.env.example` | Every API setting with its default |
| `docker-compose.yml`, `docker/` | Development containers for the API and MCP server |
| `Makefile` | Shortcuts for working from this folder |

Use the root `Makefile` for everyday work: `make setup`, `make start` and
`make check` (see [local setup](../docs/RUNNING-LOCALLY.md)). Production
images are built from the root `Dockerfile.api`; see
[deployment](../docs/DEPLOYMENT.md).
