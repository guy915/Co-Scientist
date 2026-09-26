"""Explicit, credential-isolated configuration for campaign live evaluations."""

import os
import sys


def configure_live_environment(model: str | None = None) -> str:
    """Pin model roles before app imports; transport verifies current prices.

    Supply MODEL_NAME (or the model argument) and its provider credential
    explicitly. No credential is read from disk. Live evaluators run in a fresh
    process so previously constructed settings cannot retain paid defaults.
    """
    model = _explicit_model(model)
    admitted_key = (
        "GROQ_API_KEY"
        if model == "groq/openai/gpt-oss-120b"
        else "OPENROUTER_API_KEY"
    )
    for name in list(os.environ):
        if name.upper().endswith("_API_KEY") and name != admitted_key:
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
    return model


def _explicit_model(selected: str | None) -> str:
    if "app.config" in sys.modules:
        raise RuntimeError("live evaluation requires a fresh process")
    model = (
        selected if selected is not None else os.getenv("MODEL_NAME", "")
    ).strip()
    is_openrouter = model.startswith("openrouter/") and model != "openrouter/"
    is_groq_free = model == "groq/openai/gpt-oss-120b"
    if not (is_openrouter or is_groq_free):
        raise ValueError(
            "live evaluation requires an explicit qualified MODEL_NAME"
        )
    credential = "GROQ_API_KEY" if is_groq_free else "OPENROUTER_API_KEY"
    if not os.getenv(credential, "").strip():
        raise ValueError(f"live evaluation requires {credential}")
    return model
