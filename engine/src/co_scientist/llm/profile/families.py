"""Facts that hold for a whole family of routes, matched by name.

A route a family covers needs no entry of its own: a new ``deepseek-*``
release is a DeepSeek model the day it ships. Families apply in the order
listed, later ones over earlier ones, and an exact entry in
``llm.profile.routes`` overrides all of them. A family should state only
what is true of every model it matches; anything a single model gets wrong
belongs in that model's entry.
"""

from typing import Final

from co_scientist.llm.profile.types import Family, Thinking

FAMILIES: Final[tuple[Family, ...]] = (
    # DeepSeek, whichever host serves it. The whole family reasons, so
    # every member needs the token floor; honours a disabled reasoning mode;
    # and takes DeepSeek's own ``thinking`` object on its own API. Only
    # ``json_object`` is accepted there, which litellm's registry denies
    # knowing: it marks deepseek/* as supporting response schema, and the
    # DeepSeek API answers a schema'd request with an invalid-request error.
    # Every schema'd call is therefore downgraded, per call, to json_object
    # with the schema restated as prompt text, and missing required fields
    # back-filled with empty defaults (json_object mode has no server-side
    # enforcement, so nested required fields are routinely omitted).
    Family(
        contains="deepseek",
        facts={
            "reasons": True,
            "thinking": Thinking.NATIVE,
            "reasoning_can_disable": True,
            "json_schema": False,
        },
    ),
    # DeepSeek reached through OpenRouter: the gateway normalizes reasoning
    # into its own parameter (``Thinking.GATEWAY``) and spreads one model
    # across hosts that differ sharply in price, so the call carries the
    # routing block and its price ceiling even though no entry names the
    # model.
    Family(
        prefix="openrouter/",
        contains="deepseek",
        facts={"thinking": Thinking.GATEWAY, "gateway": True},
    ),
    # Gemini 3 degrades below temperature 1.0.
    Family(contains="gemini-3", facts={"min_temperature": 1.0}),
)
