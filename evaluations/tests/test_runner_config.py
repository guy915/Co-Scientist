from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations._run_driver import configure_environment
from evaluations.tests._engine_fake_backend import SCRIPT_PRELUDE


def test_an_offline_invocation_leaves_no_credential_to_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    # Credential names evolve; suffix-based removal avoids an incomplete
    # provider allowlist.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-be-billed")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-would-be-billed")

    configure_environment("/tmp/db.sqlite", "/tmp/cache", live=False)

    assert [name for name in os.environ if name.endswith("_API_KEY")] == []
    assert os.environ["COSCIENTIST_FORCE_OFFLINE"] == "1"


def test_an_offline_invocation_disables_literature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generated evidence cannot support generated claims, blocking the stages
    # sweeps need to exercise.
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)

    configure_environment("/tmp/db.sqlite", "/tmp/cache", live=False)

    assert os.environ["FORCE_LITERATURE_REVIEW"] == "0"


_ROOT = Path(__file__).resolve().parents[2]


def test_live_runner_isolates_credentials_and_all_model_roles(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=dotenv-paid\nMODEL_NAME=deepseek/paid\n"
    )
    script = """
import os
from evaluations._run_driver import configure_environment
configure_environment("/tmp/eval.db", "/tmp/eval-cache", live=True)
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
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "MODEL_NAME": "openrouter/campaign/zero:free",
            "SUPERVISOR_MODEL_NAME": "deepseek/paid",
            "DEEPSEEK_API_KEY": "synthetic-paid",
            "gemini_api_key": "synthetic-lowercase-paid",
            "OPENROUTER_API_KEY": "synthetic-router",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_live_runner_rejects_implicit_or_non_openrouter_models(
    tmp_path: Path,
) -> None:
    script = """
import os
from evaluations._run_driver import configure_environment
for model in ("", "deepseek/deepseek-chat"):
    os.environ["MODEL_NAME"] = model
    try:
        configure_environment("/tmp/eval.db", "/tmp/eval-cache", live=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unqualified model admitted")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "PYTHONPATH": str(_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


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
configure_environment("/tmp/eval.db", "/tmp/eval-cache", live=True)
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
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "MODEL_NAME": "openrouter/campaign/zero:free",
            "OPENROUTER_API_KEY": "synthetic-router",
        },
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("status", "backend", "accepted"),
    [
        ("completed", "real", True),
        ("completed", "offline", False),
        ("failed", "real", False),
        (None, "real", False),
    ],
)
def test_golden_acceptance_requires_persisted_real_completion(
    status: str | None, backend: str, accepted: bool
) -> None:
    from evaluations.golden_run import _assess

    artifact: dict[str, object] = {
        "run": SimpleNamespace(status=status, llm_backend=backend)
        if status
        else None,
        "evidence": [{"source": "pubmed"}],
        "claim_edges": [{"supporting": [{"quote": "Located passage"}]}],
        "matches": [],
        "hypotheses": [],
        "report": {},
    }
    assessment = _assess(artifact, {"query_gene_disease_network": 1})
    assert assessment["passed"] is accepted


def test_golden_run_rejects_unqualified_indra_before_execution(
    tmp_path: Path,
) -> None:
    script = """
import os
from unittest.mock import patch
from evaluations.golden_run import run
with patch("evaluations.golden_run._install_tool_call_counter",
           side_effect=AssertionError("execution started before admission")):
    try:
        run()
    except RuntimeError as error:
        assert "INDRA" in str(error), str(error)
    else:
        raise AssertionError("unqualified INDRA accepted")
assert os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] == "1"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
            "MODEL_NAME": "openrouter/campaign/zero:free",
            "OPENROUTER_API_KEY": "synthetic-router",
            "DEEPSEEK_API_KEY": "synthetic-paid",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_noncampaign_golden_uses_no_dotenv_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=synthetic-paid\nMODEL_NAME=deepseek/implicit\n"
    )
    script = """
import os
from unittest.mock import patch
from evaluations.golden_run import run

def observe_config():
    from app.config import settings
    assert settings.gemini_api_key == ""
    for model in (settings.model_name, settings.supervisor_model_name,
                  settings.chat_model_name, settings.semantic_safety_model,
                  settings.claim_verifier_model):
        assert model == "openrouter/explicit/model"
    assert settings.tools_config.endswith("indra_cancer.yaml")
    assert settings.claim_assessor == "llm"
    raise RuntimeError("configuration observed; no execution")

with patch("evaluations.golden_run._install_tool_call_counter", observe_config):
    try:
        run()
    except RuntimeError as error:
        assert str(error) == "configuration observed; no execution"
    else:
        raise AssertionError("unexpected execution")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "MODEL_NAME": "openrouter/explicit/model",
            "OPENROUTER_API_KEY": "synthetic-router",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
