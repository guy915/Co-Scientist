"""Verify all loaded project modules against a frozen source manifest."""

import hashlib
import sys
from pathlib import Path


def imported_sources(root, expected):
    sources = {}
    for name, module in list(sys.modules.items()):
        if name.split(".")[0] not in {"app", "co_scientist", "evaluations"}:
            continue
        filename = getattr(module, "__file__", None)
        if filename is None:
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError(f"Project import escaped snapshot: {name}")
        relative = str(path.relative_to(root))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected.get(relative, {}).get("sha256") != sha:
            raise RuntimeError(f"Project import differs from manifest: {name}")
        sources[name] = {"path": relative, "sha256": sha}
    return sources
