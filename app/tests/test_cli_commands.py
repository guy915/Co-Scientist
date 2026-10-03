from __future__ import annotations

import json

import pytest

from tests._cli_helpers import (
    _api,
    _create,
    _grep_logs,
    _invoke,
    _start,
    _wait_status,
    cli_server,
)
from tests._client import wait_for

__all__ = ["cli_server"]


@pytest.fixture(scope="module")
def completed_run(cli_server: str) -> tuple[str, str, str]:
    client_id = "reads"
    run_id = _create(cli_server, client_id, tier="express")
    _start(cli_server, run_id, client_id)
    _wait_status(cli_server, run_id, "completed", client_id)
    return cli_server, run_id, client_id


def test_status_reports_provider(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "status") == 0
    out = capsys.readouterr().out
    assert "provider" in out
    assert "engine" in out


def test_status_json(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "status", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["health"]["status"] == "healthy"
    assert data["status"]["provider"] == "engine"
    assert data["status"]["llm_backend"] == "offline"


def test_config_shows_defaults(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "config") == 0
    assert "max_iterations" in capsys.readouterr().out


def test_show_summary_and_json(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", "show", run_id, client_id=client_id) == 0
    out = capsys.readouterr().out
    assert "status" in out
    assert "completed" in out

    assert (
        _invoke(base, "runs", "show", run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == run_id
    assert isinstance(data["summary"], dict)


def test_watch_after_skips_replayed_events(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    events = _api(
        base, "GET", f"/api/runs/{run_id}/events", client_id=client_id
    )
    max_seq = max(
        frame["seq"]
        for line in events.text.splitlines()
        if line.startswith("data:")
        for frame in [json.loads(line[len("data:") :])]
    )
    assert (
        _invoke(
            base,
            "runs",
            "watch",
            run_id,
            "--after",
            str(max_seq),
            client_id=client_id,
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].endswith("_terminal\tcompleted")


def test_watch_json_emits_jsonl(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "watch", run_id, "--json", client_id=client_id)
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    frames = [json.loads(line) for line in lines]
    assert frames[-1]["type"] == "_terminal"
    assert frames[-1]["payload"]["status"] == "completed"


# Offline reports legitimately have no literature citations.
@pytest.mark.parametrize(
    ("command", "key"),
    [
        ("hypotheses", "hypotheses"),
        ("reviews", "reviews"),
        ("safety", "safety"),
    ],
)
def test_read_collection_text_and_json(
    completed_run: tuple[str, str, str],
    capsys: pytest.CaptureFixture[str],
    command: str,
    key: str,
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", command, run_id, client_id=client_id) == 0
    text_lines = [
        line for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    assert text_lines, f"{command} produced no lines"

    assert (
        _invoke(base, "runs", command, run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data[key], list)
    assert len(data[key]) == len(text_lines)


@pytest.mark.parametrize(
    ("command", "key"),
    [
        ("matches", "matches"),
        ("proximity", "proximity"),
        ("claim-evidence", "claim_evidence"),
        ("tasks", "tasks"),
    ],
)
def test_new_read_collections_json(
    completed_run: tuple[str, str, str],
    capsys: pytest.CaptureFixture[str],
    command: str,
    key: str,
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", command, run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data[key], list)


def test_metrics_text_output(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", "metrics", run_id, client_id=client_id) == 0
    assert capsys.readouterr().out.strip()


def test_logs_shows_captured_server_records(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "logs", "--grep", "Starting Co-Scientist") == 0
    out = capsys.readouterr().out
    assert "Starting Co-Scientist server" in out
    assert "INFO" in out


def test_logs_capture_http_requests(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _api(cli_server, "GET", "/health").raise_for_status()
    assert wait_for(lambda: _grep_logs(cli_server, "/health"), timeout=15.0), (
        "no access log for /health was captured"
    )
    assert _invoke(cli_server, "logs", "--grep", "/health") == 0
    assert "GET /health" not in capsys.readouterr().out
    assert _invoke(cli_server, "logs", "--all", "--grep", "/health") == 0
    assert "GET /health" in capsys.readouterr().out


def test_logs_ingests_client_records_and_clears(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _api(
        cli_server,
        "POST",
        "/api/logs",
        json_body={
            "records": [
                {
                    "message": "ui clicked run",
                    "level": "info",
                    "logger": "session",
                }
            ]
        },
    ).raise_for_status()
    assert _invoke(cli_server, "logs", "--grep", "ui clicked run") == 0
    out = capsys.readouterr().out
    assert "ui clicked run" in out
    assert "ui.session" in out

    assert _invoke(cli_server, "logs", "--clear") == 0
    assert "deleted" in capsys.readouterr().out
    assert _invoke(cli_server, "logs", "--grep", "ui clicked run") == 0
    assert "ui clicked run" not in capsys.readouterr().out


def test_report_summary(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", "report", run_id, client_id=client_id) == 0
    out = capsys.readouterr().out
    assert "research_goal" in out
    assert "leaderboard" in out


def test_report_markdown(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "report", run_id, "--md", client_id=client_id)
        == 0
    )
    assert "#" in capsys.readouterr().out


def test_report_json(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "report", run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert "payload" in data
    assert data["payload"]["provider"] == "engine"


def _kv_value(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.startswith(key):
            return line.split(" : ", 1)[1].strip()
    raise AssertionError(f"no {key!r} line in output:\n{output}")


def test_share_create_list_revoke_round_trip(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(base, "runs", "share", "create", run_id, client_id=client_id)
    assert code == 0
    created = capsys.readouterr().out
    share_id = _kv_value(created, "id")
    token = _kv_value(created, "token")
    assert share_id and token

    assert _api(base, "GET", f"/api/shared/{token}").status_code == 200

    assert (
        _invoke(base, "runs", "share", "list", run_id, client_id=client_id) == 0
    )
    listing = capsys.readouterr()
    assert share_id in listing.out
    assert token not in listing.out

    code = _invoke(
        base,
        "runs",
        "share",
        "revoke",
        run_id,
        share_id,
        client_id=client_id,
    )
    assert code == 0
    assert "revoked" in capsys.readouterr().out

    assert (
        _invoke(base, "runs", "share", "list", run_id, client_id=client_id) == 0
    )
    assert capsys.readouterr().out.strip() == ""

    assert _api(base, "GET", f"/api/shared/{token}").status_code == 404


def test_share_create_json(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(
        base,
        "runs",
        "share",
        "create",
        run_id,
        "--json",
        client_id=client_id,
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == run_id
    assert data["token"]

    code = _invoke(
        base,
        "runs",
        "share",
        "revoke",
        run_id,
        data["id"],
        "--json",
        client_id=client_id,
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["revoked"] is True


def test_share_create_requires_a_report(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "share-no-report")
    code = _invoke(
        cli_server,
        "runs",
        "share",
        "create",
        run_id,
        client_id="share-no-report",
    )
    assert code == 1
    assert "Goal Report not ready" in capsys.readouterr().err


def test_ask_offline_returns_grounded_answer(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(
        base, "runs", "ask", run_id, "Which idea won?", client_id=client_id
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "offline mode" in captured.out
    assert captured.err.strip() == ""


def test_ask_json_streams_answer_frames(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(
        base,
        "runs",
        "ask",
        run_id,
        "Which idea won?",
        "--json",
        client_id=client_id,
    )
    assert code == 0
    frames = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    types = {frame["type"] for frame in frames}
    assert "chunk" in types
    assert "done" in types
    assert "error" not in types


@pytest.mark.parametrize(
    ("verb", "expected_err"),
    [
        ("cancel", "already finished"),
        ("resume", "already completed"),
    ],
)
def test_terminal_run_verb_errors(
    completed_run: tuple[str, str, str],
    capsys: pytest.CaptureFixture[str],
    verb: str,
    expected_err: str,
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", verb, run_id, client_id=client_id) == 1
    assert expected_err in capsys.readouterr().err
