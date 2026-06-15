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
"""Pure-Python Elo helpers used by the mock workflow and tests.

Mirrors the formula in `co_scientist.nodes.ranking.calculate_elo_update`
so the clone's tournament behaviour is consistent across mock and real paths.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


INITIAL_ELO: int = _env_int("ELO_INITIAL", 1200)
DEFAULT_K_FACTOR: int = _env_int("ELO_K_FACTOR", 24)


def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Standard Elo expected score for `player` against `opponent`."""
    result: float = 1.0 / (1.0 + 10.0**((opponent_elo - player_elo) / 400.0))
    return result


def update_pair(
    winner_elo: int,
    loser_elo: int,
    k_factor: int = DEFAULT_K_FACTOR,
) -> tuple[int, int]:
    """Return integer-rounded post-match Elo for (winner, loser)."""
    e_win = expected_score(winner_elo, loser_elo)
    e_lose = expected_score(loser_elo, winner_elo)
    new_winner = winner_elo + k_factor * (1.0 - e_win)
    new_loser = loser_elo + k_factor * (0.0 - e_lose)
    return int(round(new_winner)), int(round(new_loser))


@dataclass
class Match:
    """Single tournament match record."""

    winner_id: str
    loser_id: str
    winner_elo_before: int
    winner_elo_after: int
    loser_elo_before: int
    loser_elo_after: int
    rationale: str = ""


def run_round_robin(
    hypotheses_elo: dict[str, int],
    pairs: list[tuple[str, str]],
    judge: Callable[[str, str], tuple[str, str, str]],
    k_factor: int = DEFAULT_K_FACTOR,
) -> list[Match]:
    """Apply Elo updates for an ordered list of pairs.

    `judge(a, b) -> (winner_id, loser_id, rationale)` decides each match.
    `hypotheses_elo` is mutated in place; returned matches are the audit log.
    """
    matches: list[Match] = []
    for a, b in pairs:
        winner_id, loser_id, rationale = judge(a, b)
        w_before = hypotheses_elo[winner_id]
        l_before = hypotheses_elo[loser_id]
        w_after, l_after = update_pair(w_before, l_before, k_factor=k_factor)
        hypotheses_elo[winner_id] = w_after
        hypotheses_elo[loser_id] = l_after
        matches.append(
            Match(
                winner_id=winner_id,
                loser_id=loser_id,
                winner_elo_before=w_before,
                winner_elo_after=w_after,
                loser_elo_before=l_before,
                loser_elo_after=l_after,
                rationale=rationale,
            ))
    return matches
