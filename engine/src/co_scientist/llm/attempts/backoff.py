"""How long the LLM retry loops wait before re-issuing a pushed-back call.

Two conditions are answered by waiting rather than by re-asking, and they
clear on very different scales: a throttle is a burst that passes in
seconds, an upstream outage is a service being down for minutes. They
therefore keep separate schedules here, while
``llm.attempts.retry._wait_before_retry`` stays the one place that decides
which of them a failure is and does the actual sleeping (which is also
where every test patches ``asyncio.sleep``). Both draw from the one
jitter algorithm in ``backoff``.
"""

from typing import Final

from co_scientist.backoff import jittered_backoff_seconds

# Base seconds for the throttled-retry wait; attempt N waits roughly
# BASE * 2^(N-1), jittered.
_RATE_LIMIT_BACKOFF_BASE_SECONDS: Final[float] = 2.0

# Base and ceiling for the outage wait. Sized against run 49a509b0 below,
# and against the two clocks a long wait has to stay clear of: the wait is
# an awaited sleep, so the durable task's lease heartbeat (a coroutine on
# the same loop, waking each second) keeps renewing through it, and
# COSCIENTIST_LLM_TIMEOUT_SECONDS bounds each litellm call rather than the
# gaps between them. The ceiling exists so that a caller with a larger
# attempt budget cannot double its way into an open-ended stall.
_PROVIDER_OUTAGE_BACKOFF_BASE_SECONDS: Final[float] = 30.0
_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS: Final[float] = 240.0


def _rate_limit_backoff_seconds(attempt: int) -> float:
    """Return the jittered wait before retrying a throttled attempt.

    Uncapped, unlike the search-tool retry: a provider still throttling on
    the last of a handful of attempts is asking for a longer pause, and the
    attempt budget already bounds the total. See
    ``backoff.jittered_backoff_seconds`` for why the wait is jittered.
    """
    return jittered_backoff_seconds(
        attempt, base_seconds=_RATE_LIMIT_BACKOFF_BASE_SECONDS
    )


def _provider_outage_backoff_seconds(attempt: int) -> float:
    """Return the jittered wait before retrying an outage-failed attempt.

    Longer than the throttled schedule because it answers a different
    condition. A throttle clears as soon as the caller's own burst does; an
    upstream that is down stays down on its own timetable, so a schedule
    sized for a burst spends the whole attempt budget inside the outage.
    Standard run 49a509b0 (2026-09-08) is the measurement: its terminal
    ``research_overview`` call logged waits of 1.6s, 3.6s, 6.3s and 11.6s
    -- the four the 2.0s base allows -- so all five attempts were gone in
    roughly 25 seconds against an outage lasting minutes, and the task
    failed, discarding a run with 146 completed tasks.

    At the base and ceiling above, the four waits a five-attempt call takes
    are drawn from [15, 30], [30, 60], [60, 120] and [120, 240] seconds:
    between 3.75 and 7.5 minutes in total, rather than half a minute.

    Args:
        attempt: The 1-indexed attempt that just failed.

    Returns:
        Seconds to wait, jittered, never above
        ``_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS``.
    """
    return jittered_backoff_seconds(
        attempt,
        base_seconds=_PROVIDER_OUTAGE_BACKOFF_BASE_SECONDS,
        max_seconds=_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS,
    )
