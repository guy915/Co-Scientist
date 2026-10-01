"""Shared pytest fixtures and import-path setup for the engine test suite."""

import pathlib
import sys
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

# Ensure ``co_scientist`` is importable even when the editable install's
# .pth file is not processed (a known venv quirk in this repo).
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def _no_prompt_disk_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop nodes writing prompt debug files to disk during tests.

    The LLM wrappers in ``co_scientist.llm`` save each named prompt for
    debugging by resolving ``save_prompt_to_disk`` through the
    ``co_scientist.prompts`` module at call time; patching it there to a
    no-op keeps the test run from littering the working tree.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    import co_scientist.prompts as prompts_mod

    def _noop(**_: Any) -> None:
        return None

    monkeypatch.setattr(prompts_mod, "save_prompt_to_disk", _noop)


@pytest.fixture
def _patch_mcp_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[type[Any]]:
    """Patch the MCP transport class and reset per-test global state.

    Replaces ``MultiServerMCPClient`` at its use-site with a fresh fake class
    (so the construction counter and tool/error config never leak between
    tests) and resets the module-global ``_global_client`` before and after
    each test so caching tests are isolated.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        The per-test fake client class, for tests that configure it.
    """
    from langchain_core.tools import (
        StructuredTool,
    )

    from co_scientist.mcp_client import (
        reset_mcp_client,
    )
    from co_scientist.mcp_client import session as mcp_session_mod
    from tests._mcp import (
        FakeMultiServerMCPClient,
    )

    class _Fake(FakeMultiServerMCPClient):
        instances_created = 0
        tools: ClassVar[list[StructuredTool]] = []
        error: Exception | None = None

    monkeypatch.setattr(mcp_session_mod, "MultiServerMCPClient", _Fake)
    reset_mcp_client()
    yield _Fake
    reset_mcp_client()


@pytest.fixture(autouse=True)
def _free_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic metadata keeps mocked free-model requests hermetic."""
    from co_scientist.constants.pricing import MODEL_PRICING
    from co_scientist.llm.admission import free_catalog

    catalog = {
        model.removeprefix("openrouter/"): {
            "pricing": {
                "prompt": str(price.prompt_usd_per_million),
                "completion": str(price.completion_usd_per_million),
            },
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
        for model, price in MODEL_PRICING.items()
        if model.startswith("openrouter/")
    }
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setattr(free_catalog, "_snapshot", None)
    monkeypatch.setattr(free_catalog, "_fetch_catalog", lambda: catalog)
