"""Proposing code variants: operator choice and patch acceptance.

The cases that matter are the rejections. A proposal that half-applies,
or that is retried into existence, produces a child nobody wrote -- and
one that looks perfectly ordinary in the lineage view.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from co_scientist.agents.code_evolve import (
    CodeOperator,
    ParentVariant,
    ProposalRejectedError,
    apply_proposal,
    build_prompt,
    instructions_for,
    select_operator,
)
from co_scientist.code_eval import (
    Direction,
    EvaluationStage,
    EvaluatorSpec,
    Objective,
)
from co_scientist.workspace.session import WorkspaceSession

_PARENT = (
    "def solve(n):\n"
    "    total = 0\n"
    "    for i in range(n):\n"
    "        total += i\n"
    "    return total\n"
)


@pytest.fixture
def session(tmp_path: Path) -> WorkspaceSession:
    return WorkspaceSession(tmp_path / "variant")


def _spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        stages=(EvaluationStage(name="run", argv=("python", "main.py")),),
        objective=Objective(metric="score", direction=Direction.MAXIMIZE),
    )


def test_a_failed_parent_forces_repair() -> None:
    # Every other move is wasted on a program that does not run.
    for _ in range(20):
        assert select_operator(parent_failed=True) is CodeOperator.REPAIR


def test_a_working_parent_never_draws_repair() -> None:
    rng = random.Random(0)
    drawn = {select_operator(parent_failed=False, rng=rng) for _ in range(200)}
    assert CodeOperator.REPAIR not in drawn


def test_the_deck_reaches_every_other_operator() -> None:
    # A deck that in practice only plays one move is the failure this
    # whole mechanism exists to prevent, so the draw is checked rather
    # than assumed from the weights.
    rng = random.Random(7)
    drawn = {select_operator(parent_failed=False, rng=rng) for _ in range(500)}
    assert drawn == set(CodeOperator) - {CodeOperator.REPAIR}


def test_every_operator_has_instructions() -> None:
    for operator in CodeOperator:
        assert instructions_for(operator).strip()


def test_the_prompt_carries_the_program_and_the_move() -> None:
    parent = ParentVariant(source={"main.py": _PARENT}, fitness=1.0, ordinal=3)
    prompt, schema = build_prompt(
        parent, operator=CodeOperator.VECTORIZE, evaluator=_spec()
    )
    assert "for i in range(n)" in prompt
    assert "vectorize" in prompt
    assert instructions_for(CodeOperator.VECTORIZE)[:40] in prompt
    assert schema is not None


def test_the_prompt_states_the_objective_direction() -> None:
    spec = EvaluatorSpec(
        stages=(EvaluationStage(name="run", argv=("python", "main.py")),),
        objective=Objective(metric="latency", direction=Direction.MINIMIZE),
    )
    prompt, _ = build_prompt(
        ParentVariant(source={"main.py": _PARENT}),
        operator=CodeOperator.TARGETED_EDIT,
        evaluator=spec,
    )
    assert "as small as possible" in prompt
    assert "latency" in prompt


def test_the_prompt_shows_a_failed_parents_error() -> None:
    # The repair operator can only act on what the prompt carries.
    parent = ParentVariant(
        source={"main.py": _PARENT},
        status="failed",
        artifacts={"stderr": "NameError: name 'np' is not defined"},
    )
    prompt, _ = build_prompt(
        parent, operator=CodeOperator.REPAIR, evaluator=_spec()
    )
    assert "NameError: name 'np' is not defined" in prompt


def test_an_applying_patch_yields_the_child_source(
    session: WorkspaceSession,
) -> None:
    patch = (
        "*** Begin Patch\n"
        "*** Update File: main.py\n"
        "@@ def solve(n):\n"
        "-    total = 0\n"
        "+    total = 1\n"
        "*** End Patch\n"
    )
    source, changed = apply_proposal(session, {"main.py": _PARENT}, patch)
    assert changed == ("main.py",)
    assert "total = 1" in source["main.py"]
    assert "for i in range(n)" in source["main.py"]


def test_a_patch_whose_context_does_not_match_is_rejected(
    session: WorkspaceSession,
) -> None:
    # Written against something other than the program it was shown, so
    # retrying reproduces the mismatch and applying it partially would
    # produce a program nobody wrote.
    patch = (
        "*** Begin Patch\n"
        "*** Update File: main.py\n"
        "@@ def solve(n):\n"
        "-    total = 99999\n"
        "+    total = 1\n"
        "*** End Patch\n"
    )
    with pytest.raises(ProposalRejectedError):
        apply_proposal(session, {"main.py": _PARENT}, patch)


def test_a_rejected_patch_leaves_the_parent_untouched(
    session: WorkspaceSession,
) -> None:
    patch = (
        "*** Begin Patch\n"
        "*** Update File: main.py\n"
        "@@ def solve(n):\n"
        "-    total = 0\n"
        "+    total = 1\n"
        "*** Update File: main.py\n"
        "@@ def solve(n):\n"
        "-    nothing like this exists\n"
        "+    replacement\n"
        "*** End Patch\n"
    )
    with pytest.raises(ProposalRejectedError):
        apply_proposal(session, {"main.py": _PARENT}, patch)
    assert session.read_file("main.py") == _PARENT


def test_a_malformed_envelope_is_rejected(
    session: WorkspaceSession,
) -> None:
    with pytest.raises(ProposalRejectedError):
        apply_proposal(session, {"main.py": _PARENT}, "just some prose")


def test_a_patch_that_adds_a_file_carries_it_into_the_child(
    session: WorkspaceSession,
) -> None:
    patch = (
        "*** Begin Patch\n"
        "*** Add File: helper.py\n"
        "+def helper():\n"
        "+    return 2\n"
        "*** End Patch\n"
    )
    source, changed = apply_proposal(session, {"main.py": _PARENT}, patch)
    assert changed == ("helper.py",)
    assert source["helper.py"] == "def helper():\n    return 2\n"
    assert source["main.py"] == _PARENT


def test_a_patch_that_deletes_a_file_drops_it_from_the_child(
    session: WorkspaceSession,
) -> None:
    patch = "*** Begin Patch\n*** Delete File: extra.py\n*** End Patch\n"
    source, _ = apply_proposal(
        session, {"main.py": _PARENT, "extra.py": "x = 1\n"}, patch
    )
    assert "extra.py" not in source
    assert "main.py" in source


def test_a_parent_with_no_score_counts_as_failed() -> None:
    # Ran to completion, wrote no metrics: as unusable a parent as a
    # crash, and the operator choice has to treat it the same way.
    parent = ParentVariant(source={"main.py": _PARENT}, status="no_metrics")
    assert parent.failed


def test_the_first_variant_has_no_prior_run_to_report() -> None:
    prompt, _ = build_prompt(
        ParentVariant(source={}),
        operator=CodeOperator.EXPLORE,
        evaluator=_spec(),
    )
    assert "no prior run" in prompt
