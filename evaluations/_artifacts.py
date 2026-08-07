"""Shared result-artifact writing for the offline evaluation runners.

Every runner that persists a report writes it the same way: into
``evaluations/results/`` under a date-stamped name, as indented JSON with a
trailing newline. Owning that here keeps the runners from drifting on the
directory, the date format, or the encoding.

Every artifact also gets a ``provenance`` block, stamped automatically by
``write_dated_artifact`` so no runner has to remember to add one. A number
with no record of what produced it cannot be reproduced or challenged later:
this block is the source revision, the execution environment, and the prompt
templates in effect, plus whatever the caller knows about the model, seed,
and cost behind its own measurement.

Runners that only print a summary (``scaling_eval``) deliberately write no
artifact and do not use this module.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import platform
import subprocess
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_RESULTS_DIR = _ROOT / "evaluations" / "results"
_PROMPTS_DIR = (
    _ROOT / "engine" / "src" / "co_scientist" / "prompts" / "templates"
)

# Bounds a single best-effort `git` subprocess call. Provenance capture must
# never be why a runner hangs -- an unresponsive git is worth "unknown", not
# a stalled eval.
_GIT_TIMEOUT_SECONDS = 5


def _git(*args: str) -> str | None:
    """Runs a `git` subcommand against the repo root; None on any failure.

    Deliberately swallows every failure mode (git absent, not a repo, a
    detached/shallow checkout with no HEAD, a timeout): provenance capture
    degrades to "unknown" rather than failing the eval it is attached to.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _source_provenance() -> dict[str, Any]:
    """The source revision this process is running from.

    ``git_dirty`` is None (unknown) rather than False when the status check
    itself failed, so a reader never confuses "could not tell" with
    "confirmed clean".
    """
    status = _git("status", "--porcelain")
    return {
        "git_commit": _git("rev-parse", "HEAD") or "unknown",
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "git_dirty": bool(status) if status is not None else None,
    }


def _environment_provenance() -> dict[str, Any]:
    """The interpreter and OS this artifact was produced under."""
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def _prompt_identity() -> dict[str, Any]:
    """A stable digest over the engine's prompt templates.

    Every markdown template's relative path and bytes feed one hash, so two
    artifacts with the same digest ran against byte-identical prompts and
    one with a different digest did not -- without having to diff the
    templates directory by hand months later. Missing entirely (the engine
    checkout is absent) reports as such rather than raising.
    """
    if not _PROMPTS_DIR.is_dir():
        return {"templates_dir": None, "digest": None, "file_count": 0}
    files = sorted(_PROMPTS_DIR.rglob("*.md"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(_PROMPTS_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return {
        "templates_dir": str(_PROMPTS_DIR.relative_to(_ROOT)),
        "digest": digest.hexdigest(),
        "file_count": len(files),
    }


def build_provenance(
    *,
    model: Any = None,
    seed: Any = None,
    cost: Any = None,
) -> dict[str, Any]:
    """Assembles the provenance block stamped onto every artifact.

    Args:
        model: Model identifier(s) the measurement exercised (e.g. a
            litellm model string, or a dict of role -> model for a run with
            several). None when the runner made no model call (a purely
            deterministic assessor).
        seed: The random or deterministic seed behind the measurement, or a
            description of one (e.g. "derived from research goal +
            iteration" for the engine's tournament pairing). None when
            nothing in the run was seeded.
        cost: The cost the measurement incurred -- typically a dict with a
            currency/token breakdown. None when no billed call was made.

    Returns:
        A JSON-serializable provenance dict: ``source`` (git commit/branch/
        dirty), ``environment`` (python/platform), ``prompts`` (template
        digest), the three caller-supplied fields above, and
        ``captured_at``.
    """
    return {
        "source": _source_provenance(),
        "environment": _environment_provenance(),
        "prompts": _prompt_identity(),
        "model": model,
        "seed": seed,
        "cost": cost,
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def write_dated_artifact(
    report: dict[str, Any],
    filename_stem: str,
    *,
    model: Any = None,
    seed: Any = None,
    cost: Any = None,
) -> pathlib.Path:
    """Writes a report to ``results/<filename_stem>-<today>.json``.

    Stamps a ``provenance`` block onto the report before writing (see
    ``build_provenance``); a runner that knows its own model, seed, or cost
    passes them through here rather than folding them into the report body
    by hand, so every artifact carries them the same way.

    Args:
        report: JSON-serializable report body.
        filename_stem: Artifact name without the date or extension; today's
            ISO date and ".json" are appended.
        model: Forwarded to ``build_provenance``.
        seed: Forwarded to ``build_provenance``.
        cost: Forwarded to ``build_provenance``.

    Returns:
        The written path, relative to the repository root, so a runner can
        print it without restating where the results directory lives.
    """
    stamped = {
        **report,
        "provenance": build_provenance(model=model, seed=seed, cost=cost),
    }
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"{filename_stem}-{date}.json"
    out.write_text(json.dumps(stamped, indent=2) + "\n", encoding="utf-8")
    return out.relative_to(_ROOT)
