"""Recorded answers for test_model_profile_snapshot.py.

Captured on 2026-10-01 by running the observers in that file against the
engine as it stood before model facts were regrouped into one profile
(da7e3874). Not to be edited by hand: a difference here means an answer
the engine gives has changed.

``CAPABILITIES`` pairs each set of models that share one capability row
with that row. ``MONEY`` has a row per model: declared gateway routes,
then other priced routes, then the two exact routes with no price, then
the unknown and family-variant probes. Named constants are rows or
fragments that several models share.
"""

from typing import Any

_FREE: Any = [
    [0.0, 0.0, 0.0],
    0.0,
    {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
]
_UNPRICED: Any = [None, 0.0, {}]
_STEALTH_PIN: Any = {
    "allow_fallbacks": False,
    "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
    "only": ["Stealth"],
    "order": None,
}
_CAP_1: Any = {"max_price": {"prompt": 0.462, "completion": 1.3860000000000001}}
_CAP_2: Any = {"max_price": {"prompt": 1.3860000000000001, "completion": 4.158}}
_CAP_3: Any = {
    "max_price": {"prompt": 0.2625, "completion": 1.5750000000000002}
}
_CAP_4: Any = {"max_price": {"prompt": 2.625, "completion": 10.5}}
_KNOBS_1: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": True, "max_tokens": 2048},
    {"enabled": True, "effort": "low"},
]
_KNOBS_2: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": False},
    {"enabled": True, "effort": "low"},
]
_REQUESTS_1: Any = [
    ["json_object", True, 18000, True],
    ["json_object", False, 18000, True],
]
_REQUESTS_2: Any = [
    ["json_object", True, 18000, True],
    ["json_object", False, 4000, True],
]
_REQUESTS_3: Any = [
    ["json_schema", False, 4000, True],
    ["json_object", False, 4000, True],
]

