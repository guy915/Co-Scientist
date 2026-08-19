"""The data a discovery run's programs read, kept out of what evolves.

A discovery run evolves a program, and most interesting programs read
something. That input cannot live in the variant's own `source`: the
proposal agent rewrites every file it is given, so a CSV placed there
would be patched like code, re-sent to the model on every generation,
and stored again in full for each of the run's variants.

So a dataset is a property of the *run*. It is written once at creation,
carried in its own table, and copied into each variant's workspace
before evaluation -- never into the config row, which every task of
every type reads.

**The copy is what bounds the size.** Variants evaluate concurrently and
each is confined to its own directory, which is the isolation that keeps
one evaluation from running part of another's code; sharing one
directory to avoid duplicating bytes would trade a correctness property
for disk. Hard-linking would trade it for a subtler one -- a variant
writing to its input would corrupt every sibling's copy, silently. So
the dataset is copied per variant, and `MAX_DATASET_BYTES` is the
consequence of that choice rather than an arbitrary limit: it is the
number that keeps a full generation's copies bounded.

Beyond that ceiling is a different mechanism -- a mounted volume, or an
object store the run reads through a reference -- and it is deliberately
not built, because no use case has yet named a size that needs it.
"""

from __future__ import annotations

from typing import Any

from app.discovery_spec import DiscoverySpecError

# Key under which a create request carries the run's dataset. Present on
# the request only: creation moves the bytes to their own table and
# leaves the manifest behind.
DATASET_KEY = "dataset"

# Key under which the stored config names the dataset's files. A
# manifest, never content -- the proposal prompt has to know the files
# exist to write a program that opens them, and echoing their contents
# into a schema is how output length starts scaling with input.
DATASET_PATHS_KEY = "dataset_paths"

# Most bytes a run's dataset may total. See the module docstring: the
# real constraint is that this is copied once per variant, so the disk a
# run needs is this times its variant count.
MAX_DATASET_BYTES = 4 * 1024 * 1024


def _refuse(reason: str) -> None:
    raise DiscoverySpecError(f"discovery.{DATASET_KEY} {reason}")


def _checked_path(path: Any, seed_paths: frozenset[str]) -> str:
    """Validates one dataset path against the run's own program."""
    if not isinstance(path, str) or not path:
        _refuse("keys must be non-empty paths")
    text = str(path)
    if text.startswith("/") or ".." in text.split("/"):
        _refuse(f"path {text!r} must stay inside the workspace")
    if text in seed_paths:
        # Not a merge: whichever won would decide silently whether the
        # run evolves a program or overwrites it with data.
        _refuse(f"path {text!r} collides with the seed program")
    return text


def _checked_text(path: Any, content: Any) -> str:
    """Validates one dataset file's contents."""
    if not isinstance(content, str):
        _refuse(f"file {path!r} must be text")
    return str(content)


def dataset_files(
    block: dict[str, Any] | None, seed_paths: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Reads and validates a create request's dataset block.

    Args:
        block: The request's ``discovery`` object, or None.
        seed_paths: Paths the seed program already occupies.

    Returns:
        The dataset as ``{path: contents}``; empty when none was given.

    Raises:
        DiscoverySpecError: If it is not a map of text files, a path
            escapes the workspace or collides with the program, or the
            whole thing exceeds ``MAX_DATASET_BYTES``.
    """
    raw = (block or {}).get(DATASET_KEY)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _refuse("must be a map of paths to text")
    files = {
        _checked_path(path, seed_paths): _checked_text(path, content)
        for path, content in raw.items()
    }
    total = sum(len(text.encode("utf-8")) for text in files.values())
    if total > MAX_DATASET_BYTES:
        _refuse(
            f"totals {total} bytes, over the {MAX_DATASET_BYTES} ceiling. "
            f"It is copied into every variant's workspace, so a run's disk "
            f"is this times its variant count."
        )
    return files


def without_payload(block: dict[str, Any]) -> dict[str, Any]:
    """Replaces a request's dataset with the manifest to be stored.

    The bytes go to their own table. What the config keeps is the list
    of paths, because the loop has to tell the model which files its
    program may open and the run row is read by every task.
    """
    if DATASET_KEY not in block:
        return block
    stripped = {k: v for k, v in block.items() if k != DATASET_KEY}
    stripped[DATASET_PATHS_KEY] = sorted(block[DATASET_KEY] or {})
    return stripped
