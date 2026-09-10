"""Locates the Google prompts published alongside the papers.

The papers and the Nature supplement print the agents' prompts in full
(paper §A.2, SI Note 9). All eight are mirrored byte-exact -- header
comment, heading, and fenced body -- in the committed corpus at
``docs/CORPUS-EXTRACTION.md`` (Appendix A), which is the reproduction the
fidelity tests read. That mirror was previously a second copy under
``references/core/``; the reference tree has since been removed (its
publishable content is exactly this Appendix), so the one committed home
of the published text is the only source now.

``docs/`` lives outside ``engine/``, which is independently installable.
An engine extracted on its own has no ``docs/CORPUS-EXTRACTION.md`` and
skips; a checkout that has it but has lost a prompt from it is a move or a
deletion, and fails.

The engine's two published-value pin modules -- ``pseudocode_invariants``
and ``artifact_shapes`` -- carry their pinned values inline as cited module
constants and do not read this module at all. Their ``_corroboration``
siblings, which re-read the raw reference tree, were removed with that tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_APPENDIX = (
    Path(__file__).resolve().parents[2] / "docs" / "CORPUS-EXTRACTION.md"
)

# An Appendix-A prompt entry opens ``#### `<stem>.md` `` and wraps the
# verbatim reference file (comment header, ``# heading``, and the inner
# ```` ``` ```` prompt fence) in an outer fence of four-or-more backticks.
_OUTER_FENCE = re.compile(r"^(`{4,})\s*$")


def corpus_available() -> bool:
    """True when the published-prompt corpus is checked out beside the engine.

    Callers that read the corpus at *collection* time need this: a
    ``pytest.skip`` raised while a parametrization is being built is a
    collection error, not a skip, so the engine-alone checkout this module
    exists to tolerate would go red instead of quiet.

    Returns:
        Whether ``docs/CORPUS-EXTRACTION.md`` is present.
    """
    return _APPENDIX.is_file()


def published_prompt(name: str) -> str:
    """Return one of the eight prompts the papers publish in full.

    Reads the verbatim reference file as reproduced in ``docs/
    CORPUS-EXTRACTION.md``'s Appendix A -- the outer-fenced block under the
    ``#### `<stem>.md` `` heading -- so the returned text is the same
    header-comment-plus-fenced-body shape the standalone file carried.

    Args:
        name: The prompt's stem, e.g. ``ranking-04-pairwise-comparison``.

    Returns:
        The file's text, header comment and inner fence included.
    """
    if not _APPENDIX.is_file():
        pytest.skip("engine checked out without docs/CORPUS-EXTRACTION.md")
    lines = _APPENDIX.read_text(encoding="utf-8").splitlines()
    heading = f"#### `{name}.md`"
    return _extract_outer_fence(lines, heading, name)


def _extract_outer_fence(lines: list[str], heading: str, name: str) -> str:
    """Return the outer-fenced block that follows ``heading``.

    Args:
        lines: The Appendix file split into lines.
        heading: The ``#### `<stem>.md` `` line that opens the entry.
        name: The stem, for the assertion message.

    Returns:
        The block's inner text (the verbatim reference file).
    """
    start = next((i for i, ln in enumerate(lines) if ln.strip() == heading), -1)
    assert start >= 0, f"published prompt missing from Appendix A: {name}"
    fence = ""
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not fence:
            if match := _OUTER_FENCE.match(line):
                fence = match.group(1)
            continue
        if line.strip() == fence:
            return "\n".join(body)
        body.append(line)
    raise AssertionError(f"published prompt has no closed fence: {name}")
