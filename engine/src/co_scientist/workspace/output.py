"""What a command's output is allowed to become before anyone reads it.

Two independent hazards share this module because they share a seam: the
one point where bytes a confined command produced cross back into the
transcript, and from there into storage.

**Redaction happens on the inline output, not only on stored artifacts.**
This is the gap in the harness the idea came from: it scrubs files it
persists and passes the command's own stdout through untouched, so a
single ``env`` prints every injected credential straight into the
conversation. Both paths go through here.

**A secret too short to redact is refused, not redacted.** Replacing an
eight-character value that happens to occur in ordinary prose corrupts
output everywhere it appears, and the corruption reads as a tool bug.
Registration fails loudly instead, because a caller who knows the
registry rejected a value can decide what to do; one who believes a short
value is being masked cannot.

**If a raw value survives redaction, the output is dropped whole.** The
check is cheap and the alternative is unbounded: an encoding this module
does not know about could reconstruct the value downstream. Losing a
command's output is recoverable. Publishing a key is not.

Spillover is the third concern and the mild one. Output beyond the
preview budget is written into the workspace under a protected metadata
directory -- protected because the sandbox forces it read-only, so a
later command cannot rewrite the record of an earlier one, while this
process (outside the sandbox) still can. The model reads it back with
``read_file`` when it wants the middle.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Below this, a value occurs in ordinary output by coincidence often
# enough that masking it does more damage than the exposure it prevents.
MIN_SECRET_LENGTH = 8

# Where spilled output lands, relative to the workspace root. Inside
# PROTECTED_METADATA_NAMES, so a confined command cannot rewrite it.
SPILL_DIRECTORY = ".cosci/output"

# How much of one stream reaches the model inline. Large enough for a
# real traceback or test run, small enough that a chatty command does not
# consume the context the reasoning needs.
DEFAULT_PREVIEW_CHARS = 16_000

# Environment variables whose values are registered as secrets by
# default. Substring matching on the *name*, because the point is to
# catch the variable nobody remembered to name here.
_SECRET_NAME_PATTERN = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE
)


class SecretRegistrationError(ValueError):
    """A value this module will not claim to be able to mask."""


class SecretRegistry:
    """Values that must never appear in output the model or a store sees."""

    def __init__(self) -> None:
        """Creates an empty registry."""
        # Keyed by value: two names for one value must both be masked,
        # and the first registration wins the label.
        self._names_by_value: dict[str, str] = {}

    def register(self, name: str, value: str) -> None:
        """Records one secret.

        Args:
            name: Label to show in place of the value.
            value: The secret itself.

        Raises:
            SecretRegistrationError: If the value is too short to mask
                without corrupting unrelated output.
        """
        if len(value) < MIN_SECRET_LENGTH:
            raise SecretRegistrationError(
                f"refusing to register {name!r}: a value shorter than "
                f"{MIN_SECRET_LENGTH} characters cannot be masked without "
                "corrupting output that merely contains it"
            )
        self._names_by_value.setdefault(value, name)

    def register_environment(
        self, environ: dict[str, str] | None = None
    ) -> tuple[str, ...]:
        """Registers every environment value that looks like a credential.

        Args:
            environ: Environment to scan; defaults to the process's own.

        Returns:
            The names registered. Values too short to mask are skipped
            with a warning rather than raising -- one odd variable must
            not stop the rest from being protected.
        """
        source = os.environ if environ is None else environ
        registered = []
        for name, value in source.items():
            if not value or not _SECRET_NAME_PATTERN.search(name):
                continue
            try:
                self.register(name, value)
            except SecretRegistrationError as exc:
                logger.warning("%s", exc)
                continue
            registered.append(name)
        return tuple(registered)

    def redact(self, text: str) -> str:
        """Replaces every registered value with its label.

        Longest first, so a secret that contains another is masked as
        itself rather than being half-replaced from the inside.
        """
        for value in sorted(self._names_by_value, key=len, reverse=True):
            if value in text:
                text = text.replace(
                    value, f"[redacted:{self._names_by_value[value]}]"
                )
        return text

    def survivors(self, text: str) -> tuple[str, ...]:
        """Returns the names of any registered values still present."""
        return tuple(
            sorted(
                name
                for value, name in self._names_by_value.items()
                if value in text
            )
        )


@dataclass(frozen=True)
class OutputPointer:
    """Where the full text of a spilled stream was written.

    Attributes:
        path: Workspace-relative path, readable with ``read_file``.
        digest: SHA-256 of the redacted text, so a later read can be
            shown to be the same bytes.
        total_chars: Length of the full redacted text.
    """

    path: str
    digest: str
    total_chars: int


@dataclass(frozen=True)
class BoundedOutput:
    """One stream, made safe to show.

    Attributes:
        text: What the reader gets -- the whole stream, a head-and-tail
            preview, or a refusal.
        truncated: Whether ``text`` omits part of the stream.
        pointer: Where the full text was written, when it was.
    """

    text: str
    truncated: bool
    pointer: OutputPointer | None


def _preview(text: str, limit: int) -> str:
    """Builds a head-and-tail preview of an over-long stream.

    Both ends, never just the head: a command's verdict is at the end
    (the traceback, the failure count) and its context is at the start,
    and a head-only truncation reliably discards the half that answers
    the question.
    """
    omitted = len(text) - limit
    head = (limit * 2) // 3
    tail = limit - head
    return (
        f"{text[:head]}\n"
        f"[... {omitted} characters omitted; read the full output with "
        f"read_file ...]\n"
        f"{text[-tail:]}"
    )


class OutputRecorder:
    """Makes a command's output safe to put in front of the model.

    Attributes:
        root: The workspace spilled output is written under.
        secrets: Values to mask.
    """

    def __init__(
        self,
        root: Path,
        secrets: SecretRegistry | None = None,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ) -> None:
        """Binds a recorder to one workspace.

        Args:
            root: The workspace root.
            secrets: Values to mask; an empty registry when omitted.
            preview_chars: Inline budget per stream.
        """
        self.root = root.resolve()
        self.secrets = secrets if secrets is not None else SecretRegistry()
        self._preview_chars = preview_chars

    def record(self, label: str, text: str) -> BoundedOutput:
        """Redacts, bounds, and spills one stream.

        Args:
            label: Names the stream in the spilled filename, e.g.
                "stdout".
            text: The raw captured output.

        Returns:
            What is safe to show, and where the rest went.
        """
        if not text:
            return BoundedOutput(text="", truncated=False, pointer=None)

        redacted = self.secrets.redact(text)
        leaked = self.secrets.survivors(redacted)
        if leaked:
            logger.error(
                "dropping %s: redaction did not remove %s", label, leaked
            )
            return BoundedOutput(
                text=(
                    f"[output withheld: it still contained {', '.join(leaked)}"
                    " after redaction]"
                ),
                truncated=True,
                pointer=None,
            )

        if len(redacted) <= self._preview_chars:
            return BoundedOutput(text=redacted, truncated=False, pointer=None)

        return BoundedOutput(
            text=_preview(redacted, self._preview_chars),
            truncated=True,
            pointer=self._spill(label, redacted),
        )

    def _is_inside_workspace(self, candidate: Path) -> bool:
        """Reports whether a resolved path is under the workspace root."""
        resolved = candidate.resolve()
        return resolved == self.root or self.root in resolved.parents

    def _spill(self, label: str, redacted: str) -> OutputPointer | None:
        """Writes the full redacted text into the workspace.

        Returns None when the write fails: a full disk must cost the
        model the middle of one command's output, not the command.
        """
        digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        relative = f"{SPILL_DIRECTORY}/{label}-{digest[:12]}.txt"
        target = self.root / relative
        if not self._is_inside_workspace(target.parent):
            # A symlink stands where the metadata directory should be.
            # This write runs in the host process, outside the sandbox,
            # so following it would put command output in a directory
            # the command chose. Checked before the mkdir, not after:
            # creating the directory and then declining to write into it
            # still lets a confined command make the host create
            # directories wherever it likes. Sessions pre-create the
            # metadata directory so this cannot arise; this is the
            # backstop for workspaces made before they did.
            logger.error(
                "refusing to spill %s: %s resolves outside the workspace",
                label,
                relative,
            )
            return None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(redacted, encoding="utf-8")
        except OSError as exc:
            logger.warning("could not spill %s output: %s", label, exc)
            return None
        return OutputPointer(
            path=relative, digest=digest, total_chars=len(redacted)
        )
