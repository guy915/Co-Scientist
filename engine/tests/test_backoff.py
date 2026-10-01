"""Tests for the jittered backoff schedule shared by the retry paths.

The LLM retry loop and the literature-search tool call draw their waits from
``backoff.jittered_backoff_seconds`` with their own base and cap. These pin
the properties both of them depend on -- a genuine half-jitter, growth per
attempt, and a cap that only the search path asks for -- so a later
"simplification" of the distribution has to fail here first.
"""

from co_scientist import backoff
from co_scientist.evidence import search_retry
from co_scientist.llm.attempts import backoff as llm_backoff


def test_wait_is_drawn_from_the_top_half_of_the_ceiling() -> None:
    """Every wait lands in [ceiling / 2, ceiling], for every attempt."""
    for attempt in range(1, 6):
        ceiling = 2.0 * 2 ** (attempt - 1)
        for _ in range(50):
            delay = backoff.jittered_backoff_seconds(attempt, 2.0)
            assert ceiling / 2 <= delay <= ceiling


def test_wait_is_actually_jittered() -> None:
    """Identical waits would release every throttled caller together."""
    waits = {backoff.jittered_backoff_seconds(3, 2.0) for _ in range(40)}
    assert len(waits) > 1


def test_ceiling_doubles_with_each_attempt() -> None:
    """The floor of a later attempt clears the ceiling of an earlier one."""
    first = max(backoff.jittered_backoff_seconds(1, 2.0) for _ in range(50))
    third = min(backoff.jittered_backoff_seconds(3, 2.0) for _ in range(50))
    assert third > first


def test_max_seconds_saturates_the_growth() -> None:
    """Past the cap the ceiling stops doubling."""
    for _ in range(50):
        assert backoff.jittered_backoff_seconds(9, 0.5, 8.0) <= 8.0


def test_callers_keep_their_own_base_and_cap() -> None:
    """Sharing the schedule must not have merged the two callers' tuning.

    The search path waits fractions of a second and saturates at 8s; the LLM
    path starts at 2s and is deliberately uncapped.
    """
    assert search_retry._search_retry_delay(1) <= 0.5
    assert llm_backoff._rate_limit_backoff_seconds(1) >= 1.0
    assert search_retry._search_retry_delay(12) <= 8.0
    assert llm_backoff._rate_limit_backoff_seconds(12) > 8.0
