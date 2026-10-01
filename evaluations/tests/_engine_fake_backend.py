"""Source for a probe script that fakes the engine's provider answers.

Not a test module (underscore prefix). The live-runner probes run in a
subprocess, so the engine's recording ``FakeBackend``
(``engine/tests/_llm_fake.py``) is made available to them as script text:
prepend ``SCRIPT_PRELUDE`` and answer every engine completion with
``with fake_backend(provider):``.
"""

from __future__ import annotations

from pathlib import Path

_ENGINE_FAKE = (
    Path(__file__).resolve().parents[2] / "engine" / "tests" / "_llm_fake.py"
)

# The imports sit inside ``fake_backend`` so loading the fake happens where the
# probe asks for it, after the probe has configured its environment.
SCRIPT_PRELUDE = f"""
def fake_backend(provider):
    import importlib.util
    from co_scientist.llm.request.backend import using_backend

    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", {str(_ENGINE_FAKE)!r})
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return using_backend(module.FakeBackend(provider))
"""
