"""Run-scoped minting of ``Hypothesis`` identifiers.

Split out of ``models`` so the reasoning has room to be stated and
``models`` stays about the data shapes. Re-exported from ``models``, so
import sites are unaffected by the split.

A hypothesis gets a fresh ``uuid4`` by default, and that alone makes an
otherwise-fixed run unreproducible. The offline LLM backend
(``offline.llm``) renders byte-identical content for byte-identical
prompts, but ranking's multi-turn debate writes the winning hypothesis's
id into the follow-up judge prompt
(``agents/ranking/ranking_debate_turns.py::_append_debate_context``): one
random id changes a prompt, which changes that call's content, which
changes the judgment that content decides, and the run diverges from
there. On a small post-dedup pool the visible symptom is a per-run coin
flip over whether evolution's near-duplicate guard accepts a refinement,
so an offline test asserting an exact count fails a few runs in ten --
and a warm LLM cache masks it, which is why it reads as an order or load
dependency rather than as nondeterminism.

``run_scoped_hypothesis_ids`` replaces the draw for the duration of one
in-process run with ``uuid5`` over a per-run namespace and a per-run
ordinal: identical inputs mint identical ids, while two runs -- live at
the same moment or not -- can never mint the same id, because a run id
they do not share puts them in disjoint namespaces.

Three properties are load-bearing:

- **Per-run state, never module-global.** The factory lives in a
  ``ContextVar``. Each run's worker cohort executes on its own thread with
  its own event loop, and asyncio copies the surrounding context into
  every task and ``to_thread`` call, so one run's minter reaches that
  run's work and nothing else's. A module-level counter or RNG would be
  shared by every live run in the process.
- **Installed only around a full in-process run.** The two
  ``generate_hypotheses`` paths install it; nothing else does. The app's
  durable path never calls them -- it prepares state once and then runs
  each graph node as its own leased task -- so it keeps ``uuid4`` and is
  untouched by this module.
- **Never installed on a resume.** A resume restarts the ordinal stream
  while the checkpoint already holds hypotheses minted from its early
  values, so seeding a resume is the one way to make two hypotheses in
  one run share an id.
"""

import contextlib
import itertools
import uuid
from collections.abc import Callable, Iterator
from contextvars import ContextVar

# None (the default) means "draw a random uuid4", which is every context
# outside an in-process run.
_ID_FACTORY: ContextVar[Callable[[], str] | None] = ContextVar(
    "hypothesis_id_factory", default=None
)


def new_hypothesis_id() -> str:
    """Mints the identifier for a freshly constructed hypothesis.

    Returns:
        This run's next deterministic id when a run installed a factory in
        the calling context, otherwise a fresh random ``uuid4``.
    """
    factory = _ID_FACTORY.get()
    if factory is None:
        return str(uuid.uuid4())
    return factory()


def run_seed_material(run_id: str, research_goal: str) -> str:
    """Builds the text identifying one run's id stream.

    Args:
        run_id: The run's unique identifier.
        research_goal: The run's research question or goal.

    Returns:
        Seed text combining both, NUL-separated so no pair of inputs can
        be concatenated into another pair's seed.
    """
    return f"{run_id}\x00{research_goal}"


def _make_id_factory(seed_material: str) -> Callable[[], str]:
    """Builds one run's deterministic id minter.

    Args:
        seed_material: Text identifying this run (see
            ``run_seed_material``). Runs differing in it get disjoint
            namespaces, so their ids can never collide.

    Returns:
        A callable minting ``uuid5(run namespace, ordinal)`` ids: unique
        within the run, and disjoint from every other run's.
    """
    namespace = uuid.uuid5(uuid.NAMESPACE_OID, seed_material)
    ordinals = itertools.count(1)

    def _mint() -> str:
        # next() on an itertools.count is atomic, so two nodes minting
        # concurrently never draw the same ordinal. Which node draws
        # which ordinal follows the run's own execution order -- the same
        # basis the rest of the offline pipeline's determinism rests on.
        return str(uuid.uuid5(namespace, str(next(ordinals))))

    return _mint


@contextlib.contextmanager
def run_scoped_hypothesis_ids(seed_material: str) -> Iterator[None]:
    """Mints deterministic hypothesis ids for the duration of one run.

    Args:
        seed_material: Text identifying this run (see
            ``run_seed_material``).

    Yields:
        None; hypotheses constructed inside the block, and inside any task
        or thread it spawns, draw their ids from this run's stream.
    """
    _ID_FACTORY.set(_make_id_factory(seed_material))
    try:
        yield
    finally:
        # Cleared rather than reset from a token: a streaming run holds
        # this block open across yields, so entry and exit can run in
        # different consumer contexts, and ``ContextVar.reset`` rejects a
        # token from another context. Clearing restores the default
        # (``uuid4``) and cannot raise.
        _ID_FACTORY.set(None)
