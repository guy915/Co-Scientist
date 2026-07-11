"""``cosci`` operator CLI for driving Co-Scientist runs from a terminal.

A thin, agent-friendly wrapper over the app's HTTP API (``/api/runs`` plus the
``/health``/``/status`` diagnostics). Every command is a direct call to an
existing endpoint; the CLI adds no behavior of its own. See ``app.cli.main``
for the argument parser and ``app.cli.http`` for the HTTP client.
"""

from __future__ import annotations

from app.cli.main import main

__all__ = ["main"]
