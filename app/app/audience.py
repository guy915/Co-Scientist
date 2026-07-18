"""Audience-specific prompt context, loaded from bundled markdown files.

Only the ``sbi_ucd`` audience carries injected context today; the loader is
written generically so adding another audience's file is a one-line change.
The file is read once and cached, since it never changes at runtime.
"""

from __future__ import annotations

import logging
import re
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_AUDIENCES: tuple[str, ...] = ("general", "google", "sbi_ucd")
AUDIENCE_PATTERN: str = "^(general|google|sbi_ucd)$"

# Audiences with a bundled context file, mapped to their filename under
# ``content/``. Absent audiences contribute no context.
_CONTEXT_FILES: dict[str, str] = {"sbi_ucd": "sbi_ucd_context.md"}

# The deeper reference, loaded only where a single call can afford it. The
# run pipeline cannot: run_setup_guidance reaches generation, reflection,
# evolution, meta-review and every tournament comparison, and ranking is
# roughly quadratic in the hypothesis count, so anything injected there is
# paid for tens to hundreds of times per run. Chat answers one question per
# call, and the questions are often definitional, so they take the long form.
_REFERENCE_FILES: dict[str, str] = {"sbi_ucd": "sbi_ucd_reference.md"}

_CONTENT_DIR = Path(__file__).parent / "content"


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@cache
def _load_context_file(filename: str) -> str:
    """Read and cache one context markdown file, or return empty on failure.

    HTML comments are stripped: these files carry maintainer notes about
    where the text is injected and what it may cost, which are instructions
    to a reader of the repository, not to the model.

    Args:
        filename: The file's name under the ``content/`` directory.

    Returns:
        The file's text without comments, or an empty string if it cannot
        be read.
    """
    path = _CONTENT_DIR / filename
    try:
        return _COMMENT.sub("", path.read_text(encoding="utf-8")).strip()
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


def audience_reference(audience: str | None) -> str:
    """Return the extended reference for an audience, or empty when none.

    This is the long form, for callers that make one LLM call rather than
    one per hypothesis or per tournament match. Use `audience_context` for
    anything on the run path.

    Args:
        audience: The self-declared audience value, possibly None or unknown.

    Returns:
        The audience's reference text, or an empty string when the audience
        has no bundled reference (all but ``sbi_ucd`` today).
    """
    filename = _REFERENCE_FILES.get(audience or "")
    if filename is None:
        return ""
    return _load_context_file(filename)


def audience_chat_context(audience: str | None) -> str:
    """Return the full background for chat: the profile plus the reference.

    Chat is the one surface that makes a single LLM call per user question,
    so it can afford both. Everything on the run path takes
    `audience_context` alone.

    Args:
        audience: The self-declared audience value, possibly None or unknown.

    Returns:
        The profile and reference joined, either alone if only one exists,
        or an empty string when the audience has neither.
    """
    parts = [audience_context(audience), audience_reference(audience)]
    return "\n\n".join(part for part in parts if part)
