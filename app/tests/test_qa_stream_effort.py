"""The Q&A stream's reasoning tier, split out to keep test_qa.py under cap.

Chat is a scoping conversation, not the science: see
``app.config_thinking.CONVERSATIONAL_REASONING_EFFORT``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app import qa
from app.config import settings
from app.config_thinking import CONVERSATIONAL_REASONING_EFFORT
from tests._client import drain as _drain
from tests._llm_fake_backend import install_completion_backend


def test_stream_llm_deltas_requests_the_conversational_reasoning_tier(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The interview and chat turns think at a lower tier than the science."""
    seen: dict[str, Any] = {}

    async def _capturing_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)

        async def _chunks() -> AsyncIterator[Any]:
            delta = SimpleNamespace(content="hi", reasoning_content=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

        return _chunks()

    install_completion_backend(
        monkeypatch,
        (SimpleNamespace(acompletion=_capturing_acompletion)).acompletion,
    )
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    _drain(
        qa.stream_llm_deltas(
            settings.effective_chat_model, "sys prompt", "q?", []
        )
    )

    assert seen["reasoning_effort"] == CONVERSATIONAL_REASONING_EFFORT
