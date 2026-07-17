"""Audience-specific prompt context, loaded from bundled markdown files.

Only the ``sbi_ucd`` audience carries injected context today; the loader is
written generically so adding another audience's file is a one-line change.
The file is read once and cached, since it never changes at runtime.
"""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_AUDIENCES: tuple[str, ...] = ("general", "google", "sbi_ucd")
AUDIENCE_PATTERN: str = "^(general|google|sbi_ucd)$"

# Audiences with a bundled context file, mapped to their filename under
# ``content/``. Absent audiences contribute no context.
_CONTEXT_FILES: dict[str, str] = {"sbi_ucd": "sbi_ucd_context.md"}

_CONTENT_DIR = Path(__file__).parent / "content"


@cache
def _load_context_file(filename: str) -> str:
    """Read and cache one context markdown file, or return empty on failure.

    Args:
        filename: The file's name under the ``content/`` directory.

    Returns:
        The file's text, or an empty string if it cannot be read.
    """
    path = _CONTENT_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Could not read audience context %s: %s", path, exc)
        return ""


def audience_context(audience: str | None) -> str:
    """Return the prompt context for an audience, or empty when it has none.

    Args:
        audience: The self-declared audience value, possibly None or unknown.

    Returns:
        The audience's injected context text, or an empty string when the
        audience has no bundled context (all but ``sbi_ucd`` today).
    """
    filename = _CONTEXT_FILES.get(audience or "")
    if filename is None:
        return ""
    return _load_context_file(filename)
