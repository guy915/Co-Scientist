"""A structural fingerprint: what algorithm a program uses, as a vector.

The hand-written features next door measure a program's *surface* --
how long, how deeply nested, what it imports. Those separate a
vectorised rewrite from a tuned loop, and they do not separate a loop
from a recursion from a comprehension, which are three different
algorithms with nearly identical surfaces. This closes that gap without
a model.

The construction is a hashed n-gram profile over the syntax tree. Every
parent-to-child pair of node types is one n-gram; each is hashed into a
small fixed number of buckets and the counts are normalized. Two
programs built the same way land close together whatever they are
named; two built differently land apart even at identical length.

Three properties are deliberate:

**It is scale-invariant.** Buckets hold *fractions* of the program's
n-grams, never counts. A count grows as a variant is refined, and an
axis that grows with refinement measurably degrades the archive -- the
run stops keeping different approaches and starts keeping every
maturity of one. Fractions describe composition, which is what "kind"
means here.

**It is low-dimensional.** Eight buckets, not the thousands a learned
embedding would give. A discovery run evaluates tens of variants, and in
high dimensions the distance between tens of points concentrates until
every variant is equidistant from every other -- clustering on a 1536-
dimensional embedding of forty programs would niche them by nothing at
all, expensively.

**It is deterministic.** A stable checksum, not Python's randomized
`hash`, so a variant's fingerprint is the same in the process that
evaluates it, the process that selects from it, and the test that pins
it.

**Whether a file is Python is decided by its name, not by whether it
parses.** Plain prose parses surprisingly often -- `notes` is a valid
expression, `a,b` is a tuple, `# heading` is an empty module -- so
"try the parser and see" quietly files data and documentation as code
with a structure of their own. The extension is the honest signal.

**It reads a program file by file, never as one blob.** Concatenating
first and parsing once means a single non-Python file -- a README, a
fixture, a config -- makes the whole program unparseable, and every
structural measurement silently falls back to the crude text path. A
program does not become structurally unknowable because someone added a
data file next to it.
"""

from __future__ import annotations

import ast
import itertools
import pathlib
import re
import zlib
from collections.abc import Iterator, Mapping

# How many buckets the n-gram profile is folded into. Small enough that
# tens of variants can be told apart reliably, large enough that
# unrelated structures rarely collide into one coordinate.
SHAPE_BUCKETS = 8

