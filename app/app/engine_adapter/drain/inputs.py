"""The persistence inputs the drain derives once from an engine final state.

Kept apart from the orchestrator (``final_state``): the phase modules that
consume these inputs (``claims.grounding``) import the type from here, so no
phase has to import back into the orchestrator that imports it.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class FinalStateInputs(NamedTuple):
    """Precomputed persistence inputs derived from an engine final state.

    ``final_state`` itself rides along for the consumers that read keys not
    precomputed here (the held-for-review persistence).
    """

    hyps_parents_first: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    matchups: list[dict[str, Any]]
    proximity_graph: dict[str, Any]
    persisted_engine_ids: set[str]
    final_state: dict[str, Any]
