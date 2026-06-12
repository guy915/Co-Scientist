# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Adds the Apache 2.0 license header to source files that lack one."""

import sys
from pathlib import Path

HEADER_LINES = [
    "Copyright 2026 The Co-Scientist Authors",
    "",
    'Licensed under the Apache License, Version 2.0 (the "License");',
    "you may not use this file except in compliance with the License.",
    "You may obtain a copy of the License at",
    "",
    "    http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    'distributed under the License is distributed on an "AS IS" BASIS,',
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "See the License for the specific language governing permissions and",
    "limitations under the License.",
]

PY_HEADER = "\n".join(f"# {l}".rstrip() for l in HEADER_LINES) + "\n\n"
TS_HEADER = ("/**\n" + "\n".join(f" * {l}".rstrip() for l in HEADER_LINES) +
             "\n */\n\n")


def add_header(path: Path) -> bool:
    """Prepends the license header to one file.

    Args:
        path: The source file to update.

    Returns:
        True if the file was modified, False if it already had a header.
    """
    text = path.read_text()
    if "Licensed under the Apache License" in text[:1024]:
        return False
    if path.suffix == ".py":
        if text.startswith("#!"):
            shebang, _, rest = text.partition("\n")
            path.write_text(shebang + "\n" + PY_HEADER + rest)
        else:
            path.write_text(PY_HEADER + text)
    else:
        path.write_text(TS_HEADER + text)
    return True


def main() -> None:
    """Walks the directories given on argv and adds missing headers."""
    changed = 0
    for root in sys.argv[1:]:
        for pattern in ("*.py", "*.ts", "*.tsx"):
            for path in sorted(Path(root).rglob(pattern)):
                if add_header(path):
                    changed += 1
                    print(f"added: {path}")
    print(f"{changed} files updated")


if __name__ == "__main__":
    main()
