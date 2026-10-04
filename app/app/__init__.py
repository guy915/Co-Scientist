"""Installed package metadata is the version source for API diagnostics; raw
checkouts need a fallback when distribution metadata is absent.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DIST_NAME = "co-scientist-viewer"

try:
    API_VERSION = version(_DIST_NAME)
except PackageNotFoundError:  # pragma: no cover - raw checkout only
    API_VERSION = "0.1.0"
