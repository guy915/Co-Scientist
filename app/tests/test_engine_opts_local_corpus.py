"""The engine is told where the group's papers are, not whether to read them."""

from __future__ import annotations

from pathlib import Path

from app import paper_corpus, store
from app.engine_adapter import _build_engine_opts
from app.engine_adapter.opts import _resolve_generator_disable_tools


def _run(isolated_db: str, audience: str | None) -> store.RunRow:
    """Create a run declaring one audience."""
    return store.create_run(
        "a goal",
        "extended",
        "engine",
        {"setup": {"goal": "a goal"}, "audience": audience},
    )


def test_the_corpus_location_reaches_the_engine(isolated_db: str) -> None:
    """Where the corpus lives is the app's fact, so the app passes it.

    The engine cannot derive it: installed as a package, a repository
    path resolved from its own file lands inside the engine directory,
    and the deployment env var is not set in a checkout. Either way the
    corpus would silently not exist.
    """
    run = _run(isolated_db, paper_corpus.CORPUS_AUDIENCE)

    opts = _build_engine_opts(run.config, run.id, isolated_db)

    assert opts["local_corpus_dir"] == str(paper_corpus.corpus_dir())
    assert Path(opts["local_corpus_dir"]).name == "sbi_ucd"


def test_the_location_carries_no_permission_with_it(isolated_db: str) -> None:
    """A second gate here is how two gates come to disagree.

    Whether a run may read the corpus is decided once, by withholding
    the corpus tools from every other audience, and the engine reads
    that same decision back off its registry. So the directory is passed
    unconditionally and means only "this is where it would be".
    """
    other = _run(isolated_db, "general")

    opts = _build_engine_opts(other.config, other.id, isolated_db)

    assert opts["local_corpus_dir"] == str(paper_corpus.corpus_dir())
    # ...and the decision that actually governs it is the withheld tool,
    # which the engine reads back as "this audience may not search it".
    withheld = _resolve_generator_disable_tools(other.config)
    assert set(paper_corpus.CORPUS_TOOL_IDS) <= set(withheld)
