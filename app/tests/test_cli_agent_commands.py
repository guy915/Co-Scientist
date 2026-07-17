"""Unit tests for the agent-focused cosci commands (httpx MockTransport)."""

from __future__ import annotations

import argparse
import importlib
from typing import Any

import httpx
import pytest

from app.cli import runs_cmd, status_cmd
from app.cli.http import ApiClient, CliError

cli_main = importlib.import_module("app.cli.main")


def _client(handler: object) -> ApiClient:
    """Build an ApiClient whose requests are served by ``handler``."""
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return ApiClient("http://api.test", transport=transport, retry_wait=0.0)


def _read_args(run_id: str = "r1", as_json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(run_id=run_id, json=as_json)


# ---------------------------------------------------------------------------
# New read subcommands
# ---------------------------------------------------------------------------


def test_matches_lists_rows(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs/r1/matches"
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 7,
                        "iteration": 1,
                        "winner_id": "h1",
                        "loser_id": "h2",
                        "rationale": "stronger grounding",
                    }
                ]
            },
        )

    assert runs_cmd.handle_matches(_read_args(), _client(handler)) == 0
    out = capsys.readouterr().out
    assert "h1" in out
    assert "h2" in out
    assert "stronger grounding" in out


def test_proximity_lists_edges(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs/r1/proximity"
        return httpx.Response(
            200,
            json={
                "proximity": [
                    {
                        "source_hypothesis_id": "h1",
                        "target_hypothesis_id": "h2",
                        "similarity": 0.83,
                        "cluster_id": "c1",
                    }
                ]
            },
        )

    assert runs_cmd.handle_proximity(_read_args(), _client(handler)) == 0
    out = capsys.readouterr().out
    assert "h1" in out
    assert "0.83" in out


def test_claim_evidence_lists_edges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs/r1/claim-evidence"
        return httpx.Response(
            200,
            json={
                "claim_evidence": [
                    {
                        "id": 3,
                        "hypothesis_id": "h1",
                        "label": "supports",
                        "claim": "PINK1 phosphorylates ubiquitin",
                    }
                ]
            },
        )

    assert runs_cmd.handle_claim_evidence(_read_args(), _client(handler)) == 0
    out = capsys.readouterr().out
    assert "supports" in out
    assert "PINK1" in out


def test_metrics_renders_key_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs/r1/metrics"
        return httpx.Response(
            200,
            json={
                "metrics": {
                    "llm_calls": 12,
                    "phase_timings": {"generate": 3.5},
                }
            },
        )

    assert runs_cmd.handle_metrics(_read_args(), _client(handler)) == 0
    out = capsys.readouterr().out
    assert "llm_calls" in out
    assert "12" in out
    assert "generate" in out


def test_metrics_absent_prints_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"metrics": None})

    assert runs_cmd.handle_metrics(_read_args(), _client(handler)) == 0
    assert "no metrics recorded" in capsys.readouterr().out


def test_demo_lists_runs(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs/demo"
        return httpx.Response(
            200,
            json={
                "runs": [
                    {
                        "id": "demo-1",
                        "status": "completed",
                        "provider": "mock",
                        "research_goal": "demo goal",
                    }
                ]
            },
        )

    args = argparse.Namespace(json=False)
    assert runs_cmd.handle_demo(args, _client(handler)) == 0
    assert "demo-1" in capsys.readouterr().out


def test_config_renders_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/config"
        return httpx.Response(
            200,
            json={
                "max_iterations": 3,
                "initial_hypotheses_count": 6,
                "evolution_max_count": 4,
            },
        )

    args = argparse.Namespace(json=False)
    assert status_cmd.handle_config(args, _client(handler)) == 0
    out = capsys.readouterr().out
    assert "max_iterations" in out
    assert "3" in out


# ---------------------------------------------------------------------------
# runs wait
# ---------------------------------------------------------------------------


def _wait_args(
    run_id: str = "r1",
    *,
    interval: float = 0.0,
    max_wait: float | None = None,
    as_json: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        run_id=run_id, interval=interval, max_wait=max_wait, json=as_json
    )


def _status_sequence(*statuses: str) -> Any:
    """Build a handler serving each status in turn, then repeating the last."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(calls["n"], len(statuses) - 1)
        calls["n"] += 1
        return httpx.Response(200, json={"id": "r1", "status": statuses[index]})

    return handler


def test_wait_polls_until_completed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = _status_sequence("running", "running", "completed")
    rc = runs_cmd.handle_wait(_wait_args(), _client(handler))
    assert rc == 0
    out = capsys.readouterr().out
    # One line per status change, not per poll.
    assert out.count("running") == 1
    assert out.count("completed") == 1


def test_wait_exit_codes_reflect_terminal_status() -> None:
    for status, expected in (
        ("failed", 3),
        ("blocked", 4),
        ("cancelled", 5),
        ("paused", 6),
    ):
        handler = _status_sequence(status)
        rc = runs_cmd.handle_wait(_wait_args(), _client(handler))
        assert rc == expected, status


def test_wait_times_out_with_exit_124() -> None:
    handler = _status_sequence("running")
    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_wait(_wait_args(max_wait=0.05), _client(handler))
    assert excinfo.value.exit_code == 124


def test_wait_json_emits_final_run_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = _status_sequence("running", "completed")
    rc = runs_cmd.handle_wait(_wait_args(as_json=True), _client(handler))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count('"status"') == 1
    assert '"completed"' in out


# ---------------------------------------------------------------------------
# Verbose logging and --version
# ---------------------------------------------------------------------------


def test_verbose_logs_requests_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = ApiClient(
        "http://api.test", transport=transport, verbose=True, retry_wait=0.0
    )
    client.request_json("GET", "/health")
    err = capsys.readouterr().err
    assert "GET /health" in err
    assert "200" in err


def test_version_flag_prints_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--version"])
    assert excinfo.value.code == 0
    assert "cosci" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def test_parser_wires_new_commands() -> None:
    parser = cli_main.build_parser()
    wait_args = parser.parse_args(["runs", "wait", "r1"])
    assert wait_args.handler is runs_cmd.handle_wait
    assert wait_args.interval == 2.0
    assert wait_args.max_wait is None
    for command, handler in (
        (["runs", "matches", "r1"], runs_cmd.handle_matches),
        (["runs", "proximity", "r1"], runs_cmd.handle_proximity),
        (["runs", "metrics", "r1"], runs_cmd.handle_metrics),
        (["runs", "claim-evidence", "r1"], runs_cmd.handle_claim_evidence),
        (["runs", "demo"], runs_cmd.handle_demo),
        (["config"], status_cmd.handle_config),
    ):
        assert parser.parse_args(command).handler is handler, command
