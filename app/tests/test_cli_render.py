"""Unit tests for the cosci CLI output formatters (no server needed)."""

from __future__ import annotations

from app.cli import render


def test_oneline_collapses_whitespace() -> None:
    assert render.oneline("a  b\n\tc") == "a b c"


def test_oneline_truncates_with_ellipsis() -> None:
    out = render.oneline("x" * 200, limit=10)
    assert len(out) == 10
    assert out.endswith("…")


def test_format_run_line_is_tab_separated() -> None:
    run = {
        "id": "r1",
        "status": "completed",
        "provider": "mock",
        "research_goal": "Study  neurons",
    }
    assert render.format_run_line(run) == "r1\tcompleted\tmock\tStudy neurons"


def test_format_action_line() -> None:
    assert render.format_action_line({"id": "r1", "status": "queued"}) == (
        "r1\tqueued"
    )


def test_format_kv_aligns_keys() -> None:
    out = render.format_kv([("a", 1), ("bb", 2)])
    assert out == "a  : 1\nbb : 2"


def test_format_kv_empty() -> None:
    assert render.format_kv([]) == ""


def test_format_record_line_selects_first_present_key() -> None:
    record = {"id": 5, "state": "verified", "claim": "a  claim"}
    line = render.format_record_line(record, (("id",), ("state",), ("claim",)))
    assert line == "5\tverified\ta claim"


def test_format_record_line_drops_trailing_empty_columns() -> None:
    line = render.format_record_line(
        {"id": 5}, (("id",), ("state",), ("claim",))
    )
    assert line == "5"


def test_format_record_line_uses_fallback_key() -> None:
    line = render.format_record_line(
        {"id": "h1", "statement": "S"}, (("id",), ("title", "statement"))
    )
    assert line == "h1\tS"


def test_sse_data_parses_data_frame() -> None:
    assert render.sse_data('data: {"type": "x", "seq": 3}') == {
        "type": "x",
        "seq": 3,
    }


def test_sse_data_ignores_non_data_and_malformed() -> None:
    assert render.sse_data(": keep-alive comment") is None
    assert render.sse_data("event: message") is None
    assert render.sse_data("data: not json") is None
    assert render.sse_data("data: ") is None
    # A JSON array is valid JSON but not an event object.
    assert render.sse_data("data: [1, 2]") is None


def test_format_event_line_renders_seq_type_payload() -> None:
    line = render.format_event_line(
        {"seq": 5, "type": "status", "payload": {"status": "running"}}
    )
    assert line == '5\tstatus\t{"status": "running"}'


def test_format_event_line_omits_empty_payload() -> None:
    line = render.format_event_line(
        {"seq": 2, "type": "lifecycle", "payload": {}}
    )
    assert line == "2\tlifecycle"
