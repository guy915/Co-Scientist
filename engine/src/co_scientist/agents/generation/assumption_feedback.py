"""Verified-wrong assumptions fed back into generation (audit K9).

Deep verification decomposes each leading hypothesis into assumptions and
probes them; when a non-fundamental assumption fails, the idea survives
(verdict "weakened") but nothing told later generation about the failure,
so fresh cycles kept rebuilding on the same broken ground.

This module is the engine-side record plus the generation-side
consumption: it derives the falsified non-fundamental assumptions from
the probes already stored on hypotheses (no new state channel) and
renders the "avoid or rework these assumptions" guidance block that the
generation prompts splice in. Two probe records are admitted:

- an explicit per-probe ``assumption_holds: False`` boolean, which the
  verification schema does not carry today but may gain; the reader is
  forward-compatible with it.
- for a hypothesis whose verdict is "weakened" -- the verifier's own
  wording for "non-fundamental gaps" -- its non-fundamental probes,
  which are exactly the assumptions the verdict says failed.

Fundamental failures are excluded: this record is the "assumptions that
don't kill the idea" channel, and a fundamental failure is reported
through the verdict itself, which travels on the hypothesis and reaches
the reader ("undermined" demotes the idea rather than removing it -- see
``Hypothesis.is_undermined``). Evolution is the other intended consumer;
it reads the same record through this module (see its prompt builder).
"""

import logging
from typing import Any

from co_scientist.constants import truncate
from co_scientist.models import Hypothesis

logger = logging.getLogger(__name__)

# How much of the record reaches one prompt: six probe lines covers the
# weakened leaders of a tournament without competing with the ideation
# the prompt is actually asking for.
MAX_FALSIFIED_ASSUMPTION_LINES = 6

_PROBE_FIELD_CHARS = 240


def _probe_explicitly_falsified(probe: dict[str, Any]) -> bool | None:
    """Reads an explicit per-probe correctness record when one exists.

    Args:
        probe: One deep-verification probe entry.

    Returns:
        True if the probe records the assumption as falsified
        (``assumption_holds: False``), False if it records it as
        holding, None when the probe carries no explicit record.
    """
    holds = probe.get("assumption_holds")
    if isinstance(holds, bool):
        return not holds
    return None


def _probe_admitted(probe: dict[str, Any], verdict: str | None) -> bool:
    """Decides whether one probe belongs in the falsified-assumption record.

    Fundamental probes never qualify (their failure kills the idea, which
    is a different channel). An explicit ``assumption_holds`` record is
    authoritative in both directions; without one, only probes of a
    "weakened" hypothesis are admitted -- that verdict is the verifier's
    statement that non-fundamental assumptions failed, and these are the
    probes of those assumptions.
    """
    if probe.get("assumption_is_fundamental"):
        return False
    explicit = _probe_explicitly_falsified(probe)
    if explicit is not None:
        return explicit
    return verdict == "weakened"


def _format_probe_line(probe: dict[str, Any]) -> str:
    """Renders one falsified probe as a single guidance line."""
    question = truncate(
        str(probe.get("question") or "").strip(), _PROBE_FIELD_CHARS
    )
    answer = truncate(
        str(probe.get("answer") or "").strip(), _PROBE_FIELD_CHARS
    )
    if answer:
        return f"{question} -- finding: {answer}"
    return question


def _falsified_lines_for_hypothesis(hypothesis: Hypothesis) -> list[str]:
    """Renders the admitted falsified-probe lines for one hypothesis."""
    probes = hypothesis.deep_verification_probes
    if not probes:
        return []
    verdict = hypothesis.deep_verification_verdict
    return [
        _format_probe_line(probe)
        for probe in probes
        if _probe_admitted(probe, verdict)
    ]


def falsified_nonfundamental_assumptions(
    hypotheses: list[Hypothesis],
) -> list[str]:
    """Collects the run's falsified non-fundamental assumptions.

    Args:
        hypotheses: The run's hypothesis pool (any order; the record is
            prompt guidance, not a ranking input).

    Returns:
        One guidance line per admitted probe, capped at
        ``MAX_FALSIFIED_ASSUMPTION_LINES``. Empty until deep verification
        has weakened at least one hypothesis.
    """
    lines: list[str] = []
    for hypothesis in hypotheses:
        lines.extend(_falsified_lines_for_hypothesis(hypothesis))
        if len(lines) >= MAX_FALSIFIED_ASSUMPTION_LINES:
            logger.info(
                "Falsified-assumption guidance capped at %s lines",
                MAX_FALSIFIED_ASSUMPTION_LINES,
            )
            return lines[:MAX_FALSIFIED_ASSUMPTION_LINES]
    return lines


def build_falsified_assumptions_section(
    hypotheses: list[Hypothesis] | None,
) -> str:
    """Renders the avoid-or-rework guidance block for generation prompts.

    Args:
        hypotheses: The run's hypothesis pool, or None.

    Returns:
        The rendered block, or an empty string when no assumption has
        been verified wrong yet (the prompt placeholder then renders
        nothing).
    """
    lines = falsified_nonfundamental_assumptions(hypotheses or [])
    if not lines:
        return ""
    bullets = "".join(f"- {line}\n" for line in lines)
    return (
        "## Assumptions Verified Incorrect (avoid or rework)\n\n"
        "Verification in this run already found these non-fundamental"
        " assumptions incorrect. Do not build new hypotheses on them;"
        " avoid them or rework around them:\n"
        f"{bullets}\n"
    )
