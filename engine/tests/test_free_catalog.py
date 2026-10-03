"""Catalog freshness and recovery across failed metadata reads."""

from typing import Any

import httpx
import pytest

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm.admission import free_policy as free_catalog
from tests._llm_free_fakes import _catalog, _mock_catalog
from tests._llm_free_fakes import _free_catalog as _free_catalog


def test_expired_catalog_recovers_after_a_failed_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed refresh withholds stale prices and permits the next read."""
    monkeypatch.setattr(free_catalog, "CATALOG_TTL_SECONDS", 0)
    payload = _catalog({"prompt": "0", "completion": "0"})
    _mock_catalog(monkeypatch, payload)
    assert free_catalog.current_catalog()["campaign/zero:free"]["pricing"] == {
        "prompt": "0",
        "completion": "0",
    }

    def unavailable(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx, "get", unavailable)
    with pytest.raises(FreeModelEligibilityError, match="catalog unavailable"):
        free_catalog.current_catalog()
    payload["data"][0]["pricing"]["completion"] = "1"
    reads = _mock_catalog(monkeypatch, payload)
    assert (
        free_catalog.current_catalog()["campaign/zero:free"]["pricing"][
            "completion"
        ]
        == "1"
    )
    assert len(reads) == 1


def test_injected_reader_is_shared_by_worker_threads() -> None:
    """All cohort threads see the installed source and share its cache."""
    from concurrent.futures import ThreadPoolExecutor

    reads: list[int] = []

    def load() -> dict[str, Any]:
        reads.append(1)
        return {"injected": {"pricing": {"prompt": "0"}}}

    with (
        free_catalog.using_catalog_reader(free_catalog.CatalogReader(load)),
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        results = list(
            pool.map(lambda _: free_catalog.current_catalog(), range(8))
        )
    assert all(result == results[0] for result in results)
    assert "injected" in results[0]
    assert reads == [1]


def test_nested_reader_scope_restores_its_predecessor_after_failure() -> None:
    """A scoped source never leaks into the reader it temporarily replaces."""
    outer = free_catalog.CatalogReader(lambda: {"outer": {}})
    inner = free_catalog.CatalogReader(lambda: {"inner": {}})
    with free_catalog.using_catalog_reader(outer):
        assert free_catalog.current_catalog() == {"outer": {}}
        with (
            pytest.raises(ValueError, match="scope failed"),
            free_catalog.using_catalog_reader(inner),
        ):
            assert free_catalog.current_catalog() == {"inner": {}}
            raise ValueError("scope failed")
        assert free_catalog.current_catalog() == {"outer": {}}
