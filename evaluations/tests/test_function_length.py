"""Repo-wide function-length ceiling, counted in code lines.

The 40-line convention is documented in `CONTRIBUTING.md` and was never
checked, so it drifted exactly the way the file-length ceiling next door
did. The sibling gate's docstring records the lesson: the metrics that
survived were the ones a checker enforced. This one gets a checker too.

**Why the docstring is subtracted, and why that is not a loophole.**
The same style guide that sets this ceiling also *requires* Google-format
docstrings with `Args:` / `Returns:` / `Raises:` sections on first-party
code. Those two rules collide under a raw line count. Measured over this
gate's exact scope at the commit it was written against, 58 functions
exceeded 40 raw lines and only 9 exceeded 40 lines of actual code. The
other 49 were long solely because they documented themselves as
instructed -- a 25-line function carrying a 16-line `Args:`/`Returns:`
block would have "violated" the ceiling. A gate that fires on those has
one of two outcomes, and both are worse code: gutted docstrings, or
cohesive functions fragmented to buy back lines. So the measurement is
the function's total span minus every docstring inside it. Documenting a
function can never push it over the line; only writing more code can.
`test_docstrings_do_not_count_toward_the_ceiling` pins that property,
because if it ever regressed this would silently become a raw-line gate
that penalises compliance with the style guide.

Everything else in the span counts -- blank lines, comments, and
continuation lines included. They are all lines a reader has to move
through, and exempting them would invite reformatting to beat the gate.

**Scope: first-party Python source, deliberately excluding the test
trees.** A long test is a different defect from a long run-path function,
and often not a defect at all. The longest one here
(`app/tests/test_resume.py`, ~59 lines) is 49 lines of arrange seeding
seven store rows, one line of act, and six of assert: linear, branchless,
and readable precisely because the state under assertion is stated in
full. Pushing that setup behind a helper to satisfy a counter would make
the test harder to read, not easier -- the opposite of what the ceiling is
for. Where test setup genuinely repeats, the fix is a shared builder the
suite already reaches for, not a line budget. Test length stays a review
question. TypeScript is out of scope here too: its function lengths are
governed by the frontend ESLint config, alongside the complexity rule.
"""

from __future__ import annotations

import ast
import pathlib

from evaluations.tests._source_tree import ROOT, is_test_file, source_files

MAX_CODE_LINES = 40

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_DOCSTRING_OWNERS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Narrow, per-function exemptions, keyed by (repo-relative path, qualified
# function name) with the justification as the value. This exists so that a
# function which is genuinely cohesive at 40+ code lines -- where every
# available split would hurt readability -- can be admitted by name, in the
# open, with the reasoning attached.
#
# What is deliberately NOT available: a file-wide or repo-wide suppression.
# This campaign removed one -- `app/app/seed.py` carried a module-level ruff
# suppression of E501 and C901 that hid a 248-line function for months. A
# blanket suppression is how a gate stops being a gate: it silences the next
# violation in that file too, including the one nobody meant to allow. An
# entry here must name one function and say why.
_EXEMPTIONS: dict[tuple[str, str], str] = {}


def _docstring_span(node: ast.AST) -> int:
    """Counts the lines occupied by one node's own docstring.

    Args:
        node: A module, class, or function node.

    Returns:
        The docstring's line span, or 0 when the node has no docstring.
    """
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        return 0
    first = body[0]
    if not isinstance(first, ast.Expr):
        return 0
    value = first.value
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        return 0
    return (first.end_lineno or first.lineno) - first.lineno + 1


def _code_lines(node: _FunctionNode) -> int:
    """Measures a function's code lines: its span minus every docstring.

    Decorators sit outside the measured span (`node.lineno` is the `def`
    line), so decorating a function does not count against it. Docstrings
    of nested functions and classes are subtracted too, for the same reason
    the function's own is.

    Args:
        node: The function being measured.

    Returns:
        The function's line count excluding docstring lines.
    """
    span = (node.end_lineno or node.lineno) - node.lineno + 1
    docstrings = sum(
        _docstring_span(inner)
        for inner in ast.walk(node)
        if isinstance(inner, _DOCSTRING_OWNERS)
    )
    return span - docstrings


def _qualified_names(tree: ast.Module) -> dict[int, str]:
    """Maps every function and class node to its dotted qualified name.

    Walks generic node bodies rather than only class/function bodies, so a
    function defined inside an `if` or `try` block is still named and still
    measured.

    Args:
        tree: The parsed module.

    Returns:
        A mapping of node id to qualified name, e.g. `Hypothesis.to_dict`.
    """
    names: dict[int, str] = {}
    pending: list[tuple[ast.AST, str]] = [(tree, "")]
    while pending:
        node, prefix = pending.pop()
        for child in ast.iter_child_nodes(node):
            child_prefix = prefix
            if isinstance(child, _DOCSTRING_OWNERS):
                names[id(child)] = f"{prefix}{child.name}"
                child_prefix = f"{prefix}{child.name}."
            pending.append((child, child_prefix))
    return names


def _offenders(path: pathlib.Path) -> list[tuple[int, int, str]]:
    """Finds the over-ceiling functions in one source file.

    Args:
        path: Repo-relative path of the file to measure.

    Returns:
        A `(code_lines, line_number, qualified_name)` tuple per offender.
    """
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = _qualified_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = names[id(node)]
        if (str(path), name) in _EXEMPTIONS:
            continue
        code_lines = _code_lines(node)
        if code_lines > MAX_CODE_LINES:
            found.append((code_lines, node.lineno, name))
    return found


def test_no_function_exceeds_the_code_line_ceiling() -> None:
    """No first-party source function may exceed MAX_CODE_LINES."""
    files = [path for path in source_files((".py",)) if not is_test_file(path)]
    # A collection bug that finds nothing would make this test vacuous,
    # so pin that the walk still reaches the tree.
    assert len(files) > 300, f"only found {len(files)} python source files"

    oversized = [
        (code_lines, path, line, name)
        for path in files
        for code_lines, line, name in _offenders(path)
    ]
    oversized.sort(reverse=True)
    assert not oversized, "functions over the {} code-line ceiling:\n{}".format(
        MAX_CODE_LINES,
        "\n".join(
            f"  {code_lines:>4} {path}:{line} {name}"
            for code_lines, path, line, name in oversized
        ),
    )


def test_docstrings_do_not_count_toward_the_ceiling() -> None:
    """The measurement subtracts docstring lines, including nested ones."""
    source = "\n".join(
        [
            "def outer():",
            '    """Summary.',
            "",
            "    Args:",
            "        nothing: Padding to make the docstring long.",
            '    """',
            "    def inner():",
            '        """Nested docstring line one.',
            "",
            '        Line three."""',
            "        return 1",
            "",
            "    return inner()",
        ]
    )
    outer = ast.parse(source).body[0]
    assert isinstance(outer, ast.FunctionDef)
    inner = outer.body[1]
    assert isinstance(inner, ast.FunctionDef)

    # 13 raw lines; 5 belong to the outer docstring and 3 to the inner one.
    assert outer.end_lineno == 13
    assert _code_lines(outer) == 5
    assert _code_lines(inner) == 2


def test_exemptions_name_one_function_and_carry_a_reason() -> None:
    """Every exemption is per-function and justified in writing."""
    for (path, name), reason in _EXEMPTIONS.items():
        assert (ROOT / path).is_file(), f"stale exemption path: {path}"
        assert name, f"exemption for {path} names no function"
        assert len(reason) > 40, f"unjustified exemption: {path}:{name}"
