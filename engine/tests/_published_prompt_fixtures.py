"""The fixture every published-prompt counterpart is rendered from.

The earlier corpus study measured word coverage against the *static* template
files under ``prompts/templates/``. That is wrong in both directions: published
text can live in a Python builder rather than the template (until 2026-09-06
``prompts/ranking.py::_format_review_context`` carried the "Disregard these
scores" sentence that ``ranking.md`` had no literal match for; both the function
and that template are now gone, and the sentence is static text in
``ranking_pairwise.md`` and ``ranking_debate.md``), and template text can be a
slot that never renders. The fixture here therefore exists to drive the real
builders, in ``_published_prompt_renders.py``, with input realistic enough that
the text they return is the text that would go on the wire.

Every ``{{slot}}`` must fill with realistic, non-empty content, including
the ones that render nothing when their input is absent (review scores,
deep verification, mature reviews, partners, supervisor guidance). A slot
left empty here would read as a missing published sentence, which is why
``test_every_slot_rendered`` fails first on a leftover ``{{`` marker.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from co_scientist.prompts import PromptRunContext
from tests._state import make_article, make_hypothesis, make_review

GOAL = (
    "Identify a repurposable approved drug that suppresses hepatic"
    " fibrosis progression in patients with metabolic dysfunction-"
    "associated steatohepatitis."
)

PREFERENCES = (
    "Prefer mechanisms testable in a 12-week rodent model, with an"
    " approved compound and a measurable serum readout."
)

CRITERIA = [
    "Mechanistic specificity over correlative association",
    "Feasibility within a single academic laboratory",
    "Falsifiable within twelve weeks",
]

INSTRUCTIONS = (
    "Prioritise mechanisms with an existing clinical safety record and"
    " state the pilot readout that would settle each proposal."
)

ATTRIBUTES = ["novel", "testable", "mechanistically specific"]

ARTICLES_WITH_REASONING = (
    "Analysis 1 (2024, Hepatology): TGF-beta1 driven myofibroblast"
    " activation remains the dominant fibrogenic axis; the authors note"
    " that integrin alpha-v beta-6 blockade was never tested alongside"
    " an approved antifibrotic. Reasoning: this is an unexplored"
    " combination.\n"
    "Analysis 2 (2023, J Hepatol): pirfenidone reduced collagen"
    " deposition in a murine CCl4 model but was not evaluated in a"
    " steatohepatitis background. Reasoning: the model gap is the"
    " opening."
)

TRANSCRIPT = (
    "Expert 1: I propose integrin alpha-v beta-6 blockade combined with"
    " a low-dose approved antifibrotic.\n"
    "Expert 2: The combination is plausible, but the readout must"
    " separate lipotoxic injury from fibrogenesis."
)

HYPOTHESIS_TEXT = (
    "Low-dose pirfenidone combined with integrin alpha-v beta-6"
    " blockade suppresses hepatic myofibroblast activation in a"
    " steatohepatitis background, lowering serum PRO-C3 by at least"
    " thirty percent at twelve weeks."
)

PARTNER_TEXT = (
    "Selective ASK1 inhibition reduces hepatocyte apoptosis and"
    " secondarily lowers stellate-cell activation."
)

REFERENCE_LIST = (
    "[P1] Integrin alpha-v beta-6 in liver fibrosis (2024)\n"
    "[P2] Pirfenidone in experimental steatohepatitis (2023)"
)


@dataclasses.dataclass(frozen=True)
class _PromptsConfig:
    """Stands in for the tools-config domain block."""

    domain_context: str = (
        "You work in translational hepatology; assume access to rodent"
        " models and standard serum assays."
    )
    generation_guidance: str = (
        "Favour mechanisms with an approved compound already available."
    )
    review_guidance: str = (
        "Weigh translational plausibility alongside mechanistic novelty."
    )
    evolution_guidance: str = (
        "Refinements should stay implementable in an academic laboratory."
    )
    reflection_guidance: str = (
        "Treat rodent-only evidence as suggestive, not established."
    )


class ToolRegistry:
    """The shipped tool registry with the domain slots populated.

    Tool instructions come from the real default config, so the rendered
    prompt carries the tool block a production run would see; only the
    ``domain_*`` slots are overridden, because the shipped config leaves
    them empty and an empty slot would be indistinguishable from a
    missing published sentence.
    """

    def __init__(self) -> None:
        from co_scientist.config import get_tool_registry

        self._registry = get_tool_registry()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._registry, name)

    def get_prompts_config(self) -> _PromptsConfig:
        return _PromptsConfig()


SUPERVISOR_GUIDANCE: dict[str, Any] = {
    "research_goal_analysis": {
        "key_areas": [
            "myofibroblast activation",
            "drug repurposing safety record",
        ]
    },
    "workflow_plan": {
        "generation_phase": {
            "focus_areas": ["approved antifibrotics"],
            "diversity_requirements": ["one non-hepatic analogy"],
        },
        "evolution_phase": {
            "refinement_priorities": ["tighten the pilot readout"],
            "iteration_strategy": "deepen the two leading mechanisms",
        },
    },
}

META_REVIEW: dict[str, Any] = {
    "common_strengths": ["clear mechanistic framing"],
    "common_weaknesses": ["pilot thresholds are frequently unstated"],
    "strategic_recommendations": [
        "state a quantitative Go/No-Go for every proposal"
    ],
    "emerging_themes": ["integrin-directed antifibrotic combinations"],
    "covered_areas": ["stellate-cell biology"],
    "open_directions": ["biliary contributions to fibrogenesis"],
}


def run_context() -> PromptRunContext:
    return PromptRunContext(
        supervisor_guidance=SUPERVISOR_GUIDANCE,
        meta_review=META_REVIEW,
        tool_registry=ToolRegistry(),
        run_setup_guidance="This run targets a twelve-week pilot.",
        run_focus_guidance="Keep every proposal repurposing-first.",
        preferences=PREFERENCES,
    )


def articles() -> list[Any]:
    return [
        make_article(
            title="Integrin alpha-v beta-6 in liver fibrosis",
            authors=["Okada", "Ruiz"],
            year=2024,
            source_id="P1",
            used_in_analysis=True,
        ),
        make_article(
            title="Pirfenidone in experimental steatohepatitis",
            authors=["Delacroix"],
            year=2023,
            source_id="P2",
            used_in_analysis=True,
        ),
    ]


def reviewed_hypothesis(text: str, label: str) -> Any:
    """Build a hypothesis carrying every signal ranking can surface."""
    hypothesis = make_hypothesis(
        text=text,
        title=f"{label} mechanism",
        reviews=[make_review()],
        reflection_notes=(
            f"Classification: missing piece. {label} explains the"
            " unexplained PRO-C3 plateau reported in the 2024 cohort."
        ),
        deep_verification_probes=[
            {
                "question": (
                    "Does integrin blockade reach hepatic stellate"
                    " cells at tolerated doses?"
                ),
                "answer": "Yes in rodents; human exposure is untested.",
                "reasoning": "Rodent PK covers the target compartment.",
                "assumption_is_fundamental": True,
            }
        ],
        deep_verification_verdict="holds",
    )
    hypothesis.enrichments["full"] = {
        "verdict": "accepted",
        "justification": (
            f"{label}'s causal chain survives the literature check."
        ),
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "holds",
        "decisive_step": "stellate-cell deactivation at week six",
        "failure_points": ["off-target integrin engagement"],
    }
    return hypothesis


@dataclasses.dataclass(frozen=True)
class Counterpart:
    """One rendered prompt of ours that claims a published source."""

    name: str
    builder_chain: str
    text: str


@dataclasses.dataclass(frozen=True)
class Rendered:
    """Every counterpart of one published prompt.

    ``primary`` is the counterpart whose internal ordering the fidelity
    tests check; ``union`` is every counterpart's text concatenated, which
    is what a presence check runs against when the README maps one
    published prompt onto two of ours.
    """

    published: str
    counterparts: tuple[Counterpart, ...]

    @property
    def primary(self) -> Counterpart:
        return self.counterparts[0]

    @property
    def union(self) -> str:
        return "\n".join(part.text for part in self.counterparts)
