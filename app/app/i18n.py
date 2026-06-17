"""Server-side localization helpers.

The frontend stores a two-letter locale code (e.g. "he") on each run. These
helpers translate that code into the natural-language name the engine and chat
prompts expect, and provide localized strings for the few pieces of report text
that are assembled in Python rather than produced by the model.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

# Map locale code -> human-readable language name used inside LLM prompts.
_LANGUAGE_NAMES: dict[str, str] = {
    "he": "Hebrew",
}

# Locales that read right-to-left.
_RTL_LOCALES = frozenset({"he", "ar", "fa", "ur"})


def language_name(code: str | None) -> str | None:
    """Return the prompt-ready language name for a locale code.

    Args:
        code: Two-letter locale code (optionally region-suffixed), or None.

    Returns:
        The language name (e.g. "Hebrew"), or None when the locale is unset or
        English/unknown and the prompts should stay in English.
    """
    if not code:
        return None
    base = code.split("-")[0].lower()
    if base in ("", "en"):
        return None
    return _LANGUAGE_NAMES.get(base)


def is_rtl(code: str | None) -> bool:
    """Return whether the given locale code is written right-to-left."""
    if not code:
        return False
    return code.split("-")[0].lower() in _RTL_LOCALES


# Localized labels for the Python-assembled report. Keys mirror the English
# defaults; missing locales fall back to English via report_labels().
_REPORT_LABELS: dict[str, dict[str, str]] = {
    "he": {
        "run_title": "ריצת Co-Scientist",
        "profile": "פרופיל",
        "provider": "ספק",
        "hypotheses": "השערות",
        "top_hypotheses": "ההשערות המובילות לפי Elo",
        "meta_review": "תובנות מטא-סקירה",
        "common_strengths": "חוזקות משותפות",
        "common_weaknesses": "חולשות משותפות",
        "emerging_themes": "מוטיבים מתהווים",
        "areas_for_improvement": "תחומים לשיפור",
        "strategic_recommendations": "המלצות אסטרטגיות",
    },
}

_REPORT_LABELS_EN: dict[str, str] = {
    "run_title": "Co-Scientist Run",
    "profile": "Profile",
    "provider": "Provider",
    "hypotheses": "Hypotheses",
    "top_hypotheses": "Top hypotheses by Elo",
    "meta_review": "Meta-review insights",
    "common_strengths": "Common strengths",
    "common_weaknesses": "Common weaknesses",
    "emerging_themes": "Emerging themes",
    "areas_for_improvement": "Areas for improvement",
    "strategic_recommendations": "Strategic recommendations",
}


def report_labels(code: str | None) -> dict[str, str]:
    """Return the report heading labels for a locale, defaulting to English."""
    base = (code or "").split("-")[0].lower()
    overrides = _REPORT_LABELS.get(base, {})
    return {**_REPORT_LABELS_EN, **overrides}


# Milestone messages emitted into the chat as the workflow progresses. Each
# entry is a format template; placeholders are filled by milestone_text().
_MILESTONES_EN: dict[str, str] = {
    "supervisor": "Research plan ready — supervisor complete",
    "generate": "{count} hypotheses generated ({label})",
    "label_initial": "initial",
    "label_iteration": "iteration {itr}",
    "ranking": "Tournament complete (iteration {itr}, {count} matches)",
    "meta_review": "Meta-review complete",
    "evolve": "{count} hypotheses evolved (iteration {itr})",
}

_MILESTONES: dict[str, dict[str, str]] = {
    "he": {
        "supervisor": "תוכנית המחקר מוכנה — המפקח סיים",
        "generate": "נוצרו {count} השערות ({label})",
        "label_initial": "ראשוני",
        "label_iteration": "איטרציה {itr}",
        "ranking": "הטורניר הושלם (איטרציה {itr}, {count} השוואות)",
        "meta_review": "מטא-סקירה הושלמה",
        "evolve": "{count} השערות עברו אבולוציה (איטרציה {itr})",
    },
}


def milestone_labels(code: str | None) -> dict[str, str]:
    """Return milestone format templates for a locale, defaulting to English."""
    base = (code or "").split("-")[0].lower()
    overrides = _MILESTONES.get(base, {})
    return {**_MILESTONES_EN, **overrides}
