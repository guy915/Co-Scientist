"""Audience-specific prompt context, loaded from bundled markdown files.

Only the ``sbi_ucd`` audience carries injected context today; the loader is
written generically so adding another audience's file is a one-line change.
The file is read once and cached, since it never changes at runtime.

The bundled file is the group's own reference document, shipped verbatim and
in full to every surface -- run planning, generation, reflection, evolution,
meta-review, every tournament comparison, chat Q&A, and the goal interview.
An earlier version of this module summarised that document into a short
profile plus a longer reference and served the two to different surfaces.
That is deliberately gone: the summary was written from a model's
understanding of the group rather than from the document, so what reached a
run was a paraphrase that dropped the people, the mathematics, and the
collaborators. One file, served everywhere, is the only arrangement in which
what the scientist wrote is what the model reads.
"""

from __future__ import annotations

import logging
import re
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_AUDIENCES: tuple[str, ...] = ("general", "google", "sbi_ucd")
AUDIENCE_PATTERN: str = f"^({'|'.join(VALID_AUDIENCES)})$"

# Audiences with a bundled context file, mapped to their filename under
# ``content/``. Absent audiences contribute no context.
_CONTEXT_FILES: dict[str, str] = {"sbi_ucd": "sbi_ucd_context.md"}

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


# Chat and the interview ask for "everything we know about this group",
# the run path asks for "the context". Those were once different texts;
# they are the same document now, and this alias is what keeps a future
# divergence a one-line change.
audience_chat_context = audience_context
