"""What a proposal is shown about its parent.

Kept apart from the call itself because these choices are where a
proposal quietly goes wrong -- an outcome summary that omits the error,
a program truncated in the middle of the function being edited -- and
they are worth reading without the LLM plumbing around them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Ceiling on how much of the parent program is shown. A patch's context
# lines must match the source character for character, so a program
# truncated mid-file produces edits anchored to text the applier will
# never find. The ceiling is therefore high enough that real programs
# arrive whole, and truncation is a loud fallback rather than routine.
MAX_SOURCE_CHARS = 60_000

# Ceiling per captured artifact. A traceback's last lines name the
# defect; its first lines are usually framework noise -- so when one is
# too long, the tail is what is kept.
MAX_ARTIFACT_CHARS = 4_000


@dataclass(frozen=True)
class ParentVariant:
    """The variant a proposal is deriving a child from.

    Attributes:
        source: The whole parent program, ``{path: contents}``.
        status: How its evaluation ended.
        fitness: Its sign-corrected score, None if it never got one.
        metrics: What it reported, raw.
        artifacts: What its failure left behind.
        ordinal: Its attempt number within the run, for the prompt.
    """

    source: dict[str, str]
    status: str = "pending"
    fitness: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    ordinal: int = 0

    @property
    def failed(self) -> bool:
        """Reports whether the parent produced no usable score.

        Defined on fitness rather than on status because that is the
        question the operator choice actually turns on: a variant that
        ran to completion and wrote no metrics is as unusable a parent
        as one that crashed, and both need repairing before anything
        else is worth trying.
        """
        return self.fitness is None


def _tail(text: str, limit: int) -> str:
    """Keeps the last ``limit`` characters, marking what was dropped."""
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters omitted ...]\n{text[-limit:]}"


def render_source(source: dict[str, str]) -> str:
    """Renders the parent program as fenced, path-labelled blocks.

    Files are ordered by path so a run's prompts stay comparable to each
    other, and each block is labelled with the path the patch must name.
    """
    blocks = []
    budget = MAX_SOURCE_CHARS
    for path in sorted(source):
        body = source[path]
        if len(body) > budget:
            body = body[:budget] + "\n[... truncated ...]"
        budget -= len(body)
        blocks.append(f"### `{path}`\n\n```\n{body}\n```")
        if budget <= 0:
            break
    return "\n\n".join(blocks)


def render_outcome(parent: ParentVariant) -> str:
    """Renders what the parent's run produced, failures included.

    A failed parent's captured output is the whole reason the repair
    operator can do anything, so it is rendered in full-ish detail
    rather than reduced to "the run failed".
    """
    if not parent.source:
        return "This is the first variant; there is no prior run."
    lines = [f"Status: `{parent.status}`."]
    if parent.fitness is not None:
        lines.append(f"Fitness (higher is better): {parent.fitness}.")
    if parent.metrics:
        reported = ", ".join(
            f"`{name}` = {value}"
            for name, value in sorted(parent.metrics.items())
        )
        lines.append(f"Reported metrics: {reported}.")
    else:
        lines.append("It reported no metrics.")
    for kind, content in sorted(parent.artifacts.items()):
        lines.append(
            f"\nCaptured `{kind}`:\n\n```\n"
            f"{_tail(content, MAX_ARTIFACT_CHARS)}\n```"
        )
    return "\n".join(lines)


def render_summary(parent: ParentVariant) -> str:
    """One line naming which attempt this program came from."""
    if not parent.source:
        return "Starting program (attempt 1)."
    return f"Program from attempt {parent.ordinal}."


def objective_description(objective: Any) -> str:
    """Describes the objective in the direction the model should read it."""
    goal = (
        "as large as possible"
        if objective.direction.value == "maximize"
        else "as small as possible"
    )
    return f"Make the reported metric `{objective.metric}` {goal}."