# Node categories that describe how a program computes, collapsed from
# the AST's much finer vocabulary. The collapse is what makes the
# profile robust: renaming a variable or swapping `+` for `-` should not
# move a program to another cell, but replacing a loop with a
# comprehension should.
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_BRANCHES = (ast.If, ast.IfExp, ast.Match, ast.Try)
_COMPREHENSIONS = (
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

# Suffixes read as Python. An extensionless file is included because a
# script often has none; everything else goes down the token path even
# if it happens to parse.
_PYTHON_SUFFIXES = frozenset({".py", ".pyi", ""})

# Fallback tokenizer for a program that is not parseable Python: word
# tokens, operators, and everything else. Coarser than the AST, and the
# same idea -- adjacent token classes as n-grams.
_TOKEN_PATTERN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*|[^\s\w]")


def _bucket(gram: str) -> int:
    """Folds one n-gram into a bucket, stably across processes."""
    return zlib.crc32(gram.encode("utf-8")) % SHAPE_BUCKETS


def _ast_grams(tree: ast.AST) -> Iterator[str]:
    """Yields every parent-to-child node-type pair in the tree."""
    for node in ast.walk(tree):
        parent = type(node).__name__
        for child in ast.iter_child_nodes(node):
            yield f"{parent}>{type(child).__name__}"


def _token_class(token: str) -> str:
    """Buckets one token into a coarse class for the text fallback."""
    if token[0].isdigit():
        return "num"
    if token[0].isalpha() or token[0] == "_":
        return "word"
    return "op"


def _token_grams(text: str) -> Iterator[str]:
    """Yields adjacent token-class pairs, for non-Python programs."""
    classes = [_token_class(t) for t in _TOKEN_PATTERN.findall(text)]
    for first, second in itertools.pairwise(classes):
        yield f"{first}>{second}"


def _profile(grams: Iterator[str]) -> tuple[float, ...]:
    """Normalizes hashed n-grams into a fixed-width composition vector."""
    counts = [0] * SHAPE_BUCKETS
    total = 0
    for gram in grams:
        counts[_bucket(gram)] += 1
        total += 1
    if total == 0:
        return tuple(0.0 for _ in range(SHAPE_BUCKETS))
    return tuple(count / total for count in counts)


def _parsed(path: str, text: str) -> ast.AST | None:
    """Parses one file as Python, or None when it is not Python."""
    if pathlib.PurePosixPath(path).suffix not in _PYTHON_SUFFIXES:
        return None
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _all_grams(source: Mapping[str, str]) -> Iterator[str]:
    """Yields n-grams from every file, each read the best way it can be."""
    for path in sorted(source):
        text = source[path]
        tree = _parsed(path, text)
        yield from _ast_grams(tree) if tree else _token_grams(text)


def shape(source: Mapping[str, str]) -> tuple[float, ...]:
    """Fingerprints a program's structure.

    Args:
        source: The program, ``{path: contents}``.

    Returns:
        ``SHAPE_BUCKETS`` fractions summing to one, or all zeros for an
        empty program. Each file is read via its AST when it parses as
        Python and via token classes otherwise, so a run in another
        language still gets a usable fingerprint -- coarser, but
        comparable to its siblings, which is all niching needs.
    """
    return _profile(_all_grams(source))


def _python_trees(source: Mapping[str, str]) -> list[ast.AST]:
    """Every file that is Python, parsed."""
    return [
        tree
        for path, text in sorted(source.items())
        if (tree := _parsed(path, text)) is not None
    ]


def _count_types(tree: ast.AST, types: tuple[type[ast.AST], ...]) -> int:
    """Counts nodes of the given kinds anywhere in the tree."""
    return sum(1 for node in ast.walk(tree) if isinstance(node, types))


def _is_recursive(tree: ast.AST) -> bool:
    """Reports whether any function in the tree calls itself.

    Direct recursion only. Mutual recursion reads as iterative here,
    which is a known and accepted gap: catching it needs a call graph,
    and the common case a discovery run produces is a function that
    calls its own name.
    """
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, functions):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == node.name
            ):
                return True
    return False


def densities(source: Mapping[str, str]) -> dict[str, float]:
    """Measures how a program spends its syntax, as fractions.

    Fractions rather than counts for the same reason the fingerprint is
    normalized: a count of loops grows as a program grows, so it niches
    by maturity instead of by kind.

    Returns:
        Loop, branch and comprehension share of the syntax tree, summed
        over every file that parses. Empty when none do -- absent rather
        than zero, because zero is a real density and defaulting to it
        would file every unreadable variant beside genuinely loop-free
        code.
    """
    trees = _python_trees(source)
    if not trees:
        return {}
    total = max(1, sum(sum(1 for _ in ast.walk(tree)) for tree in trees))
    counted = {
        "loop_density": _LOOPS,
        "branch_density": _BRANCHES,
        "comprehension_density": _COMPREHENSIONS,
    }
    return {
        name: sum(_count_types(tree, types) for tree in trees) / total
        for name, types in counted.items()
    }


def recursion(source: Mapping[str, str]) -> str:
    """Names a program recursive, iterative, or unreadable.

    Recursive if *any* file recurses; unreadable only when no file
    parses at all, so a Python module beside a data file is still
    classified on its code.
    """
    trees = _python_trees(source)
    if not trees:
        return "unknown"
    return (
        "recursive"
        if any(_is_recursive(tree) for tree in trees)
        else "iterative"
    )
