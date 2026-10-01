"""The ``co_scientist.llm`` interface: what it exports and how it loads."""

import importlib
import subprocess
import sys

import pytest

import co_scientist.llm as llm


def test_every_exported_name_resolves_to_a_defining_module() -> None:
    """``__all__`` and the lazy table agree, and each name really loads."""
    assert sorted(llm.__all__) == sorted(llm._EXPORTS)
    for name, module in llm._EXPORTS.items():
        assert module.startswith("co_scientist.llm."), name
        defined_in = importlib.import_module(module)
        assert getattr(llm, name) is getattr(defined_in, name), name


def test_the_interface_keeps_litellm_as_the_patch_seam() -> None:
    """Tests patch ``co_scientist.llm.litellm.acompletion`` by string path."""
    import litellm

    assert llm.litellm is litellm


def test_a_name_outside_the_interface_is_an_attribute_error() -> None:
    """Internals stay importable only from where they are defined."""
    with pytest.raises(AttributeError, match="_call_llm_single_attempt"):
        getattr(llm, "_call_llm_single_attempt")  # noqa: B009


def test_importing_a_foundation_module_first_does_not_cycle() -> None:
    """``cache`` reads ``llm`` names while ``llm`` itself imports ``cache``.

    Run in a fresh interpreter because the cycle only exists on a cold
    import: an interface that imported its entry points eagerly would find
    ``co_scientist.cache`` half-initialised and fail here.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import co_scientist.cache"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
