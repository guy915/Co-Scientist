"""Shared continuation helper for scientist contributions."""

from __future__ import annotations

from typing import Any

from app import engine_tasks, store
from app.store import ScientificTask


def _steer_and_continue(
    run_id: str,
    sender: str,
    content: str,
    meta: dict[str, Any],
) -> ScientificTask | None:
    """Queue a contribution as steering and reopen work from the checkpoint."""
    message = store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender=sender,
            content=content,
            kind="steering",
            meta=meta,
        )
    )
    return engine_tasks.enqueue_scientist_continuation(run_id, message.id)
