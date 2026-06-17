"""Shared pytest fixtures and import-path setup for the engine test suite."""

import pathlib
import sys
from typing import Any

import pytest

# Ensure ``co_scientist`` is importable even when the editable install's
# .pth file is not processed (a known venv quirk in this repo).
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def _no_prompt_disk_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop nodes writing prompt debug files to disk during tests.

    Pipeline nodes call ``save_prompt_to_disk`` for debugging; patching it to a
    no-op keeps the test run from littering the working tree.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    import co_scientist.prompts as prompts_mod  # pylint: disable=import-outside-toplevel

    def _noop(**_: Any) -> None:
        return None

    monkeypatch.setattr(prompts_mod, "save_prompt_to_disk", _noop)
