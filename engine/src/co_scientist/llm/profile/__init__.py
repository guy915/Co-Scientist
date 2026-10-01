"""What the engine knows about each model route: one profile, one table.

``model_profile(name)`` is the one place a capability, a routing decision or a
price is looked up by model. Every fact that used to hang off a family
substring or a table of its own -- whether a model reasons and how to ask it
to, whether it takes a ``json_schema`` response format, its temperature floor,
its gateway pin and fallbacks, its price, whether it is an admitted
promotional free route -- is a field of the ``ModelProfile`` it returns,
declared in ``llm.profile.families`` (a family of routes by name) and
``llm.profile.routes`` (an exact route, which overrides its family).

The lowest layer of ``co_scientist.llm``: it imports nothing from the rest of
the package, so admission, request shaping and pricing can all read it.
"""

from co_scientist.llm.profile.resolve import (
    gateway_routes,
    model_profile,
    priced_routes,
    promotional_free_route,
)
from co_scientist.llm.profile.types import ModelPrice, ModelProfile, Thinking

__all__ = [
    "ModelPrice",
    "ModelProfile",
    "Thinking",
    "gateway_routes",
    "model_profile",
    "priced_routes",
    "promotional_free_route",
]
