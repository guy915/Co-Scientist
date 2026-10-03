"""The routes the engine names, and what is stated about each.

One entry per exact route, keyed by its lowercased litellm name. An entry
states only the ``ModelProfile`` fields that are true of that route and
overrides whatever a family in ``llm.profile`` says; a route with
no entry here is an unknown route, or a family member. Adding or retiring a
model is one edit to this table (plus the app's configured default, which
``app/tests/test_config_models.py`` checks is priced here).

Prices are published list prices, in USD per million tokens, verified against
each provider's own pricing page in August 2026. A model with no price on
record prices at zero (see ``estimate_cost_usd``) rather than raising or
guessing -- a new or renamed model then degrades to "no cost tracked" instead
of breaking telemetry for every call site that names it.

Two ways a figure here is deliberately the pessimistic one, because an
estimate that flatters the bill is worse than no estimate:

* **Peak rate for DeepSeek.** DeepSeek bills at half these rates outside
  01:00-04:00 and 06:00-10:00 UTC. One rate per model is all this table has
  room for, and the clock is not a property of the model, so the higher one
  is listed and an off-peak run simply comes in under estimate. The previous
  entries were neither rate -- they predated the V4 price rise and
  understated output by more than half.
* **Cache-miss input for any model without a measured cache rate.**
  ``extract_token_usage`` reads the cached share of each prompt, so a model
  carrying ``cached_prompt_usd_per_million`` prices that share at the
  cheaper rate. A model without one keeps pricing every prompt token at the
  full input rate, which over-states rather than flatters. Measured on
  ``deepseek-v4-flash`` through OpenRouter: an 11k-token prefix re-sent cost
  $0.00090 cold and $0.00020 once cached, and a concurrent fan-out of eight
  re-sending the same prefix reported 95% of its prompt tokens cached -- so
  the un-cached estimate this table produced was several times the real bill
  on any tool loop.
"""

from typing import Final

from co_scientist.llm.profile.types import Facts, ModelPrice, Thinking

# Zero is an explicit ceiling for free routes, including per-request fees:
# the routing block caps every price at it (``_gateway_provider``) and the
# free-request admission re-checks it per call. Static zero-token-price
# entries are an estimate, not proof of current availability or of every
# applicable charge.
_FREE: Final = ModelPrice(0.0, 0.0)


def _gateway(
    price: ModelPrice,
    *,
    fallbacks: tuple[str, ...] = (),
    json_schema: bool = False,
    verified_provider: str | None = None,
    provider_only: str | None = None,
) -> Facts:
    """A route reached through the OpenRouter gateway with declared routing.

    Every declared route reasons and takes the gateway's reasoning knob, and
    none is known to honour a disabled reasoning mode. ``json_schema`` is
    stated for each rather than left to litellm's registry: every rung in a
    gateway chain is paired with ``require_parameters`` (see
    ``llm.request.gateway_routing._GATEWAY_PROVIDER``), which turns an
    unsupported ``response_format`` into a hard 404 instead of a soft
    degradation, and at least one declared fallback
    (``nvidia/nemotron-3.5-lightning:free``) lists no ``response_format``
    support at all in its own OpenRouter listing, so ``json_object`` is the
    only format proven safe across every rung a chain might land on.
    """
    return {
        "gateway": True,
        "thinking": Thinking.GATEWAY,
        "reasons": True,
        "reasoning_can_disable": False,
        "json_schema": json_schema,
        "price": price,
        "fallbacks": fallbacks,
        "verified_provider": verified_provider,
        "provider_only": provider_only,
    }


