"""Iterative-assumption-tree hypothesis generation (SSR §4, audits E12/K9).

The assumptions technique builds a bounded assumption/sub-assumption tree
before ideating, instead of asking for assumptions and hypotheses in one
structured call:

1. Level 0 decomposes the research area into its taken-for-granted
   assumptions and marks the load-bearing ones.
2. Level 1 decomposes the selected load-bearing parents into
   sub-assumptions, identified by positional index (schemas never echo
   input text back).
3. A final structured call generates hypotheses challenging the weakest
   nodes of the tree, via the shared ``GENERATION_SCHEMA`` shape, tagged
   ``GenerationMethod.ASSUMPTIONS``.

Every level is grounded in the run's retrieved literature context when a
reference index is available, and carries the research-expansion and
verified-wrong-assumption sections when those apply (see
``research_expansion`` and ``assumption_feedback``).

Depth and breadth are bounded by the constants below, so the technique
makes at most three LLM calls per batch regardless of what the model
returns; an empty tree degrades to the final call alone rather than
failing the strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.assumption_feedback import (
    build_falsified_assumptions_section,
)
from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    hypothesis_from_llm_output,
)
from co_scientist.agents.generation.research_expansion import (
    build_expansion_section,
)
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    MEDIUM_TEMPERATURE,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Tree bounds (E12): depth is two levels by construction (top + sub); the
# three widths bound breadth. Kept here, not in constants.py, because they
# are this technique's private shape, not a cross-agent parameter.
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
_FINAL_LEVEL_PARAMS = _AssumptionCallParams(
    prompt_name="generation_assumptions",
    max_tokens=EXTENDED_MAX_TOKENS,
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
) -> list[_AssumptionNode]:
    """Run the bounded level-0/level-1 tree calls and return the tree.

    An empty or failed level 0 yields an empty tree; the caller still
    runs the final generation call (the template covers the no-tree
    case), so the technique degrades instead of failing the strategy.
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
        return nodes
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
    return nodes


async def generate_with_assumptions(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> list[Hypothesis]:
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
        The generated hypotheses, tagged ``GenerationMethod.ASSUMPTIONS``.
    """
    reference_text, sources, literature_context = _resolve_assumptions_context(
        reference_index, articles_with_reasoning
    )
    nodes = await _build_assumption_tree(
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
    return hypotheses
