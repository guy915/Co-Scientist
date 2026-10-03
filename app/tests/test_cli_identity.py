"""The CLI's persistent per-machine default client id (app.cli.main)."""

from __future__ import annotations

import argparse
import importlib
import pathlib
from typing import Any

import pytest

from app.cli.parsers import _common_parser

# app.cli's __init__ re-exports the `main` function under the same name as
# this module, so fetch the module itself for monkeypatching (mirrors
# tests/test_cli_robustness.py's own note on this).
cli_main = importlib.import_module("app.cli.main")


def test_default_client_id_is_generated_and_persisted(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh config directory gets one id, read back on every later call."""
    monkeypatch.setenv("COSCIENTIST_CLI_CONFIG_DIR", str(tmp_path))

    first = cli_main.default_client_id()
    second = cli_main.default_client_id()

    assert first == second
    assert (tmp_path / "client_id").read_text().strip() == first


def test_default_client_id_respects_xdg_config_home(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an explicit override, XDG_CONFIG_HOME picks the base dir."""
    monkeypatch.delenv("COSCIENTIST_CLI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    generated = cli_main.default_client_id()

    assert (tmp_path / "co-scientist" / "client_id").read_text().strip() == (
        generated
    )


class _RecordingApiClient:
    """Stands in for ``ApiClient``, recording the id ``main`` resolved."""

    last_client_id: str | None = None

    def __init__(self, _api_url: str, client_id: str | None, **_: Any) -> None:
        type(self).last_client_id = client_id

    def close(self) -> None:
        return None


def _parser_with_handler(handler: Any) -> argparse.ArgumentParser:
    """A minimal one-command parser carrying the real connection options.

    Keeps these tests about identity resolution, not about what any real
    subcommand does -- the fake handler just proves ``main`` reached it
    with the resolved client.
    """
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    leaf = sub.add_parser("status", parents=[_common_parser()])
    leaf.set_defaults(handler=handler)
    return parser


@pytest.fixture
def _patched_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route ``cli_main.main`` through :class:`_RecordingApiClient`.

    The parser is swapped for a minimal one carrying a no-op handler, so a
    ``main([...])`` call in these tests resolves identity and returns
    without ever reaching the network.
    """
    _RecordingApiClient.last_client_id = None
    monkeypatch.setattr(cli_main, "ApiClient", _RecordingApiClient)
    monkeypatch.setattr(
        cli_main,
        "build_parser",
        lambda: _parser_with_handler(lambda _args, _client: 0),
    )


def test_main_uses_the_persisted_id_when_none_is_given(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    _patched_main: None,
) -> None:
    """``cosci`` with no --client-id/env still sends a stable identity."""
    monkeypatch.delenv("COSCIENTIST_CLIENT_ID", raising=False)
    monkeypatch.setenv("COSCIENTIST_CLI_CONFIG_DIR", str(tmp_path))
    persisted = cli_main.default_client_id()

    assert cli_main.main(["status"]) == 0
    assert _RecordingApiClient.last_client_id == persisted


def test_explicit_client_id_still_wins_over_the_persisted_default(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    _patched_main: None,
) -> None:
    """An explicit --client-id is never shadowed by the on-disk default."""
    monkeypatch.setenv("COSCIENTIST_CLI_CONFIG_DIR", str(tmp_path))

    assert cli_main.main(["status", "--client-id", "explicit-id"]) == 0
    assert _RecordingApiClient.last_client_id == "explicit-id"
    # Nothing was written to disk: the persisted default was never asked for.
    assert not (tmp_path / "client_id").exists()
