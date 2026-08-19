"""The read-only data a discovery run's programs open.

Three properties, each of which the obvious implementation gets wrong.
The bytes must not ride in the run's config, which every task reads.
They must not be part of a variant's source, which the proposal agent
rewrites. And the model must be told the files exist, or it writes a
program that never opens them.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store
from app.discovery_dataset import MAX_DATASET_BYTES, dataset_files
from app.discovery_spec import DiscoverySpecError, evaluator_spec
from tests._client import make_client as _client


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [{"name": "run", "argv": [sys.executable, "main.py"]}],
        "seed_source": {"main.py": "print(1)"},
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def client(isolated_db: str) -> TestClient:
    return _client()


def _create(client: TestClient, **overrides: Any) -> Any:
    return client.post(
        "/api/runs",
        json={"research_goal": "evolve it", "discovery": _spec(**overrides)},
    )


class TestValidation:
    def test_a_path_escaping_the_workspace_is_refused(self) -> None:
        with pytest.raises(DiscoverySpecError):
            dataset_files({"dataset": {"../secrets": "x"}})

    def test_an_absolute_path_is_refused(self) -> None:
        with pytest.raises(DiscoverySpecError):
            dataset_files({"dataset": {"/etc/passwd": "x"}})

    def test_a_path_colliding_with_the_program_is_refused(self) -> None:
        # Not merged: whichever won would decide silently whether the run
        # evolves a program or overwrites it with data.
        with pytest.raises(DiscoverySpecError, match="collides"):
            dataset_files({"dataset": {"main.py": "x"}}, frozenset({"main.py"}))

    def test_too_much_data_is_refused_with_the_reason(self) -> None:
        # The ceiling is a consequence of copying per variant, so the
        # message says so rather than quoting a bare number.
        big = {"dataset": {"d.csv": "x" * (MAX_DATASET_BYTES + 1)}}
        with pytest.raises(DiscoverySpecError, match="variant count"):
            dataset_files(big)

    def test_no_dataset_is_not_an_error(self) -> None:
        assert dataset_files({}) == {}


class TestCreation:
    def test_the_bytes_leave_the_config_and_the_manifest_stays(
        self, client: TestClient
    ) -> None:
        # The config row is read by every task of every type, so payload
        # there is re-read dozens of times per run.
        response = _create(client, dataset={"d.csv": "a,b\n1,2\n"})
        assert response.status_code in (200, 201)
        run_id = response.json()["id"]
        block = store.get_run(run_id).config["discovery"]
        assert "dataset" not in block
        assert block["dataset_paths"] == ["d.csv"]

    def test_the_dataset_is_stored_against_the_run(
        self, client: TestClient
    ) -> None:
        run_id = _create(client, dataset={"d.csv": "a,b\n"}).json()["id"]
        assert store.get_code_dataset(run_id) == {"d.csv": "a,b\n"}

    def test_a_bad_dataset_fails_the_request(self, client: TestClient) -> None:
        assert _create(client, dataset={"../x": "y"}).status_code == 422

    def test_a_refused_dataset_leaves_no_run(self, client: TestClient) -> None:
        # Validation runs before the row is written, so a rejected
        # request leaves nothing for the caller to find or clean up.
        before = len(client.get("/api/runs").json()["runs"])
        _create(client, dataset={"../x": "y"})
        assert len(client.get("/api/runs").json()["runs"]) == before


class TestReachingTheProgram:
    def test_the_evaluator_spec_carries_the_manifest(
        self, client: TestClient
    ) -> None:
        run_id = _create(client, dataset={"d.csv": "a\n"}).json()["id"]
        spec = evaluator_spec(store.get_run(run_id).config)
        assert spec.dataset_paths == ("d.csv",)

    def test_the_prompt_names_the_files_but_not_their_contents(self) -> None:
        # Naming them is what lets a proposal use the data at all.
        # Including the contents is how a prompt's length starts scaling
        # with its input, which truncates silently at the far end.
        from co_scientist.agents.code_evolve.proposal import render_dataset

        rendered = render_dataset(("d.csv",))
        assert "`d.csv`" in rendered
        assert "read-only" in rendered

    def test_nothing_is_said_when_there_is_no_data(self) -> None:
        from co_scientist.agents.code_evolve.proposal import render_dataset

        assert render_dataset(()) == ""

    def test_the_data_is_placed_in_a_variant_workspace(
        self, client: TestClient
    ) -> None:
        # Copied per variant rather than shared: evaluations run
        # concurrently, and one directory between them is how two
        # variants end up each running part of the other's code.
        import tempfile
        from pathlib import Path

        from co_scientist.workspace.session import WorkspaceSession

        from app.discovery_execution import place_dataset

        run_id = _create(client, dataset={"in/d.csv": "a,b\n"}).json()["id"]
        session = WorkspaceSession(Path(tempfile.mkdtemp()))
        place_dataset(run_id, session, None)
        assert session.resolve_path("in/d.csv").read_text() == "a,b\n"

    async def test_a_program_can_actually_read_it(
        self, client: TestClient
    ) -> None:
        # The end the rest of this file only approaches: a real stage,
        # confined by the real sandbox, opening the file and scoring
        # from what it found. Every earlier assertion here would still
        # hold if the sandbox denied the read.
        import tempfile
        from pathlib import Path

        from co_scientist.code_eval.spec import EvaluationRequest
        from co_scientist.workspace.session import WorkspaceSession

        from app.discovery_execution import evaluate_confined, place_dataset

        run_id = _create(client, dataset={"d.csv": "3\n4\n"}).json()["id"]
        session = WorkspaceSession(Path(tempfile.mkdtemp()))
        place_dataset(run_id, session, None)
        program = (
            "import json\n"
            "rows = [int(x) for x in open('d.csv').read().split()]\n"
            "json.dump({'score': sum(rows)}, open('metrics.json', 'w'))\n"
        )
        result = await evaluate_confined(
            session,
            EvaluationRequest(
                spec=evaluator_spec(store.get_run(run_id).config),
                files={"main.py": program},
            ),
        )
        assert result.metrics == {"score": 7.0}
