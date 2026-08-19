"""What a program *is*, as numbers the archive can niche it by.

The archive's whole value is that it keeps the best of each kind, so it
is only as good as its notion of "kind". Size and the operator that
produced a variant are free and better than nothing, but they cannot
tell a tight vectorised routine from a deeply nested loop of the same
length -- and those are exactly the two approaches a search should keep
apart. So this module measures shape as well as size.

Structure proper -- which algorithm a program uses, as opposed to how
big it is -- lives in `fingerprint`, and is folded in here. Everything
else is deliberately cheap and language-tolerant. A discovery
run's program is usually Python, so the AST is used when it parses, but
every feature has a text-based fallback: a run whose program is Rust
still gets nesting depth, branch density and import structure, just
measured more crudely. A feature that cannot be computed is absent
rather than zero -- zero is a real depth, and defaulting to it would put
unparseable programs in the same cell as flat ones.
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Mapping
from typing import Any

from co_scientist.agents.code_evolve import fingerprint

logger = logging.getLogger(__name__)

# Feature names. `operator` and `imports` are categorical; the rest are
# numeric. `metric:<key>` reads anything the program itself reported.
OPERATOR = "operator"
SOURCE_BYTES = "source_bytes"
SOURCE_LINES = "source_lines"
MAX_DEPTH = "max_depth"
BRANCH_COUNT = "branch_count"
CALL_DIVERSITY = "call_diversity"
IMPORTS = "imports"
RECURSION = "recursion"
AST_SHAPE = "ast_shape"
METRIC_PREFIX = "metric:"

CATEGORICAL_FEATURES = frozenset({OPERATOR, IMPORTS, RECURSION})

# Features whose value is a vector rather than one number. They carry
# more than an axis can bin, so only a strategy that clusters the whole
# behaviour vector can use them -- see `grid`.
VECTOR_FEATURES = frozenset({AST_SHAPE})

# Control-flow keywords counted as branching, across the languages a
# discovery run is plausibly written in. Matched on word boundaries, so
# an identifier containing "if" is not a branch.
_BRANCH_PATTERN = re.compile(
    r"\b(if|elif|else|for|while|case|switch|match|try|catch|except)\b"
)

# Callee-shaped tokens: an identifier immediately followed by "(".
_CALL_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# Top-level module names, across Python, JS/TS and C-family syntax.
_IMPORT_PATTERNS = (
    re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.M),
    re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\b", re.M),
    re.compile(r"""require\(\s*['"]([^'"]+)['"]"""),
    re.compile(r"""from\s+['"]([^'"]+)['"]"""),
    re.compile(r"^\s*#include\s*[<\"]([^>\"]+)", re.M),
)

# Ceiling on how many distinct imports name a cell. An unbounded set
# makes every marginally different dependency list its own niche, and a
# grid with one variant per cell has stopped compressing anything.
_MAX_NAMED_IMPORTS = 4


def _joined_source(source: Mapping[str, str]) -> str:
    """Concatenates a program's files in a stable order."""
    return "\n".join(source[path] for path in sorted(source))


def _indent_depth(text: str) -> int:
    """Deepest indentation, in four-space units.

    A proxy for control-flow nesting that needs no parser, so it means
    the same thing for a language this code has never seen. Tabs count
    as one level, which is what they are in every sane style.
    """
    deepest = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        prefix = line[: len(line) - len(line.lstrip())]
        deepest = max(deepest, prefix.count("\t") + prefix.count(" ") // 4)
    return deepest


def _python_depth(text: str) -> int | None:
    """Deepest nesting of block statements, via the AST.

    Returns None when the program is not parseable Python, which is the
    ordinary case for a non-Python run and for a variant mid-repair --
    the caller falls back to indentation rather than treating it as flat.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None

    def walk(node: ast.AST, depth: int) -> int:
        blocks = (
            ast.If,
            ast.For,
            ast.While,
            ast.Try,
            ast.With,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
        deepest = depth
        for child in ast.iter_child_nodes(node):
            step = depth + 1 if isinstance(child, blocks) else depth
            deepest = max(deepest, walk(child, step))
        return deepest

    try:
        return walk(tree, 0)
    except RecursionError:  # pragma: no cover - pathological nesting
        return None


def _imports(text: str) -> str:
    """Names the program's dependencies, as one categorical coordinate.

    This is the axis that separates "rewrote it with numpy" from "tuned
    the pure-Python loop" -- a genuinely different approach that every
    size- and operator-based descriptor reads as the same cell. Only the
    top-level module is kept, the set is sorted so ordering cannot split
    a cell, and it is capped so a long dependency list degrades to a
    count instead of minting a niche nothing else can ever occupy.
    """
    found: set[str] = set()
    for pattern in _IMPORT_PATTERNS:
        found.update(match.split(".")[0] for match in pattern.findall(text))
    named = sorted(found)
    if len(named) > _MAX_NAMED_IMPORTS:
        return f"{len(named)}-deps"
    return ",".join(named) or "none"


def describe(
    source: Mapping[str, str],
    *,
    operator: str | None = None,
    metrics: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Measures every behaviour feature of one variant.

    Args:
        source: The whole program, ``{path: contents}``.
        operator: The move that produced it, or None for the seed.
        metrics: What the program reported, so ``metric:<key>`` axes
            resolve without a second lookup.

    Returns:
        Feature name to value. Numeric features are floats, categorical
        ones strings. Reported metrics are included under ``metric:``.
    """
    text = _joined_source(source)
    ast_depth = _python_depth(text)
    behaviour: dict[str, Any] = {
        RECURSION: fingerprint.recursion(source),
        AST_SHAPE: fingerprint.shape(source),
        OPERATOR: operator or "seed",
        SOURCE_BYTES: float(len(text.encode("utf-8"))),
        SOURCE_LINES: float(text.count("\n") + 1 if text else 0),
        MAX_DEPTH: float(
            ast_depth if ast_depth is not None else _indent_depth(text)
        ),
        BRANCH_COUNT: float(len(_BRANCH_PATTERN.findall(text))),
        CALL_DIVERSITY: float(len(set(_CALL_PATTERN.findall(text)))),
        IMPORTS: _imports(text),
        **fingerprint.densities(source),
    }
    for key, value in (metrics or {}).items():
        behaviour[f"{METRIC_PREFIX}{key}"] = float(value)
    return behaviour


def is_categorical(feature: str) -> bool:
    """Reports whether a feature names a category rather than a quantity."""
    return feature in CATEGORICAL_FEATURES


def is_vector(feature: str) -> bool:
    """Reports whether a feature's value is a vector rather than a scalar."""
    return feature in VECTOR_FEATURES
