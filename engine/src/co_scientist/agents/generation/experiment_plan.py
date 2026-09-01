"""Formats a structured experiment-plan LLM response into prose.

R14-20 (docs/CORPUS-EXTRACTION.md): Google's published test plan is a
numbered pilot closing on separately bolded Go/No-Go criteria. The
generation/evolution LLM calls now ask for that structure
(schemas/generation.py's ``_EXPERIMENT_FIELD``: ``steps`` +
``go_criterion``/``no_go_criterion``), but ``Hypothesis.experiment``
itself stays a plain string -- the app's ``experimental_context`` TEXT
column, safety redaction (``hypothesis_safety.py``), and evolution's
prompt-context interpolation (``evolve_context.py``) all already treat
it as prose, and none of that needed to change. This module is the one
place that turns the structured response into that string; everything
downstream of ``Hypothesis.experiment`` is unaffected, and the
structured ``go_criterion``/``no_go_criterion`` keys cease to exist
once this returns -- there is no ``Hypothesis`` field for any gate to
read them from.

Under the json_object downgrade the model does not enforce the schema,
so ``format_experiment_plan`` treats every shape as possible: missing,
a bare string (a model that fell back to the old free-text shape), a
dict missing some keys, or a ``steps`` value that is not a list. It
degrades to the best text obtainable and never raises.
"""

from typing import Any

from co_scientist.constants import truncate
from co_scientist.schemas.generation import (
    _EXPERIMENT_CRITERION_CHARS,
    _EXPERIMENT_STEP_CHARS,
    MAX_EXPERIMENT_STEPS,
)


def _experiment_steps(raw: Any) -> list[str]:
    """Extracts and caps the plan's ordered steps from a raw LLM value.

    Args:
        raw: The ``steps`` value from parsed LLM JSON -- expected to be
            a list of strings, but never trusted to be.

    Returns:
        Up to ``MAX_EXPERIMENT_STEPS`` non-empty, length-capped steps,
        in order. Empty when ``raw`` is not a list.
    """
    if not isinstance(raw, list):
        return []
    steps: list[str] = []
    for step in raw:
        text = str(step).strip() if step is not None else ""
        if text:
            steps.append(truncate(text, _EXPERIMENT_STEP_CHARS))
        if len(steps) == MAX_EXPERIMENT_STEPS:
            break
    return steps


def format_experiment_plan(
    data: Any, fallback: str | None = None
) -> str | None:
    """Renders a structured experiment-plan response as markdown prose.

    Args:
        data: The raw ``experiment`` value from parsed LLM JSON --
            expected to be ``{"steps": [...], "go_criterion": ...,
            "no_go_criterion": ...}`` but never trusted to be.
        fallback: Text to fall back to (e.g. the hypothesis's own prior
            ``experiment``, for evolution's response-merge default) when
            ``data`` carries no usable content.

    Returns:
        Numbered steps followed by whichever of the separately bolded
        ``**Go:**``/``**No-Go:**`` lines are present; the stripped
        string as-is if the model answered with plain prose instead of
        the structure; ``fallback`` if nothing usable was found in
        ``data``; or ``None`` if there is no fallback either.
    """
    if isinstance(data, str):
        text = data.strip()
        return text or fallback
    if not isinstance(data, dict):
        return fallback
    steps = _experiment_steps(data.get("steps"))
    go = truncate(
        str(data.get("go_criterion") or "").strip(),
        _EXPERIMENT_CRITERION_CHARS,
    )
    no_go = truncate(
        str(data.get("no_go_criterion") or "").strip(),
        _EXPERIMENT_CRITERION_CHARS,
    )
    lines = [f"{i}. {step}" for i, step in enumerate(steps, start=1)]
    if go:
        lines.append(f"**Go:** {go}")
    if no_go:
        lines.append(f"**No-Go:** {no_go}")
    return "\n".join(lines) if lines else fallback
