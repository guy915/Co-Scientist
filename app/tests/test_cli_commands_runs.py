"""End-to-end tests for the cosci CLI runs lifecycle verbs.

create / list / start+watch / wait / steer / pause / resume / cancel, driven
against the shared offline uvicorn server from ``tests._cli_helpers`` (see
its module docstring for the offline-server rationale). The diagnostics,
read, report, and Q&A commands live in ``test_cli_commands.py``.
"""

from __future__ import annotations

import json

import pytest

from app.cli.main import main
from tests._cli_helpers import (
    _WAIT_BUDGET,
    _api,
    _create,
    _invoke,
    _run_summary,
    _start,
    _status,
    _wait_status,
    cli_server,
)
from tests._client import wait_for

__all__ = ["cli_server"]


# ---------------------------------------------------------------------------
# Create / list
# ---------------------------------------------------------------------------


def test_create_prints_id_and_status(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "runs", "create", "A goal", client_id="c1") == 0
    fields = capsys.readouterr().out.strip().split("\t")
    assert len(fields) == 2
    run_id, status = fields
    assert status == "draft"
    assert _status(cli_server, run_id, "c1") == "draft"


def test_create_json_with_config(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _invoke(
        cli_server,
        "runs",
        "create",
        "Config goal",
        "--tier",
        "standard",
        "--focus",
        "prefer_novelty",
        "--json",
        client_id="c2",
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "draft"
    assert data["config"]["tier"] == "standard"
    assert data["config"]["focus"] == "prefer_novelty"


def test_list_scoped_to_client(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    client_id = "list-client"
    _create(cli_server, client_id)
    _create(cli_server, client_id)
    assert _invoke(cli_server, "runs", "list", client_id=client_id) == 0
    lines = [
        line for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    assert len(lines) == 2
    for line in lines:
        assert len(line.split("\t")) == 4


# ---------------------------------------------------------------------------
# Start + watch streaming, wait
# ---------------------------------------------------------------------------


def test_start_and_watch_to_terminal(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "watch-client", tier="express")
    assert (
        _invoke(cli_server, "runs", "start", run_id, client_id="watch-client")
        == 0
    )
    capsys.readouterr()  # drop the start line
    assert (
        _invoke(cli_server, "runs", "watch", run_id, client_id="watch-client")
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert any("\tstatus\t" in line for line in lines)
    assert lines[-1].endswith("_terminal\tcompleted")


def test_wait_follows_run_to_completed(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "wait-client", tier="express")
    _start(cli_server, run_id, "wait-client")
    assert (
        _invoke(
            cli_server,
            "runs",
            "wait",
            run_id,
            "--interval",
            "0.2",
            client_id="wait-client",
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == f"{run_id}\tcompleted"


# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------


def test_steer_queues_message(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Uses a dedicated draft run, not the shared ``completed_run``: steering a
    # completed engine run enqueues a durable scientist continuation that
    # reopens it, which would mutate the fixture other tests depend on.
    client_id = "steer-client"
    run_id = _create(cli_server, client_id)
    assert (
        _invoke(
            cli_server,
            "runs",
            "steer",
            run_id,
            "Prioritize testability",
            client_id=client_id,
        )
        == 0
    )
    assert "queued" in capsys.readouterr().out
    msgs = _api(
        cli_server, "GET", f"/api/runs/{run_id}/messages", client_id=client_id
    ).json()["messages"]
    assert any(m["content"] == "Prioritize testability" for m in msgs)


# ---------------------------------------------------------------------------
# Lifecycle: pause / resume / cancel
# ---------------------------------------------------------------------------


def test_pause_then_resume_cycle(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # A multi-iteration run stays active for seconds, so the pause request
    # lands well inside its run window.
    run_id = _create(cli_server, "pause-client", tier="standard")
    _start(cli_server, run_id, "pause-client")
    # Pause only once the run has committed a checkpoint with hypotheses: the
    # durable executor checkpoints per node, so pausing before the first node
    # lands would leave nothing to resume from (a 409 on resume).
    assert wait_for(
        lambda: (
            _run_summary(cli_server, run_id, "pause-client").get(
                "hypotheses", 0
            )
            >= 1
        ),
        timeout=_WAIT_BUDGET,
    ), "run did not commit hypotheses before pause"
    assert (
        _invoke(cli_server, "runs", "pause", run_id, client_id="pause-client")
        == 0
    )
    # A durable engine run pauses at the DB (no in-process handle to signal a
    # transitional "pausing"), so the endpoint reports the settled "paused".
    assert "paused" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "paused", "pause-client")

    assert (
        _invoke(cli_server, "runs", "resume", run_id, client_id="pause-client")
        == 0
    )
    assert "queued" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "completed", "pause-client")


def test_cancel_active_run(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "cancel-client", tier="standard")
    _start(cli_server, run_id, "cancel-client")
    # Cancel once the run is genuinely mid-flight (a checkpoint with hypotheses
    # committed), so this exercises a real active-run cancel rather than a
    # pre-start abort.
    assert wait_for(
        lambda: (
            _run_summary(cli_server, run_id, "cancel-client").get(
                "hypotheses", 0
            )
            >= 1
        ),
        timeout=_WAIT_BUDGET,
    ), "run did not commit hypotheses before cancel"
    assert (
        _invoke(cli_server, "runs", "cancel", run_id, client_id="cancel-client")
        == 0
    )
    # A durable engine run cancels at the DB (no in-process handle to signal a
    # transitional "cancelling"), so the endpoint reports the settled state.
    assert "cancelled" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "cancelled", "cancel-client")


def test_missing_run_errors(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "runs", "show", "no-such-run") == 1
    err = capsys.readouterr().err
    assert "404" in err
    assert "run not found" in err


def test_no_command_prints_help_and_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "usage: cosci" in capsys.readouterr().err
