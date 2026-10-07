import pathlib
import sys
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

# Some editable installs fail to process the .pth file; keep imports working.
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def clear_capability_cache() -> Iterator[None]:
    """Memoized per-model answers must not leak between patched providers."""
    from co_scientist.platform.llm.request.completion import (
        _supports_json_schema_response_format,
    )

    _supports_json_schema_response_format.cache_clear()
    yield
    _supports_json_schema_response_format.cache_clear()


@pytest.fixture
def _patch_mcp_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[type[Any]]:
    """Fresh fake classes and a reset global client prevent counters and
    tools leaking between tests."""
    from langchain_core.tools import StructuredTool

    import co_scientist.mcp_client as mcp_session_mod
    from co_scientist.mcp_client import reset_mcp_client
    from tests._mcp import FakeMultiServerMCPClient

    class _Fake(FakeMultiServerMCPClient):
        instances_created = 0
        tools: ClassVar[list[StructuredTool]] = []
        error: Exception | None = None

    monkeypatch.setattr(mcp_session_mod, "MultiServerMCPClient", _Fake)
    reset_mcp_client()
    yield _Fake
    reset_mcp_client()


@pytest.fixture(autouse=True)
def _free_catalog(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Synthetic model metadata keeps mocked free requests hermetic."""
    from co_scientist.core.constants import MODEL_PRICING
    from co_scientist.platform.llm.admission import free_policy as free_catalog

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
    with free_catalog.using_catalog_reader(free_catalog.CatalogReader(lambda: catalog)):
        yield
