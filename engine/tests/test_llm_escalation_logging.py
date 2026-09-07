"""Pins the escalation log text to what the request actually carries.

Commit 7aaf3682 redirected the ``NO_THINKING`` rung on a model that
cannot honour a disable (``GatewayModel.reasoning_can_disable`` is False
-- every declared entry in the deployed free chain) to minimal-effort
reasoning instead of a literal disable, but left ``log_escalation``
always reporting "thinking disabled" for that rung. On exactly the
configuration the fix was written for, the log then asserted something
the request did not do -- the failure mode the "read the log line, not
the call site" gotcha in the root AGENTS.md exists to prevent (a
previous incident was misdiagnosed as a provider fault from a log line
that printed the pre-floor budget).
"""

import logging

import pytest

from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm_json_escalation import BudgetEscalation, log_escalation

# Declared in ``_GATEWAY_MODELS`` with the default ``reasoning_can_disable
# =False`` -- the deployed free-chain primary, and the exact model the
# 7aaf3682 redirect was written for.
_UNDISABLEABLE_MODEL = "openrouter/minimax/minimax-m3:free"

# Not a declared gateway model at all, so nothing redirects its disable
# request -- a plain ``enable_thinking=False`` genuinely reaches the wire.
_DISABLEABLE_MODEL = "deepseek/deepseek-v4-flash"


def test_no_thinking_log_names_the_cap_for_an_undisableable_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A model redirected to minimal effort must not be logged as disabled."""
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "reasoning capped at" in message
    assert "thinking disabled" not in message


def test_no_thinking_log_names_disabled_for_model_that_can_disable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A model whose disable actually lands must still be logged as disabled."""
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _DISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "thinking disabled" in message
    assert "capped" not in message


def test_budget_exhausted_no_thinking_log_matches_the_redirect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ``LLMBudgetExhaustedError`` phrasing gets the same fix."""
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMBudgetExhaustedError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "reasoning capped at" in message
    assert "thinking disabled" not in message


def test_minimal_reasoning_required_log_always_follows_a_real_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The MINIMAL_REASONING_REQUIRED rung's own message is unambiguous.

    ``escalation_for_error`` only ever raises this rung in answer to a
    live "reasoning is mandatory" 400 (see ``_is_reasoning_mandatory_
    error``), never as a declaration made ahead of one -- so the model
    name plays no part in its wording, and the message is identical
    regardless of which model triggered it.
    """
    with caplog.at_level(logging.WARNING):
        log_escalation(
            RuntimeError("reasoning is mandatory... cannot be disabled"),
            BudgetEscalation.MINIMAL_REASONING_REQUIRED,
            _DISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "rejected disabled reasoning as mandatory" in message
