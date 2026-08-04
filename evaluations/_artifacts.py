"""Shared result-artifact writing for the offline evaluation runners.

Every runner that persists a report writes it the same way: into
``evaluations/results/`` under a date-stamped name, as indented JSON with a
trailing newline. Owning that here keeps the runners from drifting on the
directory, the date format, or the encoding.

Runners that only print a summary (``scaling_eval``) deliberately write no
artifact and do not use this module.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_RESULTS_DIR = _ROOT / "evaluations" / "results"


def write_dated_artifact(
    report: dict[str, Any], filename_stem: str
) -> pathlib.Path:
    """Writes a report to ``results/<filename_stem>-<today>.json``.

    Args:
        report: JSON-serializable report body.
        filename_stem: Artifact name without the date or extension; today's
            ISO date and ".json" are appended.

    Returns:
        The written path, relative to the repository root, so a runner can
        print it without restating where the results directory lives.
    """
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"{filename_stem}-{date}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out.relative_to(_ROOT)