CAPABILITIES: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        (
            "openrouter/nex-agi/nex-n2.5-pro:free",
            "openrouter/nex-agi/nex-n2.5-mini:free",
            "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
            "openrouter/google/gemma-4-31b-it:free",
            "openrouter/minimax/minimax-m2.7:free",
            "openrouter/dots-studio/dots-3-note-preview:free",
            "openrouter/nvidia/nemotron-3.5-lightning:free",
            "openrouter/stealth/space-bunny-alpha",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/qwen/qwen3.8-27b:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": True,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": [
                ["json_schema", False, 18000, True],
                ["json_object", False, 18000, True],
            ],
        },
    ),
    (
        ("openrouter/z-ai/glm-5.2:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "minimax/minimax-m3:free",
                    "nvidia/nemotron-3-super-120b-a12b:free",
                    "nvidia/nemotron-3.5-lightning:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/minimax/minimax-m3:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "nvidia/nemotron-3-super-120b-a12b:free",
                    "google/gemma-4-31b-it:free",
                    "minimax/minimax-m2.7:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/z-ai/glm-5.3-flash",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "minimax/minimax-m3:free",
                    "nvidia/nemotron-3.5-lightning:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_1,
        },
    ),
    (
        (
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
            "deepseek/deepseek-v5-x",
            "vendor/mydeepseek-r9",
            "DeepSeek/DeepSeek-V4-Flash",
        ),
        {
            "reasons": True,
            "effort": [{"reasoning_effort": "high"}, {}],
            "knobs": [
                {"type": "enabled"},
                {"type": "disabled"},
                {"type": "disabled"},
            ],
            "routing": {},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        (
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-flash-lite",
            "gemini/gemini-2.5-pro",
            "openai/gpt-4o",
            "azure/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4-5",
            "gpt-4o",
            "ollama/llama3",
            "openrouter/x/y",
            "openrouter/qwen/qwen3.8-27b",
            "openrouter/stealth/space-bunny-alpha-2",
            "gemini/gemini-2.0-flash",
        ),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_3,
        },
    ),
    (
        (
            "gemini/gemini-3.1-flash-lite",
            "gemini/gemini-3-x",
            "gemini/gemini-3.5-flash",
            "openrouter/google/gemini-3-x",
            "Gemini/Gemini-3.1-Flash-Lite",
        ),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [1.0, 1.0, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_3,
        },
    ),
    (
        (
            "openrouter/deepseek/deepseek-v4-flash",
            "openrouter/deepseek/deepseek-v4-flash-0731",
            "openrouter/deepseek/deepseek-v4-pro",
            "openrouter/deepseek/deepseek-v5-x",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        ("openrouter/google/gemma-4-26b-a4b-it:free",),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": [
                ["json_object", True, 4000, True],
                ["json_object", False, 4000, True],
            ],
        },
    ),
    (
        ("stealth/space-bunny-alpha", "openrouter/x/y:free"),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_3,
        },
    ),
    (
        ("openrouter/deepseek/deepseek-v4-flash:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_2,
        },
    ),
    (
        ("openrouter/vendor/gemini-3-deepseek-hybrid",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [1.0, 1.0, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        (
            "OpenRouter/Stealth/Space-Bunny-Alpha",
            "OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_1,
        },
    ),
]

MONEY: dict[str, Any] = {
    "openrouter/nex-agi/nex-n2.5-pro:free": _FREE,
    "openrouter/nex-agi/nex-n2.5-mini:free": _FREE,
    "openrouter/qwen/qwen3.8-27b:free": [
        [0.0, 0.0, 0.0],
        0.0,
        {
            "data_collection": "deny",
            "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
            "only": ["modelrun"],
            "order": None,
            "zdr": True,
        },
    ],
    "openrouter/z-ai/glm-5.2:free": _FREE,
    "openrouter/minimax/minimax-m3:free": _FREE,
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": _FREE,
    "openrouter/google/gemma-4-31b-it:free": _FREE,
    "openrouter/minimax/minimax-m2.7:free": _FREE,
    "openrouter/dots-studio/dots-3-note-preview:free": _FREE,
    "openrouter/nvidia/nemotron-3.5-lightning:free": _FREE,
    "openrouter/stealth/space-bunny-alpha": [
        [0.0, 0.0, 0.0],
        0.0,
        _STEALTH_PIN,
    ],
    "openrouter/z-ai/glm-5.3-flash": [
        [0.075, 0.25, 0.015],
        0.295,
        {"max_price": {"prompt": 0.07875, "completion": 0.2625}},
    ],
    "deepseek/deepseek-v4-flash": [[0.44, 1.32, 0.0], 1.76, _CAP_1],
    "deepseek/deepseek-v4-pro": [[1.32, 3.96, 0.0], 5.28, _CAP_2],
    "deepseek/deepseek-chat": [[0.44, 1.32, 0.0], 1.76, _CAP_1],
    "deepseek/deepseek-reasoner": [[1.32, 3.96, 0.0], 5.28, _CAP_2],
    "gemini/gemini-2.5-flash": [
        [0.3, 2.5, 0.0],
        2.8,
        {"max_price": {"prompt": 0.315, "completion": 2.625}},
    ],
    "gemini/gemini-2.5-flash-lite": [
        [0.1, 0.4, 0.0],
        0.5,
        {
            "max_price": {
                "prompt": 0.10500000000000001,
                "completion": 0.42000000000000004,
            }
        },
    ],
    "gemini/gemini-2.5-pro": [
        [1.25, 10.0, 0.0],
        11.25,
        {"max_price": {"prompt": 1.3125, "completion": 10.5}},
    ],
    "gemini/gemini-3.1-flash-lite": [[0.25, 1.5, 0.0], 1.75, _CAP_3],
    "openrouter/deepseek/deepseek-v4-flash": [
        [0.083, 0.165, 0.017],
        0.21500000000000002,
        {"max_price": {"prompt": 0.08715, "completion": 0.17325000000000002}},
    ],
    "openrouter/deepseek/deepseek-v4-flash-0731": [
        [0.13, 0.28, 0.028],
        0.35900000000000004,
        {"max_price": {"prompt": 0.1365, "completion": 0.29400000000000004}},
    ],
    "openrouter/deepseek/deepseek-v4-pro": [
        [1.6, 3.2, 0.13],
        4.065,
        {
            "max_price": {
                "prompt": 1.6800000000000002,
                "completion": 3.3600000000000003,
            }
        },
    ],
    "openai/gpt-4o": [[2.5, 10.0, 0.0], 12.5, _CAP_4],
    "azure/gpt-4o": [[2.5, 10.0, 0.0], 12.5, _CAP_4],
    "openai/gpt-4o-mini": [
        [0.15, 0.6, 0.0],
        0.75,
        {"max_price": {"prompt": 0.1575, "completion": 0.63}},
    ],
    "anthropic/claude-sonnet-4-5": [
        [3.0, 15.0, 0.0],
        18.0,
        {"max_price": {"prompt": 3.1500000000000004, "completion": 15.75}},
    ],
    "openrouter/google/gemma-4-26b-a4b-it:free": _UNPRICED,
    "stealth/space-bunny-alpha": _UNPRICED,
    "gpt-4o": _UNPRICED,
    "ollama/llama3": _UNPRICED,
    "openrouter/x/y": _UNPRICED,
    "openrouter/x/y:free": _UNPRICED,
    "openrouter/qwen/qwen3.8-27b": _UNPRICED,
    "openrouter/stealth/space-bunny-alpha-2": _UNPRICED,
    "deepseek/deepseek-v5-x": _UNPRICED,
    "openrouter/deepseek/deepseek-v5-x": _UNPRICED,
    "openrouter/deepseek/deepseek-v4-flash:free": _UNPRICED,
    "vendor/mydeepseek-r9": _UNPRICED,
    "gemini/gemini-3-x": _UNPRICED,
    "gemini/gemini-3.5-flash": _UNPRICED,
    "openrouter/google/gemini-3-x": _UNPRICED,
    "gemini/gemini-2.0-flash": _UNPRICED,
    "openrouter/vendor/gemini-3-deepseek-hybrid": _UNPRICED,
    "DeepSeek/DeepSeek-V4-Flash": [None, 0.0, _CAP_1],
    "OpenRouter/Stealth/Space-Bunny-Alpha": [None, 0.0, _STEALTH_PIN],
    "OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE": [
        None,
        0.0,
        {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
    ],
    "Gemini/Gemini-3.1-Flash-Lite": [None, 0.0, _CAP_3],
}
