"""Shared type vocabulary for the ``cosci`` CLI.

Holds the command-handler signature, which both the command modules (which
implement handlers) and the parser modules (which register them as argparse
defaults) need. It lives here rather than in either layer so a command module
never has to import a parser module to name its own type. Kept import-light
(stdlib + httpx only) so ``cosci --help`` does not pull in FastAPI or the
engine.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from app.cli.http import ApiClient

Handler = Callable[[argparse.Namespace, ApiClient], int]
