"""Proposing one child variant from one parent.

The call itself is unremarkable; the two things worth reading are what
happens to a patch that does not apply, and where the child's source
comes from.

**A patch that does not apply is a rejected child, not a retry.** V4A
context lines must match the parent character for character, so a failed
match means the model wrote its edit against something other than the
program it was shown. Re-asking produces the same mismatch, and applying
what did match would produce a child that is neither the parent nor the
proposal -- a program nobody wrote, scored, and bred from.

**The child's source is read back from disk, not reconstructed.** The
applier is the authority on what the patch did; deriving the child by
re-implementing the patch semantics here would give two answers to that
question, and they would diverge on exactly the edits that are hardest
to get right.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.code_evolve.context import (
    ParentVariant,
    objective_description,
    render_outcome,
    render_source,
    render_summary,
)
from co_scientist.agents.code_evolve.operators import (
    CodeOperator,
    instructions_for,
)
from co_scientist.code_eval.spec import EvaluatorSpec
from co_scientist.llm import call_llm_json
from co_scientist.llm_types import CompletionSpec
from co_scientist.patch import PatchError
from co_scientist.prompts import load_prompt_with_schema
from co_scientist.workspace.session import WorkspaceSession

logger = logging.getLogger(__name__)


class ProposalRejectedError(Exception):
    """Raised when a proposal cannot become a variant.

    Not a failure of the run: a rejected proposal is an ordinary outcome
    of asking a model for an exact-context patch, and the caller's job is
    to record it and move on, not to retry it into existence.
    """


@dataclass(frozen=True)
class VariantProposal:
    """A child variant the model proposed and the applier accepted.

    Attributes:
        operator: The move that was assigned.
        rationale: Why the model expects this edit to help.
        expected_effect: What it predicted, recorded before the run.
        patch: The envelope as written, kept so the lineage view can
            show the actual edit rather than a diff recomputed later.
        source: The resulting program, read back after application.
        changed: Paths the patch touched.
    """

    operator: CodeOperator
    rationale: str
    expected_effect: str
    patch: str
    source: dict[str, str]
    changed: tuple[str, ...]


def render_dataset(paths: Sequence[str]) -> str:
    """Names the read-only files the program may open, never their text.

    A manifest rather than content, for the reason the proximity node
    records: a prompt whose length scales with its input truncates
    silently at the far end. And naming them is not optional -- a model
    told nothing about the data writes a program that does not know it
    exists, so the run evolves against a file it never opens.
    """
    if not paths:
        return ""
    listed = "\n".join(f"- `{path}`" for path in paths)
    return (
        "## Data the program may read\n\n"
        "These files are placed in the working directory before every "
        "run, read-only inputs rather than part of the program. Do not "
        "add, move or rewrite them; open them.\n\n"
        f"{listed}\n\n"
    )


def build_prompt(
    parent: ParentVariant,
    *,
    operator: CodeOperator,
    evaluator: EvaluatorSpec,
    dataset_paths: Sequence[str] = (),
) -> tuple[str, dict[str, Any] | None]:
    """Renders the proposal prompt and its response schema."""
    return load_prompt_with_schema(
        "code_evolution",
        {
            "objective_description": objective_description(
                evaluator.objectives
            ),
            "objective_metric": ", ".join(
                f"`{item.metric}`" for item in evaluator.objectives
            ),
            "metrics_path": evaluator.metrics_path,
            "parent_summary": render_summary(parent),
            "parent_source": render_source(parent.source),
            "parent_outcome": render_outcome(parent),
            "operator_name": operator.value,
            "operator_instructions": instructions_for(operator),
            "dataset_manifest": render_dataset(dataset_paths),
        },
    )


def _write_parent(session: WorkspaceSession, source: dict[str, str]) -> None:
    """Materializes the parent program so the patch has something to hit."""
    for relative, contents in source.items():
        target = session.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")


def _read_back(
    session: WorkspaceSession, parent: dict[str, str]
) -> dict[str, str]:
    """Reads the post-patch program back out of the workspace.

    Restricted to the parent's files plus whatever the workspace now
    holds, so a patch that added a file is captured and one that deleted
    a file is too. Harness metadata is already excluded by ``list_files``.
    """
    del parent
    return {
        relative: session.read_file(relative)
        for relative in session.list_files()
    }


def apply_proposal(
    session: WorkspaceSession,
    parent_source: dict[str, str],
    patch_text: str,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Applies a proposed patch in a workspace and returns the child.

    Raises:
        ProposalRejectedError: If the envelope is malformed or any hunk's
            context does not match. Nothing was written in that case --
            the applier is all-or-nothing -- so the workspace is not left
            holding a half-edited program.
    """
    _write_parent(session, parent_source)
    try:
        outcome = session.apply_patch_text(patch_text)
    except PatchError as exc:
        raise ProposalRejectedError(f"patch did not apply: {exc}") from exc
    if not outcome.changed:
        raise ProposalRejectedError("patch applied but changed nothing")
    return _read_back(session, parent_source), outcome.changed


async def propose_variant(
    session: WorkspaceSession,
    parent: ParentVariant,
    *,
    operator: CodeOperator,
    evaluator: EvaluatorSpec,
    spec: CompletionSpec,
) -> VariantProposal:
    """Asks the model for one child of ``parent`` and applies it.

    Args:
        session: The child's own workspace, which the patch is applied in.
        parent: The variant being derived from.
        operator: The assigned move.
        evaluator: How the child will be scored -- the objective and the
            metrics path, so the prompt can state both.
        spec: Which model to call and how.

    Returns:
        The accepted child.

    Raises:
        ProposalRejectedError: If the model's patch does not apply.
    """
    prompt, schema = build_prompt(
        parent,
        operator=operator,
        evaluator=evaluator,
        dataset_paths=evaluator.dataset_paths,
    )
    response = await call_llm_json(
        prompt, dataclasses.replace(spec, json_schema=schema)
    )
    patch_text = str(response.get("patch") or "")
    if not patch_text.strip():
        raise ProposalRejectedError("model returned no patch")
    source, changed = apply_proposal(session, parent.source, patch_text)
    logger.info(
        "Variant proposal (%s) changed %s", operator.value, ", ".join(changed)
    )
    return VariantProposal(
        operator=operator,
        rationale=str(response.get("rationale") or ""),
        expected_effect=str(response.get("expected_effect") or ""),
        patch=patch_text,
        source=source,
        changed=changed,
    )
