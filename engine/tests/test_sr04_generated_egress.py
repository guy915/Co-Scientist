from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from co_scientist.platform.sandbox import command_lifecycle_available, sandbox_backend
from co_scientist.platform.sandbox.workspace.run_workspace import open_draft_workspace


@pytest.mark.skipif(
    sandbox_backend() is None or not command_lifecycle_available(),
    reason="generated program requires real confinement and lifecycle isolation",
)
@pytest.mark.asyncio
async def test_generated_program_cannot_connect_to_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path))
    workspace = open_draft_workspace("synthetic-run", "synthetic-draft")
    with socket.socket() as canary:
        canary.bind(("127.0.0.1", 0))
        canary.listen(1)
        port = canary.getsockname()[1]
        code = (
            "import socket; "
            f"s=socket.create_connection(('127.0.0.1',{port}),timeout=1); "
            "print('network-exposed'); s.close()"
        )
        outcome = await workspace.run_command([sys.executable, "-c", code], timeout_seconds=5)
    assert outcome.result.exit_code != 0
    assert "network-exposed" not in outcome.result.stdout
