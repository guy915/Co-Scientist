"""The suite must not share the working directory's LLM cache.

Caching is on by default and its directory resolves relative to the working
directory, so a suite run from ``app/`` would write into ``app/cache`` --
shared with every previous run, with local development, and gitignored, so
nothing surfaces it. The engine consults that cache *before* the offline
router, which makes it a correctness problem: a test can be served a
response another run recorded under different code.
"""

from __future__ import annotations

import pathlib
import tempfile

from co_scientist.cache import _resolve_cache_env


def test_the_suite_resolves_its_own_cache_directory() -> None:
    """The resolved cache directory is a throwaway, not the repo's own.

    Pins the placement as much as the value: the assignment has to happen
    before ``app.config`` is imported, because ``Settings()`` reads the
    environment at that module's import time and ``app.main`` bridges what
    it captured back. Moving the two lines below the import leaves the
    default in place and fails here.
    """
    _, cache_dir, _ = _resolve_cache_env()
    resolved = pathlib.Path(cache_dir).resolve()

    assert resolved.is_relative_to(
        pathlib.Path(tempfile.gettempdir()).resolve()
    ), resolved
    assert not resolved.is_relative_to(pathlib.Path.cwd()), resolved
