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
LIST_FILES = "list_files"


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
                "if very large."
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
                    "timeout_seconds": {
                        "type": "number",
                        "description": (
                            "Wall-clock ceiling for this command. Capped at "
                            f"{int(DEFAULT_COMMAND_TIMEOUT_SECONDS)} seconds."
                        ),
                    },
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
                            "*** Begin Patch and ending with *** End Patch."
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
