"""Whether this deployment can run the code a discovery run evolves.

A discovery run executes model-authored programs, and the engine will
not run any of them unconfined -- `sandbox.argv.wrap_argv` raises rather
than degrading to an unsandboxed subprocess. So confinement is not a
quality of the run, it is a property of the *host kernel*, and a host
without it cannot do the one thing a discovery run exists to do.

Both halves of that live here: the question, and what happens to a task
that asks it too late. Split from `discovery_spec`, which reads what a
run was configured to do -- a different kind of fact, answered from the
run's own JSON rather than from the machine underneath it.
"""

from __future__ import annotations

from typing import Any


def code_execution_backend() -> str | None:
    """Names the confinement this deployment can run variants under.

    Reported by `/status` because the alternative way to learn the
    answer is to start a run and watch it fail: verifying a sandbox
    inside the built image on a developer's machine tests that
    machine's kernel, not the one the image is deployed onto.

    Returns:
        The backend's name, or None when this host offers none.
    """
    from co_scientist.sandbox import sandbox_backend

    backend: str | None = sandbox_backend()
    return backend


def place_dataset(run_id: str, session: Any, db_path: str | None) -> None:
    """Copies the run's dataset into one variant's workspace.

    Copied rather than shared: variants evaluate concurrently and each
    is confined to its own directory, which is what stops one evaluation
    running part of another's code. A shared directory would trade that
    property for disk, and a hard link would trade it for a quieter
    version of the same bug -- a variant writing to its input would
    corrupt every sibling's copy with nothing in either result to show
    it. `discovery_dataset.MAX_DATASET_BYTES` is what keeps the cost of
    that choice bounded.
    """
    from app import store

    for path, content in store.get_code_dataset(
        run_id, db_path=db_path
    ).items():
        target = session.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


async def evaluate_confined(session: Any, request: Any) -> Any:
    """Evaluates a variant, keeping only the host's own refusal fatal.

    `engine_tasks_variants` holds the rule this appears to break: a
    crashing variant returns a result rather than raising, because our
    retry rule makes every exception but `UnsupportedTaskError`
    retryable, and a crash is the expected case. That rule is about the
    *variant*: its code is repairable, another variant may do better,
    and the run has every reason to continue.

    A host with no confinement primitive is the opposite on all three
    counts. No variant runs, no repair helps, and every retry reproduces
    the refusal exactly -- so without this the run spends its whole
    budget on identical failures and then strands with the reason
    visible only in a task traceback. `UnsupportedTaskError` is what
    tells the queue that, which makes the run fail immediately and
    legibly instead.

    The conversion belongs here rather than in the engine: the engine's
    error is deliberately loud, and swallowing it there would also cover
    the terminal tool surface, which withholds the command tool instead.

    Raises:
        UnsupportedTaskError: When this host cannot confine at all.
    """
    from co_scientist.code_eval import evaluate_variant
    from co_scientist.sandbox import UnsupportedSandboxError

    from app.task_worker_outcomes import UnsupportedTaskError

    try:
        return await evaluate_variant(session, request)
    except UnsupportedSandboxError as exc:
        raise UnsupportedTaskError(
            f"this host cannot run sandboxed code, so no variant of this "
            f"run can be evaluated: {exc}"
        ) from exc
