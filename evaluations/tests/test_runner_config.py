from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from evaluations._run_driver import configure_environment
from evaluations.tests._engine_fake_backend import SCRIPT_PRELUDE


def test_an_offline_invocation_leaves_no_credential_to_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Suffix-based removal covers provider credentials added later. Generated
    # evidence cannot support generated claims, so literature review is off.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-be-billed")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-would-be-billed")
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)

    configure_environment("/tmp/db.sqlite", live=False)

    assert [name for name in os.environ if name.endswith("_API_KEY")] == []
    assert os.environ["COSCIENTIST_FORCE_OFFLINE"] == "1"
    assert os.environ["FORCE_LITERATURE_REVIEW"] == "0"


_ROOT = Path(__file__).resolve().parents[2]


def _probe(script: str, cwd: Path, **env: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env={"PATH": os.environ["PATH"], "PYTHONPATH": str(_ROOT), **env},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


def test_live_runner_isolates_credentials_and_all_model_roles(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("GEMINI_API_KEY=dotenv-paid\nMODEL_NAME=deepseek/paid\n")
    script = """
import os
from evaluations._run_driver import configure_environment
configure_environment("/tmp/eval.db", live=True)
from dotenv import load_dotenv
load_dotenv(".env")
from app.config import settings
assert "GEMINI_API_KEY" not in os.environ
assert os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] == "1"
assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
assert "DEEPSEEK_API_KEY" not in os.environ
assert os.environ["OPENROUTER_API_KEY"] == "synthetic-router"
assert settings.gemini_api_key == ""
for model in (settings.model_name, settings.supervisor_model_name,
              settings.chat_model_name, settings.semantic_safety_model,
              settings.claim_verifier_model):
    assert model == "openrouter/campaign/zero:free", model
"""
    _probe(
        script,
        tmp_path,
        MODEL_NAME="openrouter/campaign/zero:free",
        SUPERVISOR_MODEL_NAME="deepseek/paid",
        DEEPSEEK_API_KEY="synthetic-paid",
        gemini_api_key="synthetic-lowercase-paid",
        OPENROUTER_API_KEY="synthetic-router",
    )


def test_live_runner_rejects_implicit_or_non_openrouter_models(
    tmp_path: Path,
) -> None:
    script = """
import os
from evaluations._run_driver import configure_environment
for model in ("", "deepseek/deepseek-chat"):
    os.environ["MODEL_NAME"] = model
    try:
        configure_environment("/tmp/eval.db", live=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unqualified model admitted")
"""
    _probe(
        script,
        tmp_path,
    )


def test_live_runner_price_admission_reaches_public_llm_boundary(
    tmp_path: Path,
) -> None:
    script = (
        SCRIPT_PRELUDE
        + """
import asyncio
from unittest.mock import AsyncMock, patch
import httpx
import litellm
from evaluations._run_driver import configure_environment
configure_environment("/tmp/eval.db", live=True)
from app.config import settings
from co_scientist.llm.admission import free_policy as free_catalog
from co_scientist.llm import call_llm, CompletionSpec
from co_scientist.exceptions import FreeModelEligibilityError

async def check():
    for price in ("0.01", "0"):
        catalog = {"data": [{"id": "campaign/zero:free",
            "pricing": {"prompt": "0", "completion": price},
            "architecture": {"input_modalities": ["text"],
                             "output_modalities": ["text"]}}]}
        response = litellm.ModelResponse(
            model="campaign/zero:free",
            choices=[{"message": {"role": "assistant", "content": "ok"},
                      "finish_reason": "stop"}],
            usage={"prompt_tokens": 1, "completion_tokens": 1,
                   "total_tokens": 2})
        provider = AsyncMock(return_value=response)
        metadata = httpx.Response(200, json=catalog,
            request=httpx.Request("GET", "https://openrouter.ai/api/v1/models"))
        with (
            free_catalog.using_catalog_reader(free_catalog.CatalogReader()),
            patch.object(httpx, "get", return_value=metadata),
            fake_backend(provider),
        ):
            if price != "0":
                try:
                    await call_llm(
                        "public probe", CompletionSpec(settings.model_name))
                except FreeModelEligibilityError:
                    pass
                else:
                    raise AssertionError("paid route admitted")
                provider.assert_not_called()
            else:
                answer = await call_llm(
                    "public probe", CompletionSpec(settings.model_name))
                assert answer == "ok"
                assert provider.await_count == 1
                args = provider.call_args.kwargs
                assert args["extra_body"]["provider"]["max_price"] == {
                    "prompt": 0, "completion": 0, "request": 0}
asyncio.run(check())
"""
    )
    _probe(
        script,
        tmp_path,
        MODEL_NAME="openrouter/campaign/zero:free",
        OPENROUTER_API_KEY="synthetic-router",
    )
