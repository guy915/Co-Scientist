"""Assumption-guided generation and feedback from existing mature reviews."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    hypothesis_from_llm_output,
)
from co_scientist.agents.generation.expansion_research import (
    build_expansion_section,
)
from co_scientist.constants import (
    DEEP_HYPOTHESIS_MAX_TOKENS,
    DEFAULT_MAX_TOKENS,
    LOW_TEMPERATURE,
    MEDIUM_TEMPERATURE,
    truncate,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts._common import (
    _format_meta_review_context,
    format_lab_constraints_section,
)
from co_scientist.prompts.generation_draft import (
    _build_citation_reference_section,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

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


# Tree bounds (E12): depth is two levels by construction (top + sub); the
# three widths bound breadth. Kept here, not in the constants package, because
# they are this technique's private shape, not a cross-agent parameter.
ASSUMPTION_TREE_MAX_TOP = 6
ASSUMPTION_TREE_MAX_LOAD_BEARING = 3
ASSUMPTION_TREE_MAX_SUB_PER_PARENT = 3


@dataclass
class _AssumptionNode:
    """One node of the assumption tree built by the technique.

    Attributes:
        text: The assumption statement.
        load_bearing: Whether level 0 marked the assumption load-bearing.
        sub_assumptions: Level-1 decompositions (parents only).
    """

    text: str
    load_bearing: bool = False
    sub_assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _AssumptionCallParams:
    """Per-level call settings for one structured assumption call.

    Attributes:
        prompt_name: Debug-artifact name for the call.
        max_tokens: Output token budget for this level.
        temperature: Sampling temperature for this level.
    """

    prompt_name: str
    max_tokens: int
    temperature: float


# The analysis levels decompose faithfully rather than diversely, so they
# run cool; the final ideation call keeps the technique's historical
# medium temperature.
_TREE_LEVEL_PARAMS = _AssumptionCallParams(
    prompt_name="generation_assumption_tree",
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=LOW_TEMPERATURE,
)
_SUB_LEVEL_PARAMS = _AssumptionCallParams(
    prompt_name="generation_assumption_sub",
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=LOW_TEMPERATURE,
)
# K6: the final ideation call writes the hypotheses at full depth
# (mechanism specificity, quantitative predictions, complete experiment
# detail), so it is funded by the deep-generation budget rather than the
# generic extended one.
_FINAL_LEVEL_PARAMS = _AssumptionCallParams(
    prompt_name="generation_assumptions",
    max_tokens=DEEP_HYPOTHESIS_MAX_TOKENS,
    temperature=MEDIUM_TEMPERATURE,
)


def _resolve_assumptions_context(
    reference_index: ReferenceIndex | None,
    articles_with_reasoning: str | None,
) -> tuple[str, dict[str, dict[str, Any]], str]:
    """Resolve the reference text/sources/literature-context for one call.

    Prose literature context is admitted only alongside a real (non-empty)
    reference index, so a stale degraded-mode summary string can never leak
    in.

    Returns:
        Tuple of (reference_text, sources, literature_context).
    """
    if reference_index is not None and not reference_index.is_empty():
        reference_text = reference_index.text
        sources: dict[str, dict[str, Any]] = reference_index.sources
        has_references = True
    else:
        reference_text = ""
        sources = {}
        has_references = False

    literature_context = (
        "Relevant findings from the literature review:\n"
        f"{articles_with_reasoning}\n"
        if has_references and articles_with_reasoning
        else ""
    )
    return reference_text, sources, literature_context


def _parse_top_assumptions(response: dict[str, Any]) -> list[_AssumptionNode]:
    """Parse and bound the level-0 assumption list from the LLM response.

    Args:
        response: Parsed ``ASSUMPTION_TREE_SCHEMA`` response.

    Returns:
        Up to ``ASSUMPTION_TREE_MAX_TOP`` assumption nodes, in the order
        the model returned them.
    """
    nodes: list[_AssumptionNode] = []
    for entry in response.get("assumptions") or []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("assumption") or "").strip()
        if not text:
            continue
        nodes.append(
            _AssumptionNode(
                text=text, load_bearing=bool(entry.get("load_bearing"))
            )
        )
        if len(nodes) >= ASSUMPTION_TREE_MAX_TOP:
            break
    return nodes


def _select_parents(nodes: list[_AssumptionNode]) -> list[_AssumptionNode]:
    """Select the load-bearing assumptions expanded at level 1.

    Args:
        nodes: The level-0 assumption nodes.

    Returns:
        Up to ``ASSUMPTION_TREE_MAX_LOAD_BEARING`` nodes marked
        load-bearing, in tree order. An empty list means no level-1 call.
    """
    parents = [node for node in nodes if node.load_bearing]
    return parents[:ASSUMPTION_TREE_MAX_LOAD_BEARING]


def _parse_sub_assumptions(
    response: dict[str, Any], parents: list[_AssumptionNode]
) -> None:
    """Attach level-1 sub-assumptions to their parents, in place.

    Entries name their parent by positional index. An index outside the
    parent list wraps modulo its length, so a filler (or a miscounting
    model) that emits a fixed out-of-range index still yields a
    deterministic, satisfiable tree instead of a discarded level.

    Args:
        response: Parsed ``ASSUMPTION_SUB_SCHEMA`` response.
        parents: The level-0 nodes selected for expansion; mutated.
    """
    if not parents:
        return
    for entry in response.get("parents") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("parent_index")
        if not isinstance(index, int):
            continue
        parent = parents[index % len(parents)]
        subs = [
            str(sub).strip()
            for sub in (entry.get("sub_assumptions") or [])
            if str(sub).strip()
        ]
        remaining = ASSUMPTION_TREE_MAX_SUB_PER_PARENT - len(
            parent.sub_assumptions
        )
        parent.sub_assumptions.extend(subs[: max(0, remaining)])


def _render_tree_section(nodes: list[_AssumptionNode]) -> str:
    """Render the assumption tree as the final call's prompt section.

    Args:
        nodes: The full level-0 node list (parents carry their subs).

    Returns:
        The numbered tree block, or "" when the tree is empty (the
        template then instructs the model to identify assumptions
        itself, preserving the historical single-call behavior).
    """
    if not nodes:
        return ""
    lines = [
        "## Assumption Tree (from the earlier analysis levels)\n",
    ]
    for index, node in enumerate(nodes):
        marker = " (load-bearing)" if node.load_bearing else ""
        lines.append(f"{index}. {node.text}{marker}\n")
        for sub_index, sub in enumerate(node.sub_assumptions):
            lines.append(f"   {index}.{sub_index + 1} {sub}\n")
    lines.append("\n")
    return "".join(lines)


def _build_tree_prompt(
    state: WorkflowState,
    reference_text: str,
    literature_context: str,
) -> tuple[str, Any]:
    """Build the level-0 assumption-decomposition prompt/schema."""
    return load_prompt_with_schema(
        "generation_assumption_tree",
        {
            "research_goal": state["research_goal"],
            "max_top_assumptions": ASSUMPTION_TREE_MAX_TOP,
            "meta_review_context": _format_meta_review_context(
                state.get("meta_review")
            ),
            "domain_context": "",
            "citation_reference_section": _build_citation_reference_section(
                reference_text
            ),
            "literature_context": literature_context,
            "research_expansion_section": build_expansion_section(state),
            "falsified_assumptions_section": (
                build_falsified_assumptions_section(state.get("hypotheses"))
            ),
        },
    )


def _build_sub_prompt(
    state: WorkflowState,
    parents: list[_AssumptionNode],
    reference_text: str,
    literature_context: str,
) -> tuple[str, Any]:
    """Build the level-1 sub-assumption prompt/schema for the parents.

    Parents are listed by numbered index; the response identifies them
    positionally rather than echoing their text back.
    """
    parents_list = "".join(
        f"{index}. {parent.text}\n" for index, parent in enumerate(parents)
    )
    return load_prompt_with_schema(
        "generation_assumption_sub",
        {
            "research_goal": state["research_goal"],
            "parents_list": parents_list,
            "max_sub_per_parent": ASSUMPTION_TREE_MAX_SUB_PER_PARENT,
            "domain_context": "",
            "citation_reference_section": _build_citation_reference_section(
                reference_text
            ),
            "literature_context": literature_context,
        },
    )


def _build_assumptions_prompt(
    state: WorkflowState,
    count: int,
    reference_text: str,
    literature_context: str,
    tree_section: str,
) -> tuple[str, Any]:
    """Build the final hypothesis-generation prompt/schema for the tree."""
    return load_prompt_with_schema(
        "generation_assumptions",
        {
            "research_goal": state["research_goal"],
            "num_hypotheses": count,
            "meta_review_context": _format_meta_review_context(
                state.get("meta_review")
            ),
            "domain_context": "",
            "citation_reference_section": _build_citation_reference_section(
                reference_text
            ),
            # Empty when the run carries no lab constraints (K5), which
            # leaves the prompt exactly as it rendered before.
            "lab_constraints_section": format_lab_constraints_section(
                state.get("lab_constraints")
            ),
            "literature_context": literature_context,
            "assumption_tree_section": tree_section,
            "research_expansion_section": build_expansion_section(state),
            "falsified_assumptions_section": (
                build_falsified_assumptions_section(state.get("hypotheses"))
            ),
        },
    )


async def _call_assumptions_llm(
    state: WorkflowState,
    prompt: str,
    schema: Any,
    params: _AssumptionCallParams,
) -> dict[str, Any]:
    """Issue one structured call of the assumptions technique.

    Args:
        state: Workflow state supplying the model name and run id.
        prompt: The rendered prompt for this level.
        schema: The JSON schema the response must satisfy.
        params: This level's call settings.

    Returns:
        The parsed JSON response.
    """
    return await call_llm_json(
        prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=params.max_tokens,
            temperature=params.temperature,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            # Never cached, matching the debate and tool-drafting strategies.
            # Generation fans out one durable task per hypothesis, so several
            # tasks issue this call with an identical prompt and rely on
            # sampling to explore different ideas. A cache hit would serve
            # them all the same hypothesis, and the state reducer dedupes on
            # append -- so the run would quietly commit one hypothesis where
            # the tier asked for several, with nothing failing to show it.
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name=params.prompt_name,
        ),
    )


async def _build_assumption_tree(
    state: WorkflowState,
    reference_text: str,
    literature_context: str,
) -> tuple[list[_AssumptionNode], int]:
    """Run the bounded level-0/level-1 tree calls and return the tree.

    An empty or failed level 0 yields an empty tree; the caller still
    runs the final generation call (the template covers the no-tree
    case), so the technique degrades instead of failing the strategy.

    Returns:
        Tuple of (nodes, llm_call_count): llm_call_count is 1 for the
        level-0 call, plus 1 more when a level-1 call ran (finding L3).
    """
    prompt, schema = _build_tree_prompt(
        state, reference_text, literature_context
    )
    response = await _call_assumptions_llm(
        state, prompt, schema, _TREE_LEVEL_PARAMS
    )
    nodes = _parse_top_assumptions(response)
    logger.info(
        "Assumption tree level 0: %s assumptions (%s load-bearing)",
        len(nodes),
        sum(1 for node in nodes if node.load_bearing),
    )

    parents = _select_parents(nodes)
    if not parents:
        return nodes, 1
    sub_prompt, sub_schema = _build_sub_prompt(
        state, parents, reference_text, literature_context
    )
    sub_response = await _call_assumptions_llm(
        state, sub_prompt, sub_schema, _SUB_LEVEL_PARAMS
    )
    _parse_sub_assumptions(sub_response, parents)
    logger.info(
        "Assumption tree level 1: %s parents, %s sub-assumptions",
        len(parents),
        sum(len(parent.sub_assumptions) for parent in parents),
    )
    return nodes, 2


async def generate_with_assumptions(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> tuple[list[Hypothesis], int]:
    """Generate ``count`` hypotheses by interrogating an assumption tree.

    Builds the bounded assumption/sub-assumption tree first (E12), then
    generates hypotheses challenging its weakest nodes. Grounds every
    level's claims in the supplied references so ``literature_grounding``
    cites real ``[C*]`` keys rather than inventing citations (SSR §4);
    with no reference index (the degraded LLM-only path) the levels run
    on the model's own knowledge.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to generate.
        articles_with_reasoning: Literature-review synthesis text, when a
            review ran.
        reference_index: Citation key -> source mapping, when available.

    Returns:
        Tuple of (hypotheses, llm_call_count): hypotheses are tagged
        ``GenerationMethod.ASSUMPTIONS``; llm_call_count is every real
        completion this technique spent -- the tree call(s) plus the
        final ideation call (finding L3 -- this technique previously
        reported no llm_calls at all).
    """
    reference_text, sources, literature_context = _resolve_assumptions_context(
        reference_index, articles_with_reasoning
    )
    nodes, tree_calls = await _build_assumption_tree(
        state, reference_text, literature_context
    )
    tree_section = _render_tree_section(nodes)
    prompt, schema = _build_assumptions_prompt(
        state, count, reference_text, literature_context, tree_section
    )
    response = await _call_assumptions_llm(
        state, prompt, schema, _FINAL_LEVEL_PARAMS
    )
    raw: list[dict[str, Any]] = response.get("hypotheses", [])
    hypotheses = [
        hypothesis_from_llm_output(h, sources, GenerationMethod.ASSUMPTIONS)
        for h in raw
    ]
    logger.info(
        "Assumptions generation produced %s hypotheses from a %s-node tree",
        len(hypotheses),
        len(nodes),
    )
    return hypotheses, tree_calls + 1
