"""``cosci`` operator CLI for driving Co-Scientist runs from a terminal.

A thin, agent-friendly wrapper over the app's HTTP API (``/api/runs`` plus
the ``/health``/``/status``/``/config`` diagnostics). Commands map onto
existing endpoints; the client-side behavior the CLI adds is confined to
reliability and scripting concerns — GET retries, ``watch`` stream
reconnection, ``wait`` polling with status-encoding exit codes, and stdin
(``-``) text arguments. See ``app.cli.main`` for the argument parser and
``app.cli.http`` for the HTTP client.
"""

from __future__ import annotations

from app.cli.main import main

__all__ = ["main"]
