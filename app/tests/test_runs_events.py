"""Tests for the SSE streaming helpers in ``app.runs_events``.

Covers the pure per-tick helpers directly (terminal-status detection, tick
skipping, frame draining) plus the two async generators (``_stream_live_tail``
and ``_event_stream``) via a minimal fake ``Request`` stand-in, since a full
HTTP round-trip through ``TestClient`` cannot easily control tick timing or
in-process producer handles.
"""

from __future__ import annotations

import asyncio

import pytest

from app import runs_events, store
from app.runs_registry import _RunHandle
from app.store import RunStatus
from tests._client import drain as _drain


class _FakeRequest:
    """Minimal stand-in for fastapi.Request's disconnect check."""

    def __init__(
        self,
        disconnected: bool = False,
        disconnect_after: int | None = None,
    ) -> None:
        self.disconnected = disconnected
        # 1-indexed call count at which is_disconnected() starts reporting
        # True, regardless of `disconnected`. None disables this behavior.
        self.disconnect_after = disconnect_after
        self._checks = 0

    async def is_disconnected(self) -> bool:
        """Report disconnect state, honoring the configured call-count."""
        self._checks += 1
        if (
            self.disconnect_after is not None
            and self._checks >= self.disconnect_after
        ):
            return True
        return self.disconnected


# ---------------------------------------------------------------------------
# _terminal_frame
# ---------------------------------------------------------------------------


def test_terminal_frame_formats_sse_payload() -> None:
    frame = runs_events._terminal_frame("completed", 5)
    assert frame.startswith("data: ")
    assert '"type": "_terminal"' in frame
    assert '"status": "completed"' in frame
    assert '"seq": 5' in frame


# ---------------------------------------------------------------------------
# _should_skip_tick
# ---------------------------------------------------------------------------


def test_should_skip_tick_without_handle_sleeps_and_returns_false() -> None:
    async def _run() -> bool:
        return await runs_events._should_skip_tick(None, 0)

    assert asyncio.run(_run()) is False


def test_should_skip_tick_returns_false_and_clears_event_when_set() -> None:
    handle = _RunHandle()
    handle.new_event.set()

    async def _run() -> bool:
        return await runs_events._should_skip_tick(handle, 0)

    assert asyncio.run(_run()) is False
    assert not handle.new_event.is_set()


def test_should_skip_tick_times_out_and_skips_non_safety_tick() -> None:
    handle = _RunHandle()  # new_event never set -> waits out the timeout

    async def _run() -> bool:
        return await runs_events._should_skip_tick(handle, 3)

    assert asyncio.run(_run()) is True


def test_should_skip_tick_times_out_but_tenth_tick_does_not_skip() -> None:
    handle = _RunHandle()

    async def _run() -> bool:
        return await runs_events._should_skip_tick(handle, 9)

    assert asyncio.run(_run()) is False


# ---------------------------------------------------------------------------
# _terminal_status_from_event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"type": "log", "payload": {}}, None),
        ({"type": "status", "payload": {"status": "completed"}}, "completed"),
        ({"type": "status", "payload": {"status": "running"}}, None),
        ({"type": "status", "payload": None}, None),
    ],
    ids=[
        "non_status_type_returns_none",
        "returns_terminal_status",
        "ignores_non_terminal_status",
        "handles_missing_payload",
    ],
)
def test_terminal_status_from_event(
    event: dict[str, object], expected: str | None
) -> None:
    assert runs_events._terminal_status_from_event(event) == expected


# ---------------------------------------------------------------------------
# _terminal_status_from_run
# ---------------------------------------------------------------------------


def test_terminal_status_from_run_returns_none_for_unknown_run(
    isolated_db: str,
) -> None:
    assert runs_events._terminal_status_from_run("nope") is None


