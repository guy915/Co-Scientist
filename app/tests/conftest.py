# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Shared pytest fixtures."""
from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch,
                tmp_path: pathlib.Path) -> Iterator[str]:
    """Point the SQLite store at a per-test database and force mock mode."""
    db_path = str(tmp_path / "test.db")
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    monkeypatch.setenv("COSCIENTIST_DB_PATH", db_path)
    monkeypatch.setenv("COSCIENTIST_REPORTS_DIR", reports_dir)
    monkeypatch.setenv("COSCIENTIST_FORCE_MOCK", "1")
    # Wipe any cached default-path init flags from previous tests.
    from app import store as _store  # pylint: disable=import-outside-toplevel

    _store._initialized.discard(db_path)  # pylint: disable=protected-access
    yield db_path
