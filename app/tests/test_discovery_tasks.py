"""The discovery loop end to end, against real subprocesses.

Deliberately not mocked at the evaluation boundary: the point of this
suite is that a variant which crashes, one which never writes metrics,
and one which scores are three different outcomes that all leave the run
running. Only the proposal's LLM call is stubbed -- everything below it
is the real workspace, the real sandbox and the real cascade.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

from app import engine_tasks, store
from app.engine_tasks_variants_schedule import (
    enqueue_discovery_bootstrap,
    select_parents,
)
from app.task_worker_outcomes import _handle_task_failure

_GOOD = "import json\njson.dump({'score': 7.0}, open('metrics.json', 'w'))\n"
_CRASHES = "raise RuntimeError('boom')\n"
_SILENT = "pass\n"


def _config(program: str, **overrides: Any) -> dict[str, Any]:
    """A minimal discovery run config around one program."""
    discovery: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [
            {
                "name": "run",
                "argv": [sys.executable, "main.py"],
                "timeout_seconds": 60,
            }
        ],
        "seed_source": {"main.py": program},
    }
    discovery.update(overrides)
    return {"discovery": discovery}


@pytest.fixture
def workspace_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    return str(tmp_path / "ws")


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def _run(config: dict[str, Any]) -> Any:
    run = store.create_run("discovery", "standard", "mock", config)
    store.set_run_config(run.id, config)
    return run


async def _drain(run_id: str, limit: int = 60) -> list[dict[str, Any]]:
    """Runs the real queue until this run has nothing claimable left.

    Claims through ``claim_task`` rather than reading rows directly, so
    the dependency gating between propose, evaluate and aggregate is
    exercised rather than assumed.
    """
    results: list[dict[str, Any]] = []
    for _ in range(limit):
        task = store.claim_task("test-worker", run_id=run_id)
        if task is None:
            return results
        try:
            result = await engine_tasks.execute_engine_task(task)
        except Exception as exc:
            # Classified by the production handler rather than by a
            # restatement of it here, so a test cannot pass on a rule the
            # worker does not actually apply.
            _handle_task_failure(task, "test-worker", exc, None)
            continue
        store.complete_task(task.id, "test-worker", result)
        results.append(result)
    raise AssertionError("discovery loop did not settle")


@pytest.mark.asyncio
async def test_the_seed_program_is_recorded_and_scored(
    db: str, workspace_root: str
) -> None:
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    variants = store.list_code_variants(run.id)
    assert len(variants) == 1
    assert variants[0]["fitness"] == 7.0
    detail = store.get_code_variant(variants[0]["id"])
    assert detail is not None and detail["metrics"] == {"score": 7.0}


@pytest.mark.asyncio
async def test_the_seed_is_not_proposed_by_the_model(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An LLM call here would be spent reproducing a program we already
    # have, against a prompt showing the model an empty parent.
    from co_scientist.agents.code_evolve import proposal

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the seed must not go through the model")

    monkeypatch.setattr(proposal, "call_llm_json", _forbidden)
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    assert store.list_code_variants(run.id)[0]["source"] == {"main.py": _GOOD}


@pytest.mark.asyncio
async def test_a_crashing_variant_is_scored_not_raised(
    db: str, workspace_root: str
) -> None:
    # Our retry rule makes any exception retryable, so a crash that
    # propagated would re-run identical failing code three times and
    # then strand the run.
    run = _run(_config(_CRASHES, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    listed = store.list_code_variants(run.id)[0]
    assert listed["fitness"] is None
    assert listed["status"] == "failed"
    variant = store.get_code_variant(listed["id"])
    assert variant is not None
    assert "RuntimeError" in variant["artifacts"]["stderr"]


@pytest.mark.asyncio
async def test_a_variant_that_writes_no_metrics_is_distinguishable(
    db: str, workspace_root: str
) -> None:
    run = _run(_config(_SILENT, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    variant = store.list_code_variants(run.id)[0]
    assert variant["status"] == "no_metrics"
    assert variant["fitness"] is None


@pytest.mark.asyncio
async def test_the_run_ends_at_its_generation_budget(
    db: str, workspace_root: str
) -> None:
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    results = await _drain(run.id)
    finished = [r for r in results if "continued" in r]
    assert finished and finished[-1]["continued"] is False
    assert finished[-1]["best_fitness"] == 7.0


def test_select_parents_prefers_the_best_score(db: str) -> None:
    variants: list[dict[str, Any]] = [
        {"id": "a", "fitness": 1.0, "ordinal": 1},
        {"id": "b", "fitness": 9.0, "ordinal": 2},
        {"id": "c", "fitness": 5.0, "ordinal": 3},
    ]
    assert [v["id"] for v in select_parents(variants, 2)] == ["b", "c"]


def test_select_parents_still_breeds_from_failures(db: str) -> None:
    # A generation where everything failed must still have parents, or
    # the run ends at its first bad round with nothing repaired.
    variants: list[dict[str, Any]] = [
        {"id": "a", "fitness": None, "ordinal": 1},
        {"id": "b", "fitness": None, "ordinal": 2},
    ]
    assert [v["id"] for v in select_parents(variants, 2)] == ["b", "a"]


def test_select_parents_puts_scored_ahead_of_failed(db: str) -> None:
    variants: list[dict[str, Any]] = [
        {"id": "failed", "fitness": None, "ordinal": 9},
        {"id": "scored", "fitness": -100.0, "ordinal": 1},
    ]
    assert [v["id"] for v in select_parents(variants, 1)] == ["scored"]


_IMPROVING_PATCH = (
    "*** Begin Patch\n"
    "*** Update File: main.py\n"
    "@@\n"
    " import json\n"
    "-json.dump({'score': 7.0}, open('metrics.json', 'w'))\n"
    "+json.dump({'score': 9.0}, open('metrics.json', 'w'))\n"
    "*** End Patch\n"
)


def _stub_proposal(
    monkeypatch: pytest.MonkeyPatch, patch_text: str
) -> list[str]:
    """Answers every proposal call with one fixed patch.

    Returns the list the prompts are recorded into, so a test can assert
    on what the model was actually shown.
    """
    from co_scientist.agents.code_evolve import proposal

    seen: list[str] = []

    async def _call(prompt: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(prompt)
        return {
            "patch": patch_text,
            "rationale": "raise the reported score",
            "expected_effect": "score goes up",
        }

    monkeypatch.setattr(proposal, "call_llm_json", _call)
    return seen


@pytest.mark.asyncio
async def test_a_second_generation_breeds_from_the_seed(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_proposal(monkeypatch, _IMPROVING_PATCH)
    run = _run(_config(_GOOD, max_generations=2, children_per_generation=2))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    variants = store.list_code_variants(run.id)
    assert [v["ordinal"] for v in variants] == [1, 2, 3]
    seed = variants[0]
    assert all(child["parent_id"] == seed["id"] for child in variants[1:])
    assert all(child["generation"] == 1 for child in variants[1:])


@pytest.mark.asyncio
async def test_an_improving_child_becomes_the_run_best(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_proposal(monkeypatch, _IMPROVING_PATCH)
    run = _run(_config(_GOOD, max_generations=2, children_per_generation=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    best = store.best_code_variant(run.id)
    assert best is not None
    assert best["fitness"] == 9.0
    assert best["ordinal"] == 2
    flags = [v["is_best_so_far"] for v in store.list_code_variants(run.id)]
    assert flags == [True, True]


@pytest.mark.asyncio
async def test_the_child_records_its_operator_and_diff(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_proposal(monkeypatch, _IMPROVING_PATCH)
    run = _run(_config(_GOOD, max_generations=2, children_per_generation=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    child = store.list_code_variants(run.id)[1]
    assert child["operator"]
    assert "*** Begin Patch" in child["diff"]
    assert child["rationale"] == "raise the reported score"


@pytest.mark.asyncio
async def test_a_failed_parent_is_shown_its_error_and_repaired(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The artifacts side-channel only earns its keep if the next prompt
    # carries the error and the operator acts on it.
    prompts = _stub_proposal(
        monkeypatch,
        "*** Begin Patch\n"
        "*** Update File: main.py\n"
        "@@\n"
        "-raise RuntimeError('boom')\n"
        "+import json\n"
        "+json.dump({'score': 1.0}, open('metrics.json', 'w'))\n"
        "*** End Patch\n",
    )
    run = _run(_config(_CRASHES, max_generations=2, children_per_generation=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    assert "RuntimeError: boom" in prompts[0]
    assert "repair" in prompts[0]
    assert store.list_code_variants(run.id)[1]["fitness"] == 1.0


@pytest.mark.asyncio
async def test_a_rejected_proposal_does_not_stop_the_run(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A patch whose context does not match is an ordinary outcome. The
    # child simply never exists; its evaluation has nothing to do, and
    # the generation's aggregate still runs.
    _stub_proposal(
        monkeypatch,
        "*** Begin Patch\n"
        "*** Update File: main.py\n"
        "@@\n"
        "-this line is not in the program\n"
        "+replacement\n"
        "*** End Patch\n",
    )
    run = _run(_config(_GOOD, max_generations=2, children_per_generation=1))
    enqueue_discovery_bootstrap(run.id)
    results = await _drain(run.id)
    assert len(store.list_code_variants(run.id)) == 1
    assert any(r.get("rejected") for r in results)
    assert [t.status for t in store.list_tasks(run.id)].count("failed") == 0


@pytest.mark.asyncio
async def test_a_rejected_proposal_is_reported_not_retried(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Re-asking reproduces the same mismatch, so a raise here would burn
    # the retry budget on a question whose answer will not change.
    calls = _stub_proposal(monkeypatch, "not a patch envelope at all")
    run = _run(_config(_GOOD, max_generations=2, children_per_generation=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_bootstrap_starts_a_discovery_run_at_its_seed(
    db: str, workspace_root: str
) -> None:
    run = _run(_config(_GOOD, max_generations=1))
    engine_tasks.enqueue_bootstrap(run.id)
    await _drain(run.id)
    assert len(store.list_code_variants(run.id)) == 1


@pytest.mark.asyncio
async def test_a_finished_discovery_run_leaves_running(
    db: str, workspace_root: str
) -> None:
    # Nothing else moves a discovery run out of `running` -- it has no
    # report to publish -- and a run stuck there is indistinguishable
    # from one that died.
    run = _run(_config(_GOOD, max_generations=1))
    engine_tasks.enqueue_bootstrap(run.id)
    await _drain(run.id)
    finished = store.get_run(run.id)
    assert finished is not None and finished.status == "completed"


@pytest.mark.asyncio
async def test_a_misconfigured_run_fails_at_bootstrap(
    db: str, workspace_root: str
) -> None:
    # Rather than enqueueing a generation whose every variant then fails
    # identically for a reason no single result explains.
    from app.discovery_spec import DiscoverySpecError

    config = _config(_GOOD)
    config["discovery"]["objective"] = {"metric": "score", "direction": "up"}
    run = _run(config)
    task = engine_tasks.enqueue_bootstrap(run.id)
    claimed = store.claim_task("test-worker", run_id=run.id)
    assert claimed is not None and claimed.id == task.id
    with pytest.raises(DiscoverySpecError):
        await engine_tasks.execute_engine_task(claimed)
    assert store.list_code_variants(run.id) == []


@pytest.mark.asyncio
async def test_concurrent_evaluations_do_not_share_a_directory(
    db: str, workspace_root: str
) -> None:
    # The serial drain above cannot show this. Two evaluations writing to
    # one directory each run partly the other's code, and both return a
    # plausible number attributed to the wrong variant -- nothing in
    # either result reveals it, so it has to be tested directly.
    import asyncio

    config = _config(_GOOD)
    run = _run(config)
    tasks = []
    for score in (3.0, 8.0):
        program = _GOOD.replace("7.0", str(score))
        variant_id = store.add_code_variant(
            store.NewCodeVariant(run_id=run.id, source={"main.py": program})
        )
        tasks.append(
            store.enqueue_task(
                store.NewTask(
                    run_id=run.id,
                    task_type="engine.fanout.variant.evaluate",
                    inputs={"variant_id": variant_id},
                    idempotency_key=f"evaluate:{variant_id}",
                )
            )
        )
    results = await asyncio.gather(
        *(engine_tasks.execute_engine_task(task) for task in tasks)
    )
    assert sorted(r["fitness"] for r in results) == [3.0, 8.0]
