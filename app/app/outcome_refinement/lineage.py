"""Single-parent child validation and persistence shape for refinements."""

from __future__ import annotations

from typing import Any

from co_scientist.models import Hypothesis

from app import store


def _child_row(run_id: str, child: Hypothesis) -> store.NewHypothesis:
    if child.parent_id is None or child.parent_ids != [child.parent_id]:
        raise ValueError(
            "targeted outcome refinement returned non-single lineage"
        )
    return store.NewHypothesis(
        run_id=run_id,
        hypothesis_id=child.id,
        parent_id=child.parent_id,
        parent_ids=[child.parent_id],
        generation=child.generation,
        creation_iteration=child.creation_iteration,
        category=child.category,
        title=child.title or child.text[:120],
        statement=child.text,
        mechanism=child.literature_grounding or "",
        expected_effect=child.explanation or "",
        experimental_context=child.experiment or "",
        introduction=child.introduction or "",
        recent_findings=child.recent_findings or "",
        safety_and_toxicity=child.safety_and_toxicity or "",
        created_by_agent="evolution",
    )


def _checkpointed_child(
    action: dict[str, Any],
    state: dict[str, Any],
    marker: dict[str, Any],
) -> Hypothesis | None:
    """Resolve and validate the child carried by the action checkpoint."""
    child_id = marker.get("child_hypothesis_id")
    child = next(
        (
            hypothesis
            for hypothesis in state.get("hypotheses", [])
            if hypothesis.id == child_id
        ),
        None,
    )
    if marker["kind"] == "child" and child is None:
        raise ValueError("checkpointed refinement child is missing")
    if child is not None and child.parent_id != action["hypothesis_id"]:
        raise ValueError("checkpointed refinement child has the wrong parent")
    return child


def _result_checkpoint_state(
    action: dict[str, Any],
    state: dict[str, Any],
    parent: Hypothesis,
    child: Hypothesis | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach single-parent lineage and form the durable action marker."""
    if child is None:
        return state, {
            "kind": "no_child",
            "action_id": action["action_id"],
            "outcome_id": action["outcome_id"],
            "hypothesis_id": action["hypothesis_id"],
            "child_hypothesis_id": None,
        }
    if child.parent_id != parent.id or child.parent_ids != [parent.id]:
        raise ValueError("targeted outcome evolution must return one parent")
    child.enrichments["outcome_refinement"] = {
        "action_id": action["action_id"],
        "outcome_id": action["outcome_id"],
        "parent_hypothesis_id": parent.id,
    }
    updated_state = {**state, "hypotheses": [*state["hypotheses"], child]}
    # Function-local: importing any ``app.engine_tasks`` submodule loads the
    # package, whose ``outcome_refinement`` imports this module, so a
    # top-level import is a cycle when this module loads first.
    from app.engine_tasks.support import NODE_TASK_PREFIX

    updated_state["resume_successor"] = f"{NODE_TASK_PREFIX}review"
    return updated_state, {
        "kind": "child",
        "action_id": action["action_id"],
        "outcome_id": action["outcome_id"],
        "hypothesis_id": action["hypothesis_id"],
        "child_hypothesis_id": child.id,
    }
