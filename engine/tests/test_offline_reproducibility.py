"""Tests that an offline run with the same inputs produces the same run.

``offline_llm`` already renders byte-identical content for byte-identical
prompts, but that only makes a *call* reproducible. A *run* additionally
needs every prompt to be reproducible, and each hypothesis used to draw a
random ``uuid4`` id that ranking's multi-turn debate writes into the
follow-up judge prompt -- so one random id changed a prompt, which
changed that call's content, which changed the judgment it decided, and
the run diverged from there. ``models.ids`` closes that by minting ids
from a per-run namespace instead; these tests are what keeps the property
true.

The end-to-end tests run the real compiled graph twice through the
production offline router (no ``tests._llm_fake`` content path), with the
LLM cache off -- a warm cache replays earlier answers and would hide a
regression here rather than expose it, which is exactly how this class of
flake stayed invisible.
"""

import uuid
from typing import Any

import pytest

from co_scientist import models, offline_llm
from tests._offline_helpers import (
    isolate_offline_router,
    make_offline_generator,
)

_GOAL = "Identify repurposable drugs for hepatic fibrosis"


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


async def _run(run_id: str) -> dict[str, Any]:
    """Executes one small offline run end to end.

    Args:
        run_id: The run identity the id stream is derived from.

    Returns:
        The generation result dict.
    """
    generator = make_offline_generator()
    return await generator.generate_hypotheses(
        _GOAL,
        opts={"enable_literature_review_node": False},
        run_id=run_id,
        stream=False,
    )


async def _streamed_run(run_id: str) -> dict[str, Any]:
    """Executes one small offline run through the streaming API.

    Args:
        run_id: The run identity the id stream is derived from.

    Returns:
        The last streamed cumulative state.
    """
    generator = make_offline_generator()
    last: dict[str, Any] = {}
    async for _node, state in generator.generate_hypotheses(
        _GOAL,
        opts={"enable_literature_review_node": False},
        run_id=run_id,
        stream=True,
    ):
        last = state
    return last


def _ids(result: dict[str, Any]) -> list[str]:
    """Returns the result's hypothesis ids in order."""
    return [hyp["id"] for hyp in result["hypotheses"]]


def _texts(result: dict[str, Any]) -> list[str]:
    """Returns the result's hypothesis texts in order."""
    return [hyp["text"] for hyp in result["hypotheses"]]


async def test_identical_offline_runs_produce_identical_ids_and_counts() -> (
    None
):
    """Two runs of the same offline inputs are the same run."""
    first = await _run("reproducible-run")
    second = await _run("reproducible-run")

    assert _ids(first), "the run produced no hypotheses to compare"
    assert len(_ids(first)) == len(_ids(second))
    assert _ids(first) == _ids(second)
    assert _texts(first) == _texts(second)


async def test_offline_run_reproduces_its_derived_work() -> None:
    """Reproducibility reaches the nodes an id divergence used to break.

    The divergence entered through the debate transcript and came out as
    a different tournament record and a different evolution verdict, so
    those have to match too -- equal hypothesis counts alone would not
    have caught the original defect.

    Deliberately absent: ``metrics``, ``execution_time``, and
    ``proximity_graph``, which carry wall-clock readings (the graph
    stamps ``updated_at``) and so differ between any two runs by
    construction. Reproducibility is a claim about a run's decisions, not
    about how long it took.
    """
    first = await _run("derived-work-run")
    second = await _run("derived-work-run")

    assert first["debate_transcripts"] == second["debate_transcripts"]
    assert first["tournament_matchups"] == second["tournament_matchups"]
    assert first["evolution_details"] == second["evolution_details"]
    assert first["task_history"] == second["task_history"]
    assert first["research_overview"] == second["research_overview"]


async def test_streaming_offline_runs_reproduce_and_release_the_scope() -> None:
    """The streaming path reproduces too, and lets its id scope go.

    Streaming holds the scope open across every yield, so entry and exit
    can land in different consumer contexts. Two runs matching is what
    proves the exit took effect: a scope left installed would carry its
    ordinal stream into the second run and shift every id.
    """
    first = await _streamed_run("streamed-run")
    second = await _streamed_run("streamed-run")

    assert _ids(first), "the run produced no hypotheses to compare"
    assert _ids(first) == _ids(second)
    assert uuid.UUID(models.Hypothesis(text="after").id).version == 4


async def test_distinct_run_ids_never_share_a_hypothesis_id() -> None:
    """Ids stay unique across runs, including runs live at once.

    The seed is per-run precisely so reproducibility cannot be bought
    with a fixed seed, which would hand two concurrent runs the same ids.
    """
    first = await _run("run-a")
    second = await _run("run-b")

    assert not set(_ids(first)) & set(_ids(second))


def test_hypotheses_draw_random_ids_outside_a_run() -> None:
    """Nothing changes for a hypothesis built outside a seeded run."""
    ids = {models.Hypothesis(text=f"idea {n}").id for n in range(5)}

    assert len(ids) == 5
    assert all(uuid.UUID(value).version == 4 for value in ids)


def test_run_scoped_ids_are_deterministic_unique_and_scoped() -> None:
    """The minter repeats across blocks, never within one, and cleans up."""
    seed = models.run_seed_material("run-1", _GOAL)
    with models.run_scoped_hypothesis_ids(seed):
        first = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]
    with models.run_scoped_hypothesis_ids(seed):
        second = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]

    assert first == second
    assert len(set(first)) == 3
    # The block restores the default draw rather than leaving its minter
    # installed for whatever the caller does next.
    assert models.Hypothesis(text="after").id not in first


def test_run_seed_material_separates_its_two_inputs() -> None:
    """No pair of inputs can be concatenated into another pair's seed."""
    assert models.run_seed_material("a", "bc") != models.run_seed_material(
        "ab", "c"
    )
