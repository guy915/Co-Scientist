"""Jittered exponential backoff, shared by the retry paths that wait.

Two retry loops sleep before re-issuing a call a remote source pushed back
on: the LLM attempt loop (``llm.attempts.retry``) and the
literature search tool call
(``agents/generation/literature_review/search_retry``). They wait on very
different scales -- a throttled LLM provider clears in seconds, a
reconnecting MCP session in fractions of one -- so each keeps its own base
and cap, but the schedule they draw from is one algorithm and lives here.
"""

import random


def jittered_backoff_seconds(
    attempt: int,
    base_seconds: float,
    max_seconds: float | None = None,
) -> float:
    """Return a half-jittered exponential wait after attempt ``attempt``.

    The jitter matters more than the growth: a burst throttles many callers
    at once, and an unjittered wait would release all of them
    simultaneously, reproducing the burst that caused the throttle.
    Spreading them is what actually smooths the ramp the source is asking
    for, so the wait is drawn from the top half of the ceiling rather than
    being the ceiling itself.

    Args:
        attempt: The 1-indexed attempt that just failed. The ceiling doubles
            with each one.
        base_seconds: Ceiling for the first attempt.
        max_seconds: Ceiling the doubling saturates at, or None to let it
            keep growing.

    Returns:
        Seconds to wait, drawn uniformly from ``[ceiling / 2, ceiling]``.
    """
    ceiling = base_seconds * 2 ** (attempt - 1)
    if max_seconds is not None:
        ceiling = min(ceiling, max_seconds)
    return random.uniform(ceiling / 2, ceiling)
