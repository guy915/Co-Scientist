"""The OpenAI schemas for the workspace tools.

Split from ``tools`` for length. Descriptions are the only interface the
model has to these tools, so they carry the constraints the code enforces
-- that ``argv`` is an array and a shell must be asked for by name, that
a patch is located by the context it quotes rather than by line number,
and that the whole patch applies or none of it does. A model told none of
that discovers each rule by being refused.
"""

from typing import Any

from co_scientist.workspace.session import DEFAULT_COMMAND_TIMEOUT_SECONDS

RUN_COMMAND = "run_command"
APPLY_PATCH = "apply_patch"
READ_FILE = "read_file"
WRITE_FILE = "write_file"
LIST_FILES = "list_files"
POLL_COMMAND = "poll_command"

# How long `run_command` waits before handing back a session id instead
# of a result. Short: the point is that a long command keeps running, so
# holding the turn open buys nothing the next poll does not.
DEFAULT_YIELD_SECONDS = 10.0

# Declared once: it is the only argument `run_command` grew, and the
# schema functions are at the length ceiling without it inline.
_YIELD_SECONDS = {
    "type": "number",
    "description": (
        "How long to wait for the command before returning a session to "
        f"poll instead. Capped at {int(DEFAULT_COMMAND_TIMEOUT_SECONDS)} "
        f"seconds; defaults to {int(DEFAULT_YIELD_SECONDS)}."
    ),
}


def run_command_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for the command-execution tool."""
    return {
        "type": "function",
        "function": {
            "name": RUN_COMMAND,
            "description": (
                "Run a command inside the run's isolated workspace. The "
                "command is confined by the operating system: it can read "
                "the filesystem, write only inside the workspace, and "
                "cannot reach the network. No shell is involved unless you "
                "ask for one -- pass "
                '["bash", "-lc", "..."] to use pipes, redirection or '
                "environment assignment. Output is captured and truncated "
                "if very large. A command that has not finished within "
                "yield_seconds is NOT killed and is NOT an error: the "
                "reply comes back with running=true and a session_id, "
                "and you continue it with poll_command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The command and its arguments, already split. "
                            'e.g. ["python3", "analyze.py", "--fast"].'
                        ),
                    },
                    "yield_seconds": _YIELD_SECONDS,
                },
                "required": ["argv"],
            },
        },
    }


def apply_patch_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for the file-editing tool."""
    return {
        "type": "function",
        "function": {
            "name": APPLY_PATCH,
            "description": (
                "Create, modify, delete or move files in the workspace "
                "using a context-anchored patch. Hunks are located by the "
                "surrounding lines you quote, not by line number, so quote "
                "enough context to be unambiguous. The whole patch applies "
                "or nothing does: if any hunk's context does not match, "
                "no file is written and the error names the hunk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": (
                            "The full patch envelope, beginning with "
                            "*** Begin Patch and ending with *** End Patch. "
                            "Inside it every operation starts with one of "
                            "*** Add File: <path>, *** Update File: <path> "
                            "or *** Delete File: <path> -- spelled exactly "
                            "that way, since a near-miss is refused and "
                            "costs a turn. Every content line inside a "
                            "hunk carries a leading +, - or space; an Add "
                            "File body is therefore all + lines. To create "
                            "a whole new file, prefer write_file, which "
                            "takes the text as-is."
                        ),
                    }
                },
                "required": ["patch"],
            },
        },
    }


def read_file_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for the workspace file reader."""
    return {
        "type": "function",
        "function": {
            "name": READ_FILE,
            "description": (
                "Read one file from the workspace as text. Large files are "
                "truncated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": ("Path relative to the workspace root."),
                    }
                },
                "required": ["path"],
            },
        },
    }


def write_file_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for the workspace file writer."""
    return {
        "type": "function",
        "function": {
            "name": WRITE_FILE,
            "description": (
                "Write one whole file into the workspace, creating parent "
                "directories and replacing any existing content. Use this "
                "to create a new file -- a script you are about to run, an "
                "input data file. Prefer apply_patch only when editing "
                "part of a file that already exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace root.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "The file's full text, written verbatim. No "
                            "patch envelope and no line prefixes."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
        },
    }


def list_files_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for the workspace file listing."""
    return {
        "type": "function",
        "function": {
            "name": LIST_FILES,
            "description": (
                "List every file currently in the workspace, relative to "
                "its root."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _poll_properties() -> dict[str, Any]:
    """The arguments a poll takes, as JSON schema."""
    return {
        "session_id": {
            "type": "string",
            "description": "The id run_command returned.",
        },
        "cursor": {
            "type": "object",
            "description": (
                "The cursor from your previous reply. Omit to read the "
                "command's output from the start."
            ),
            "properties": {
                "stdout": {"type": "integer"},
                "stderr": {"type": "integer"},
            },
        },
        "wait_seconds": {
            "type": "number",
            "description": (
                "How long to wait for it to finish before replying. "
                f"Capped at {int(DEFAULT_COMMAND_TIMEOUT_SECONDS)} "
                "seconds; 0 to look and reply immediately."
            ),
        },
        "input": {
            "type": "string",
            "description": (
                "Text to send to the command's stdin. Include a trailing "
                "newline if it reads by line."
            ),
        },
        "kill": {
            "type": "boolean",
            "description": "End the command and its children.",
        },
    }


def poll_command_schema() -> dict[str, Any]:
    """Builds the OpenAI schema for continuing a running command."""
    return {
        "type": "function",
        "function": {
            "name": POLL_COMMAND,
            "description": (
                "Continue a command that run_command left running. "
                "Returns whatever it has written since your last cursor "
                "-- not from the start, so polling a chatty command does "
                "not re-read it -- and its exit code once it finishes. "
                "Use `input` to answer a prompt it is waiting on, and "
                "`kill` to end it."
            ),
            "parameters": {
                "type": "object",
                "properties": _poll_properties(),
                "required": ["session_id"],
            },
        },
    }
