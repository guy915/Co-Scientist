from collections.abc import Callable
from typing import Any

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez


class CannedEntrezHandle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def close(self) -> None:
        pass


def install_entrez(monkeypatch: pytest.MonkeyPatch, **requests: Callable[..., Any]) -> None:
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    for name, request in requests.items():
        monkeypatch.setattr(Entrez, name, request)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)
