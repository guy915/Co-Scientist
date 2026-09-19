"""Explicit, credential-isolated configuration for campaign live evaluations."""

import os
import sys


def configure_live_environment() -> None:
    """Pin model roles before app imports; transport verifies current prices.

    MODEL_NAME and OPENROUTER_API_KEY must be explicitly supplied by the
    caller. No credential is read from disk. Live evaluators run in a fresh
    process so previously constructed settings cannot retain paid defaults.
    """
    model = _explicit_model()
    for name in list(os.environ):
        if name.upper().endswith("_API_KEY") and name != "OPENROUTER_API_KEY":
            del os.environ[name]
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] = "1"
    os.environ["CLAIM_ASSESSOR"] = "llm"
    for name in (
        "MODEL_NAME",
        "SUPERVISOR_MODEL_NAME",
        "CHAT_MODEL_NAME",
        "SEMANTIC_SAFETY_MODEL",
        "CLAIM_VERIFIER_MODEL",
    ):
        os.environ[name] = model


def _explicit_model() -> str:
    if "app.config" in sys.modules:
        raise RuntimeError("live evaluation requires a fresh process")
    model = os.getenv("MODEL_NAME", "").strip()
    if not model.startswith("openrouter/") or model == "openrouter/":
        raise ValueError(
            "live evaluation requires explicit OpenRouter MODEL_NAME"
        )
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise ValueError("live evaluation requires OPENROUTER_API_KEY")
    return model