# **A fallback may only ever be cheaper than the model above it**, and no
# chain may exceed ``_GATEWAY_MAX_FALLBACKS`` (OpenRouter's own cap on the
# ``models`` array). Wired the other way once -- free primary, paid last
# resort -- a "last resort" priced at $1.25/$4.25 served 3.17M tokens and
# billed $5.23 in an afternoon, because 429 is the *normal* state of a shared
# free pool, so the expensive rung was the routine destination rather than the
# emergency one. The guard against it already existed -- ``_gateway_provider``
# caps a routed call at ``_MAX_PRICE_MULTIPLE`` times the primary's listed
# rate -- but a primary priced at zero previously skipped the cap, leaving the
# request unbounded. Both rules are checked over this table by
# ``test_llm_gateway_pricing.py``. Current model eligibility still needs
# verification before live use.
#
# **Do not append paid fallbacks under free routes.**
ROUTES: Final[dict[str, Facts]] = {
    # Former system default, retained for explicit deployment overrides.
    # Campaign probes observed reasoning on both Nex variants; use bounded-
    # minimal reasoning and fund its answer. No model fallback is declared.
    "openrouter/nex-agi/nex-n2.5-pro:free": _gateway(_FREE),
    "openrouter/nex-agi/nex-n2.5-mini:free": _gateway(_FREE),
    # Provisional successor, not a system default. The listed ModelRun host
    # alone has been checked for exact-zero pricing and zero retention.
    # Pinned Qwen has native structured output but no JSON object mode (a
    # JSON object request hard-404ed on 2026-09-25).
    "openrouter/qwen/qwen3.8-27b:free": _gateway(
        _FREE, json_schema=True, verified_provider="modelrun"
    ),
    # A non-default chain head kept for a deployment that opts into it. It
    # was the deployed primary from 2026-09-05 until a real express
    # run measured its single host (Decart) answering only 7 of 85 calls --
    # a shared free pool saturated most of the day (1 of 11 live probes
    # answered, matching the same shape noted 2026-08-26) -- against its
    # own first fallback rung, Minimax M3, serving 74 of those calls at $0.
    # The 2026-09-06 default switch went straight to that rung; this entry's
    # chain remains for deployments that explicitly select it.
    "openrouter/z-ai/glm-5.2:free": _gateway(
        _FREE,
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    # The previously deployed primary, retained with its all-free chain for
    # deployments that explicitly select it. Measured 2026-09-05/06 through
    # this account's OpenRouter key:
    # every ``:free`` variant carries its own per-model daily cap (~100
    # requests/day, plus a shared 20 req/min across all free variants), not
    # the "one saturated pool" shape the 2026-09-06 single-model switch
    # assumed -- the 429 body for a different free model read "Daily limit
    # reached... Credits don't affect this cap", `limit_source:
    # openrouter_shared_capacity`. A single free primary with nothing behind
    # it therefore stops the whole run dead the moment its own ~100/day is
    # spent, however healthy every other free model is. OpenRouter's
    # ``models`` fallback array falls through on a 429 exactly as it does on
    # a provider error, so a chain of N free models buys roughly N x 100
    # free calls/day before any of them needs a real spend.
    #
    # Every rung must be priced $0/$0. The provider's zero ceiling also
    # binds fallback selection; a paid rung cannot escape it on a 429.
    #
    # Order follows the live probe (3 concurrent JSON requests each,
    # 2026-09-05/06): Nemotron Super and GLM M2.7 answered 3/3 fast
    # (~1-3s, GMICloud/Nvidia); Gemma answered 2/3 (Google AI Studio, one
    # upstream 429). Every rung reasons and spends its budget thinking
    # (checked against each model's ``supported_parameters`` listing,
    # which carries ``reasoning`` for all of them), so none is inferred
    # rather than declared.
    #
    # Trimmed from six rungs to three (production run b82f9162,
    # 2026-09-06) to respect ``_GATEWAY_MAX_FALLBACKS``. Dots Note (3/3 at
    # 1-5s, AtlasCloud), Nemotron Lightning (3/3 but slow, 8-23s, and its own
    # listing carries no ``response_format`` at all -- paired with
    # ``require_parameters`` a schema'd call cannot land there) and GLM 5.2
    # (0/3, saturated) stay declared below as standalone entries, at $0/$0,
    # so a deployment can still name one directly as its own primary or
    # hand-edit it back into a trio; they no longer ride in this default
    # chain.
    "openrouter/minimax/minimax-m3:free": _gateway(
        _FREE,
        fallbacks=(
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
            "minimax/minimax-m2.7:free",
        ),
    ),
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": _gateway(_FREE),
    "openrouter/google/gemma-4-31b-it:free": _gateway(_FREE),
    "openrouter/minimax/minimax-m2.7:free": _gateway(_FREE),
    "openrouter/dots-studio/dots-3-note-preview:free": _gateway(_FREE),
    "openrouter/nvidia/nemotron-3.5-lightning:free": _gateway(_FREE),
    # Selected zero-price system default. OpenRouter's own page calls this
    # exact preview free despite its unsuffixed ID; promotional admission
    # rechecks the current listing on every call, while this route pins
    # Stealth with no fallbacks.
    "openrouter/stealth/space-bunny-alpha": {
        **_gateway(_FREE, provider_only="Stealth"),
        "promotional_free": True,
    },
    # The paid alternative chain head, kept for a deployment that opts back
    # into it (``app.config`` no longer defaults here). Its price is the
    # historical promotional rate and its routing ceiling uses the same
    # configured price multiple as other paid entries; revalidate current
    # pricing before choosing this route.
    "openrouter/z-ai/glm-5.3-flash": _gateway(
        ModelPrice(0.075, 0.25, 0.015),
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    # Gemma's endpoint has JSON object mode only. Exact endpoint evidence,
    # ahead of the generic gateway downgrade; not otherwise declared.
    "openrouter/google/gemma-4-26b-a4b-it:free": {"json_schema": False},
    # DeepSeek's own API. The family supplies everything but the price.
    "deepseek/deepseek-v4-flash": {"price": ModelPrice(0.44, 1.32)},
    "deepseek/deepseek-v4-pro": {"price": ModelPrice(1.32, 3.96)},
    "deepseek/deepseek-chat": {"price": ModelPrice(0.44, 1.32)},
    "deepseek/deepseek-reasoner": {"price": ModelPrice(1.32, 3.96)},
    "gemini/gemini-2.5-flash": {"price": ModelPrice(0.30, 2.50)},
    "gemini/gemini-2.5-flash-lite": {"price": ModelPrice(0.10, 0.40)},
    "gemini/gemini-2.5-pro": {"price": ModelPrice(1.25, 10.00)},
    "gemini/gemini-3.1-flash-lite": {"price": ModelPrice(0.25, 1.50)},
    # The same DeepSeek weights reached through OpenRouter, which routes
    # across seventeen hosts spanning 6.5x on input and 7.9x on output.
    # Which one a call lands on is a routing decision, not a property of
    # the model (see ``llm.request.gateway_routing``), so these are the rates
    # a price-capped route can actually be held to rather than an average
    # over hosts the cap excludes. Listed separately because they are a
    # different bill, not a different model: the worker tier costs roughly a
    # fifth of first-party peak. Rates move as hosts come and go -- these
    # were OpenRouter's quoted prices in August 2026, and OpenRouter reports
    # the exact cost of each call in its own dashboard, which is the billing
    # record this only estimates.
    "openrouter/deepseek/deepseek-v4-flash": {
        "price": ModelPrice(0.083, 0.165, 0.017)
    },
    # Priced off the fp8 hosts rather than the cheapest row on the board: the
    # headline rate for this model belongs to an fp4 host at 95% uptime, and
    # ``_MAX_PRICE_MULTIPLE`` scales whatever is written here into the routing
    # ceiling, so a rate copied from the cheapest quantized host would cap the
    # route below every full-precision one. At 2x this, twenty of the model's
    # twenty-nine hosts stay eligible, and the tail charging up to 3.4x this
    # on input and 4.7x on output -- DeepSeek's own first-party endpoint among
    # them, at 0.22/0.66 -- is excluded.
    "openrouter/deepseek/deepseek-v4-flash-0731": {
        "price": ModelPrice(0.13, 0.28, 0.028)
    },
    # The paid last resort, and the only rung that can spend anything. At
    # twenty times the rate of the DeepSeek route this replaced, a run that
    # falls all the way through costs materially more than one that does
    # not -- so a bill appearing here is a signal that both free rungs were
    # unavailable, not that the model was chosen.
    "openrouter/deepseek/deepseek-v4-pro": {
        "price": ModelPrice(1.60, 3.20, 0.13)
    },
    "openai/gpt-4o": {"price": ModelPrice(2.50, 10.00)},
    # Azure resells OpenAI's models at OpenAI's list price. Present because
    # ``BYOK_PROVIDER_DEFAULT_MODELS`` names it, and an unpriced model reports
    # every run as costing nothing.
    "azure/gpt-4o": {"price": ModelPrice(2.50, 10.00)},
    "openai/gpt-4o-mini": {"price": ModelPrice(0.15, 0.60)},
    "anthropic/claude-sonnet-4-5": {"price": ModelPrice(3.00, 15.00)},
}
