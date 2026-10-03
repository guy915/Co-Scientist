"""Co-Scientist FastAPI server and installed API version.

The canonical version lives in ``pyproject.toml``; this module reads it
from the installed package metadata so the FastAPI app, the root
endpoint, and the health endpoint all report the same value. The
fallback covers running from a raw checkout where the distribution
metadata is not installed.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DIST_NAME = "co-scientist-viewer"

try:
    API_VERSION = version(_DIST_NAME)
except PackageNotFoundError:  # pragma: no cover - raw checkout only
    API_VERSION = "0.1.0"
