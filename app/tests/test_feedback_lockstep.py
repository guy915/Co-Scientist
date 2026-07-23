"""Guard for the cross-language feedback-category lockstep.

The category set ``{bug, suggestion, question, praise}`` is hand-maintained
in four places -- the backend tuple in ``app/feedback.py``, the TypeScript
union in ``frontend/src/api/feedback.ts``, and the label/value array in
``frontend/src/workbench/audience_content.ts`` (plus the parametrized cases in
``test_feedback.py``). Nothing at runtime keeps them aligned, so this test
parses the two frontend sources with structure-tolerant regexes and asserts
all three category sets are identical. It fails loudly the moment one surface
drifts from the others.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.feedback import FEEDBACK_CATEGORIES

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
_UNION_TS = _FRONTEND / "api" / "feedback.ts"
_ARRAY_TS = _FRONTEND / "workbench" / "audience_content.ts"


def _quoted_members(text: str) -> set[str]:
    """Return every single-quoted token in the given snippet."""
    return set(re.findall(r"'([^']+)'", text))


def _union_categories() -> set[str]:
    """Parse the ``FeedbackCategory`` union members from feedback.ts.

    Matches the ``type FeedbackCategory = ...`` declaration up to its
    terminating semicolon and pulls out every quoted union member, so the
    assertion survives reformatting of the union across lines.
    """
    source = _UNION_TS.read_text(encoding="utf-8")
    match = re.search(r"type\s+FeedbackCategory\s*=\s*([^;]+);", source)
    assert match, "FeedbackCategory union not found in feedback.ts"
    return _quoted_members(match.group(1))


def _array_categories() -> set[str]:
    """Parse the ``value:`` entries of the FEEDBACK_CATEGORIES array.

    Locates the array literal that follows the ``FEEDBACK_CATEGORIES``
    declaration and collects each ``value: '...'`` token, ignoring the
    accompanying labels and any surrounding whitespace churn.
    """
    source = _ARRAY_TS.read_text(encoding="utf-8")
    anchor = source.index("FEEDBACK_CATEGORIES")
    body = source[anchor:]
    return set(re.findall(r"value:\s*'([^']+)'", body))


def test_backend_and_frontend_category_sets_match() -> None:
    backend = set(FEEDBACK_CATEGORIES)

    assert backend, "backend FEEDBACK_CATEGORIES is empty"
    assert _union_categories() == backend
    assert _array_categories() == backend
