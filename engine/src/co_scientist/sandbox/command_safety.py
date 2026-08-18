"""Deciding which commands are read-only enough to run without asking.

This is an *approval* input, never a security boundary. The sandbox is
the boundary; this only decides whether a human is asked first. Confusing
the two is the failure this whole area is prone to -- opencode's
permission prompt is a UX layer and its own SECURITY.md says so, and Pi's
exec classifier is prefix matching with no shell parsing, evaded by
``true && <anything>``, which buys the appearance of a control without
the substance.

So the rule here is that anything not positively understood is unsafe.
That includes constructs this module declines to reason about at all --
redirections, command substitution, backgrounding, subshells -- rather
than constructs it has judged dangerous. A shell feature nobody thought
about lands on the safe side of a matcher and the unsafe side of a
parser, which is why the composite path parses rather than scans.

Ported from OpenAI Codex CLI's `is_safe_command.rs` (Apache-2.0). The
non-obvious parts are the flag exceptions: `find` is not read-only if it
carries `-exec` or `-delete`, and `base64` is not if it carries `-o`.
Note what is deliberately absent: any interpreter. `python`, `node`,
`perl` and friends are read-only only in the sense that a loaded gun is
inert, and an agent that wants to run one can ask.
"""

import logging
import shlex
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

# Commands that only read, with no flag able to make them write.
_ALWAYS_SAFE = frozenset(
    {
        "cat",
        "cd",
        "cut",
        "date",
        "df",
        "du",
        "echo",
        "expr",
        "false",
        "file",
        "grep",
        "head",
        "hostname",
        "id",
        "ls",
        "nl",
        "paste",
        "printenv",
        "pwd",
        "rev",
        "seq",
        "sort",
        "stat",
        "tail",
        "tr",
        "true",
        "uname",
        "uniq",
        "wc",
        "which",
        "whoami",
    }
)

# Commands that are read-only only while certain flags are absent.
_CONDITIONALLY_SAFE: dict[str, frozenset[str]] = {
    # -exec/-execdir/-ok/-okdir run arbitrary commands; -delete removes
    # files; the -f* options write pathnames to a file.
    "find": frozenset(
        {
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
        }
    ),
    # -o/--output writes the decoded bytes somewhere.
    "base64": frozenset({"-o", "--output"}),
}

# Prefixes that also disqualify a conditionally-safe command, catching
# the joined forms (`-oFILE`, `--output=FILE`) a set of exact flags
# would miss.
_CONDITIONAL_PREFIXES: dict[str, tuple[str, ...]] = {
    "base64": ("--output=", "-o"),
}

# Operators that only sequence commands. Anything else -- redirections,
# backgrounding, subshells -- means the script is not parsed here.
_SEQUENCING_OPERATORS = ("&&", "||", ";", "|")

# Characters whose presence means this module will not reason about the
# script. Not a list of dangerous things: a list of things not handled,
# which is the distinction that keeps the default closed.
_UNPARSED_CONSTRUCTS = ("$(", "`", ">", "<", "&", "\n", "$((", "${")

_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})

# Flags under which a shell takes a script string as its next argument.
_SHELL_SCRIPT_FLAGS = frozenset({"-c", "-lc", "-lic", "-ic"})


def _basename(command: str) -> str:
    """Reduces a possibly-pathed executable to its bare name."""
    return PurePosixPath(command).name


def _flags_disqualify(name: str, args: list[str]) -> bool:
    """Reports whether a conditionally-safe command carries a bad flag."""
    unsafe_flags = _CONDITIONALLY_SAFE.get(name, frozenset())
    if any(arg in unsafe_flags for arg in args):
        return True
    prefixes = _CONDITIONAL_PREFIXES.get(name, ())
    return any(
        arg.startswith(prefix) and arg != prefix
        for arg in args
        for prefix in prefixes
    )


def _is_safe_simple_command(argv: list[str]) -> bool:
    """Reports whether one already-split command is read-only."""
    if not argv:
        return False
    name = _basename(argv[0])
    if name in _ALWAYS_SAFE:
        return True
    if name in _CONDITIONALLY_SAFE:
        return not _flags_disqualify(name, argv[1:])
    return False


def _split_on_operators(script: str) -> list[str] | None:
    """Splits a script into segments on sequencing operators.

    Operators are consumed *before* segments are checked for unmodelled
    constructs, because the two overlap: ``&&`` sequences commands while
    a lone ``&`` backgrounds one, and checking first would refuse every
    composite. Order within the operator list matters for the same
    reason -- ``||`` must be split before ``|``.

    Returns:
        The segments, or None when any segment contains a construct this
        module does not parse -- in which case the caller must treat the
        whole script as unsafe rather than guessing.
    """
    segments = [script]
    for operator in _SEQUENCING_OPERATORS:
        expanded: list[str] = []
        for segment in segments:
            expanded.extend(segment.split(operator))
        segments = expanded

    stripped = [segment.strip() for segment in segments if segment.strip()]
    if any(
        token in segment
        for segment in stripped
        for token in _UNPARSED_CONSTRUCTS
    ):
        return None
    return stripped


def _shell_script(argv: list[str]) -> str | None:
    """Extracts the script from a `bash -lc "..."`-shaped invocation."""
    if len(argv) < 3 or _basename(argv[0]) not in _SHELLS:
        return None
    if argv[1] not in _SHELL_SCRIPT_FLAGS:
        return None
    # A shell invocation carrying anything after the script is doing
    # something this module does not model.
    return argv[2] if len(argv) == 3 else None


def _is_safe_shell_invocation(script: str) -> bool:
    """Reports whether every command in a shell script is read-only."""
    segments = _split_on_operators(script)
    if not segments:
        return False
    try:
        parsed = [shlex.split(segment) for segment in segments]
    except ValueError:
        # Unbalanced quoting. Unparseable means unsafe, as everywhere.
        return False
    return all(_is_safe_simple_command(argv) for argv in parsed)


def is_known_safe(argv: list[str]) -> bool:
    """Reports whether a command is read-only enough to skip approval.

    Args:
        argv: The command, already split into arguments.

    Returns:
        True only when every command that would execute is positively
        recognized as read-only. False for everything else, including
        commands that are merely unrecognized and scripts containing a
        construct this module does not parse.
    """
    if not argv:
        return False
    if _is_safe_simple_command(argv):
        return True

    script = _shell_script(argv)
    if script is None:
        return False
    return _is_safe_shell_invocation(script)
