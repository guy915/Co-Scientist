"""Campaign commands retain local computation without outbound billing paths."""

import socket
import sys
from pathlib import Path

import pytest

from co_scientist.workspace import WorkspaceSession


@pytest.mark.parametrize("persistent", [False, True])
async def test_campaign_confines_preexisting_network_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, persistent: bool
) -> None:
    session = WorkspaceSession(tmp_path, network_allowed=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        program = (
            "import socket\n"
            "print('LOCAL_OK', sum(range(10)), flush=True)\n"
            "try:\n"
            f"    socket.create_connection(('127.0.0.1', {port}),\n"
            "                             timeout=2).close()\n"
            "except OSError:\n"
            "    print('NETWORK_DENIED')\n"
            "else:\n"
            "    print('NETWORK_REACHED')\n"
        )
        argv = [sys.executable, "-c", program]
        control = await session.run_command(argv)
        assert control.result.ok, control.result.stderr
        assert "NETWORK_REACHED" in control.result.stdout
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        if persistent:
            command = await session.sessions.start(
                argv, policy=session.policy, cwd=session.root
            )
            await command.wait_for(10)
            result = command.read()
        else:
            result = (await session.run_command(argv)).result
        assert result.exit_code == 0, result.stderr
        assert "LOCAL_OK 45" in result.stdout
        assert "NETWORK_DENIED" in result.stdout
        assert "NETWORK_REACHED" not in result.stdout


def test_campaign_does_not_inject_skill_credentials(monkeypatch) -> None:
    from co_scientist.skills.credentials import skill_environment

    monkeypatch.setenv("OPENALEX_API_KEY", "test-only-key")
    assert skill_environment()["OPENALEX_API_KEY"] == "test-only-key"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    assert skill_environment() == {}


@pytest.mark.parametrize("kind", ["external", "danger_full_access"])
def test_campaign_rejects_unverified_confinement(monkeypatch, tmp_path, kind):
    from co_scientist.sandbox import SandboxKind, SandboxPolicy

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        WorkspaceSession(tmp_path, policy=SandboxPolicy(kind=SandboxKind(kind)))


def test_campaign_schema_for_preexisting_workspace_is_offline(
    monkeypatch, tmp_path
):
    from co_scientist.workspace.tools import WorkspaceToolProvider

    session = WorkspaceSession(tmp_path, network_allowed=True)
    provider = WorkspaceToolProvider(session)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    _, schemas = provider.get_tools()
    command = next(
        s["function"] for s in schemas if s["function"]["name"] == "run_command"
    )
    assert "not reach the network" in command["description"].lower()


async def test_recognized_skill_receives_no_campaign_host_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from co_scientist.skills import catalog, usage
    from co_scientist.workspace import WorkspaceToolProvider
    from tests._mcp import make_tool_call

    skills = tmp_path / "skills"
    skill = skills / "public-example"
    script = skill / "scripts" / "cli.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import os\n"
        "print('CREDENTIAL_PRESENT' if os.getenv('OPENALEX_API_KEY') "
        "else 'CREDENTIAL_ABSENT')\n"
    )
    (skill / "SKILL.md").write_text(
        "---\nname: public-example\ndescription: Example query.\n---\nBody.\n"
    )
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills))
    monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, sys.executable)
    monkeypatch.setenv("OPENALEX_API_KEY", "synthetic-only")
    catalog.available_skills.cache_clear()
    try:
        session = WorkspaceSession(tmp_path / "work", skills_enabled=True)
        provider = WorkspaceToolProvider(session)
        call = make_tool_call(
            "run_command",
            json.dumps({"argv": [sys.executable, str(script)]}),
        )
        control = json.loads(
            (await provider.execute_tool_call(call))["content"]
        )
        assert "CREDENTIAL_PRESENT" in control["stdout"]
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        with usage.scoped_skill_usage() as tally:
            result = json.loads(
                (await provider.execute_tool_call(call))["content"]
            )
        assert tally.snapshot() == {}
        assert result["exit_code"] == 0, result
        assert "CREDENTIAL_ABSENT" in result["stdout"]
        stale_read = await provider.execute_tool_call(
            make_tool_call("read_skill", json.dumps({"name": "public-example"}))
        )
        assert "unavailable in campaign" in stale_read["content"]
    finally:
        catalog.available_skills.cache_clear()
