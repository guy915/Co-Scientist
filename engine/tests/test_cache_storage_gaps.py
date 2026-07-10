"""Tests for the error/IO-failure paths in ``co_scientist.cache_storage``.

``test_cache.py`` exercises the happy-path round trips through ``LLMCache``
and ``NodeCache``. These tests call the private read/write helpers in
``cache_storage`` directly to reach the corruption self-healing and
atomic-write failure branches that a clean round trip never triggers:
corrupt JSON/pickle payloads, a missing "response" key, an OSError while
opening the entry (modeled with a directory in place of the expected file),
and a write failure when the destination's parent directory is missing.
"""

import pickle
from pathlib import Path

from co_scientist.cache_storage import (
    _read_llm_cache_entry,
    _read_node_cache_entry,
    _write_cache_file_atomically,
    _write_node_cache_file_atomically,
)

# --- _read_llm_cache_entry: corruption self-healing -------------------------


def test_read_llm_cache_entry_corrupt_json_removes_file(tmp_path: Path) -> None:
    """Invalid JSON is treated as a miss and the corrupt file is removed."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text("not valid json{{{", encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_llm_cache_entry_missing_response_key_removes_file(
    tmp_path: Path,
) -> None:
    """Valid JSON missing the "response" key is a miss; file is removed."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text('{"unexpected": "shape"}', encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_llm_cache_entry_os_error_is_a_miss_without_removal(
    tmp_path: Path,
) -> None:
    """An OSError while opening leaves the entry alone (may be concurrent).

    A directory in place of the expected file makes ``open()`` raise
    ``IsADirectoryError``, an ``OSError`` subclass, without ever producing
    JSON to decode.
    """
    cache_file = tmp_path / "entry.json"
    cache_file.mkdir()

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result is None
    # OSError is not corruption, so the entry is left in place.
    assert cache_file.exists()


def test_read_llm_cache_entry_success_returns_response(tmp_path: Path) -> None:
    """A clean read returns the stored "response" payload."""
    cache_file = tmp_path / "entry.json"
    cache_file.write_text('{"response": {"content": "hi"}}', encoding="utf-8")

    result = _read_llm_cache_entry(cache_file, "deadbeef")

    assert result == {"content": "hi"}


# --- _write_cache_file_atomically: write failures ---------------------------


def test_write_cache_file_atomically_os_error_is_swallowed(
    tmp_path: Path,
) -> None:
    """A write failure (missing parent dir) is logged, not raised."""
    cache_file = tmp_path / "missing_parent" / "entry.json"

    # Should not raise even though the parent directory does not exist.
    _write_cache_file_atomically(cache_file, "deadbeef", {"response": {}})

    assert not cache_file.exists()


def test_write_cache_file_atomically_success_writes_file(
    tmp_path: Path,
) -> None:
    """A normal write leaves the destination file in place, no temp file."""
    cache_file = tmp_path / "entry.json"

    _write_cache_file_atomically(cache_file, "deadbeef", {"response": {"a": 1}})

    assert cache_file.exists()
    assert not cache_file.with_suffix(".tmp").exists()


# --- _read_node_cache_entry: corruption self-healing ------------------------
#
# Pickle here mirrors production usage: cache_storage.py documents that
# node-cache entries are written locally by this package's own atomic
# writer into its own cache directory, so reading them back is trusted,
# not user-supplied, data. These tests write the fixtures themselves.


def test_read_node_cache_entry_corrupt_pickle_removes_file(
    tmp_path: Path,
) -> None:
    """Invalid pickle bytes are treated as a miss and the file is removed."""
    cache_file = tmp_path / "entry.pkl"
    cache_file.write_bytes(b"not a pickle stream")

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result is None
    assert not cache_file.exists()


def test_read_node_cache_entry_os_error_is_a_miss(tmp_path: Path) -> None:
    """An OSError while opening (e.g. a directory) is a miss.

    ``Path.unlink()`` on a directory itself raises ``OSError``, which the
    handler suppresses, so the directory is left behind.
    """
    cache_file = tmp_path / "entry.pkl"
    cache_file.mkdir()

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result is None
    assert cache_file.exists()


def test_read_node_cache_entry_success_returns_output(tmp_path: Path) -> None:
    """A clean read returns the unpickled node output."""
    cache_file = tmp_path / "entry.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump({"papers": ["a"]}, f)

    result = _read_node_cache_entry(cache_file, "literature_review", "deadbeef")

    assert result == {"papers": ["a"]}


# --- _write_node_cache_file_atomically: write failures ----------------------


def test_write_node_cache_file_atomically_failure_is_swallowed(
    tmp_path: Path,
) -> None:
    """Any failure during the pickle write is logged, never raised."""
    cache_file = tmp_path / "missing_parent" / "entry.pkl"

    # Should not raise even though the parent directory does not exist.
    _write_node_cache_file_atomically(
        cache_file, "literature_review", "deadbeef", {"papers": []}
    )

    assert not cache_file.exists()


def test_write_node_cache_file_atomically_success_writes_file(
    tmp_path: Path,
) -> None:
    """A normal write leaves the destination file in place."""
    cache_file = tmp_path / "entry.pkl"

    _write_node_cache_file_atomically(
        cache_file, "literature_review", "deadbeef", {"papers": ["x"]}
    )

    assert cache_file.exists()
    with open(cache_file, "rb") as f:
        assert pickle.load(f) == {"papers": ["x"]}
