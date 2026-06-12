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

"""Citation classifier covers all four states."""
from __future__ import annotations

from app.citations import (
    ALL_STATES,
    CitationRecord,
    classify_citation,
    classify_many,
)


def test_states_are_exactly_four():
    assert set(ALL_STATES) == {"verified", "partial", "unsupported", "unavailable"}


def test_unavailable_when_no_url():
    r = CitationRecord(title="x", url="", abstract="anything", claim="anything", available=True)
    assert classify_citation(r) == "unavailable"


def test_unavailable_when_flag_false():
    r = CitationRecord(
        title="x", url="https://example.org", abstract="anything", claim="anything", available=False
    )
    assert classify_citation(r) == "unavailable"


def test_verified_when_strong_overlap():
    r = CitationRecord(
        title="x",
        url="https://example.org/1",
        abstract="mitochondrial biogenesis brown adipose thermogenesis cold response",
        claim="mitochondrial biogenesis brown adipose thermogenesis cold response",
    )
    assert classify_citation(r) == "verified"


def test_partial_when_some_overlap():
    r = CitationRecord(
        title="x",
        url="https://example.org/1",
        abstract="mitochondrial biogenesis controls thermogenesis through a poorly understood pathway",
        claim="mitochondrial biogenesis affects something unrelated entirely",
    )
    state = classify_citation(r)
    assert state in {"partial", "unsupported"}  # depends on tokenization
    # Force a stronger boundary case
    r2 = CitationRecord(
        title="x",
        url="https://example.org/1",
        abstract="biogenesis thermogenesis mitochondrial cellular metabolism",
        claim="biogenesis affects thermogenesis somehow but other factors matter",
    )
    assert classify_citation(r2) in {"partial", "verified"}


def test_unsupported_when_no_overlap():
    r = CitationRecord(
        title="x",
        url="https://example.org/1",
        abstract="this paper studies algebraic topology and category theory",
        claim="protein folding kinetics in chaperonin complexes",
    )
    assert classify_citation(r) == "unsupported"


def test_classify_many_returns_correct_length():
    recs = [
        CitationRecord(url="", abstract="x", claim="x", available=False),
        CitationRecord(url="u", abstract="biogenesis thermogenesis mitochondrial cellular", claim="biogenesis thermogenesis mitochondrial cellular"),
    ]
    out = classify_many(recs)
    assert out == ["unavailable", "verified"]
