"""Tool turns recover provider failures without replaying tools."""

from collections.abc import Callable

import pytest
from litellm.exceptions import APIError, RateLimitError

from co_scientist.exceptions import LLMRateLimitParkError
from tests._llm_attempt_fakes import (
    TOOLS,
    Driver,
    ok,
    overloaded,
    rate_limited,
)
from tests._llm_attempt_fakes import drive as drive


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
async def test_tool_turn_recovers_a_transient_failure(
    drive: Driver, failure: Callable[[], Exception]
) -> None:
    run = await drive(TOOLS, [failure(), ok(TOOLS)])

    assert run.error is None
    assert len(run.calls) == 2
    assert len(run.slept) == 1 and run.slept[0] > 0
    assert run.retries == 1
    assert run.calls[0] == run.calls[1]


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
async def test_tool_turn_stops_after_three_attempts(
    drive: Driver, failure: Callable[[], Exception]
) -> None:
    run = await drive(TOOLS, [failure()])

    assert isinstance(run.error, (RateLimitError, APIError))
    assert len(run.calls) == 3
    assert len(run.slept) == 2
    assert run.retries == 2


async def test_tool_turn_parks_a_platform_quota(drive: Driver) -> None:
    run = await drive(TOOLS, [rate_limited(reset_in=7200)])

    assert isinstance(run.error, LLMRateLimitParkError)
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.retries == 0