def test_terminal_status_from_run_returns_none_for_active_run(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    assert runs_events._terminal_status_from_run(run.id) is None


def test_terminal_status_from_run_returns_terminal_status(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._terminal_status_from_run(run.id) == "completed"


# ---------------------------------------------------------------------------
# _resolve_tick_terminal
# ---------------------------------------------------------------------------


def test_resolve_tick_terminal_prefers_event_terminal_status(
    isolated_db: str,
) -> None:
    assert (
        runs_events._resolve_tick_terminal("completed", "ignored-run", 3)
        == "completed"
    )


def test_resolve_tick_terminal_skips_run_query_on_non_safety_tick(
    isolated_db: str,
) -> None:
    # tick=3 (3 % 10 != 9): no store query, even though the run is terminal.
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._resolve_tick_terminal(None, run.id, 3) is None


def test_resolve_tick_terminal_safety_net_queries_on_tenth_tick(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    assert runs_events._resolve_tick_terminal(None, run.id, 9) == "completed"


# ---------------------------------------------------------------------------
# _drain_tick_frames
# ---------------------------------------------------------------------------


def test_drain_tick_frames_returns_new_events_as_sse_frames(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.append_event(run.id, "log", {"i": 0}, db_path=isolated_db)
    seq1 = store.append_event(run.id, "log", {"i": 1}, db_path=isolated_db)

    last_seq, terminal, frames = runs_events._drain_tick_frames(run.id, 0)

    assert last_seq == seq1
    assert terminal is None
    assert len(frames) == 2
    assert all(f.startswith("data: ") for f in frames)


def test_drain_tick_frames_detects_terminal_status_event(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    seq = store.append_event(
        run.id, "status", {"status": "failed"}, db_path=isolated_db
    )

    last_seq, terminal, frames = runs_events._drain_tick_frames(run.id, 0)

    assert last_seq == seq
    assert terminal == "failed"
    assert len(frames) == 1


# ---------------------------------------------------------------------------
# _stream_live_tail
# ---------------------------------------------------------------------------


def test_stream_live_tail_returns_immediately_on_disconnect(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    request = _FakeRequest(disconnected=True)

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            None,
            0,
        )
    )
    assert frames == []


def test_stream_live_tail_ends_on_terminal_event_via_handle(
    isolated_db: str,
) -> None:
    """A pre-set handle event skips the poll wait; the new event ends it."""
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    seq = store.append_event(
        run.id, "status", {"status": "completed"}, db_path=isolated_db
    )
    handle = _RunHandle()
    handle.new_event.set()
    request = _FakeRequest()

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            handle,
            0,
        )
    )
    assert len(frames) == 2  # the status event frame + synthetic terminal
    assert '"type": "status"' in frames[0]
    assert '"type": "_terminal"' in frames[1]
    assert f'"seq": {seq}' in frames[1]


def test_stream_live_tail_continues_past_skipped_tick(
    isolated_db: str,
) -> None:
    """A tick where ``_should_skip_tick`` returns True is simply skipped.

    A handle whose ``new_event`` is never set times out on every tick,
    returning True (skip) on every tick but the every-10th safety net; the
    loop must ``continue`` rather than draining events on that tick.
    """
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    handle = _RunHandle()  # new_event never set -> tick 0 times out and skips
    request = _FakeRequest(disconnect_after=2)  # disconnect on the 2nd check

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            handle,
            0,
        )
    )
    assert frames == []


def test_stream_live_tail_polls_without_handle(isolated_db: str) -> None:
    """With no in-process handle, the loop falls back to fixed polling."""
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.append_event(
        run.id, "status", {"status": "cancelled"}, db_path=isolated_db
    )
    request = _FakeRequest()

    frames = _drain(
        runs_events._stream_live_tail(
            run.id,
            request,  # type: ignore[arg-type]
            None,
            0,
        )
    )
    assert any('"type": "_terminal"' in f for f in frames)
    assert any('"status": "cancelled"' in f for f in frames)


# ---------------------------------------------------------------------------
# _event_stream
# ---------------------------------------------------------------------------


def test_event_stream_replays_history_then_terminal_for_finished_run(
    isolated_db: str,
) -> None:
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    store.append_event(run.id, "log", {"i": 0}, db_path=isolated_db)
    store.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)
    finished_run = store.get_run(run.id, db_path=isolated_db)
    assert finished_run is not None
    request = _FakeRequest()

    frames = _drain(
        runs_events._event_stream(
            run.id,
            request,  # type: ignore[arg-type]
            0,
            finished_run,
        )
    )
    assert '"type": "log"' in frames[0]
    assert '"type": "_terminal"' in frames[-1]


def test_event_stream_falls_through_to_live_tail_for_active_run(
    isolated_db: str,
) -> None:
    """A non-terminal run row falls through to the live-tail poll loop.

    An event is appended concurrently, shortly after the stream starts
    polling, mirroring a producer emitting a new event while a client is
    connected (a pre-existing event would be caught by the history replay
    phase instead, which is a different code path).
    """
    run = store.create_run("g", "default", "mock", {}, db_path=isolated_db)
    request = _FakeRequest()

    async def _append_terminal_soon() -> None:
        await asyncio.sleep(0.05)
        store.append_event(
            run.id, "status", {"status": "cancelled"}, db_path=isolated_db
        )

    async def _run() -> list[str]:
        appender = asyncio.create_task(_append_terminal_soon())
        try:
            return [
                frame
                async for frame in runs_events._event_stream(
                    run.id,
                    request,  # type: ignore[arg-type]
                    0,
                    run,
                )
            ]
        finally:
            await appender

    frames = asyncio.run(_run())
    assert any('"type": "_terminal"' in f for f in frames)
    assert any('"status": "cancelled"' in f for f in frames)


def test_events_endpoint_serves_json_snapshot_when_stream_false(
    isolated_db: str,
) -> None:
    """``stream=false`` returns the persisted log as one JSON response.

    The default SSE behavior is covered by the round-trip tests in
    ``test_integration_run_flow``; this covers the one-shot snapshot the
    workbench diagnostics popover consumes.
    """
    from tests._client import make_client

    run = store.create_run(
        "JSON events goal", "default", "mock", {}, db_path=isolated_db
    )
    store.append_event(run.id, "lifecycle", {"event": "created"})
    store.append_event(run.id, "status", {"status": "running"})

    client = make_client()
    res = client.get(f"/api/runs/{run.id}/events?stream=false")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    events = res.json()["events"]
    assert [e["type"] for e in events] == ["lifecycle", "status"]
    assert events[0]["seq"] == 1
    assert events[1]["payload"] == {"status": "running"}

    after = client.get(f"/api/runs/{run.id}/events?stream=false&after=1")
    assert [e["seq"] for e in after.json()["events"]] == [2]
