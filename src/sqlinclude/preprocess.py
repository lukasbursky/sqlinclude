"""Core @include / @define expansion.

This module is pure with respect to *policy*: it walks a source tree, records
variables and include relationships, and emits expanded SQL. It never decides
which editor to launch or how to reach a terminal -- that lives in
:mod:`sqlinclude.editor`.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable, Iterable

INCLUDE_RE = re.compile(r'^\s*@include\s+(?:"([^"]+)"|(\S+))')
DEFINE_RE = re.compile(r"^\s*@define\s+([A-Za-z_][A-Za-z0-9_]*)\s*=?\s*(.*?)\s*$")
VAR_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
STDIN_NAME = "<stdin>"

ORIGIN_UNDEFINED = "undefined"
ORIGIN_CLI = "--vars"


def _slashed(path: str) -> str:
    """Normalize path separators for emitted markers/tree names.

    Keeps output identical across platforms (and friendly to downstream
    parsers that dislike backslashes in ``#line`` markers).
    """
    return path.replace("\\", "/")


def walk(
    source: str,
    cur: str | None,
    out: list[str] | None,
    stack: list[tuple[str, str]],
    no_markers: bool,
    env: dict[str, str],
    blocked: set[str],
    on_var: Callable[[str, str | None, str, int], None] | None = None,
    on_define: Callable[[str, str, int], None] | None = None,
    tree: dict | None = None,
) -> bool:
    """Process directives in ``source``.

    Appends expansion to ``out`` (or only collects via callbacks when ``out``
    is ``None``); ``tree``, when given, records include relationships as
    ``{"name", "children"}`` nodes. Returns ``True`` on error.
    """
    cwd = os.getcwd()
    cur_disp = _slashed(os.path.relpath(os.path.realpath(cur), cwd)) if cur else STDIN_NAME
    line_no = 0
    for raw in source.splitlines(keepends=True):
        line_no += 1
        m = INCLUDE_RE.match(raw)
        if m:
            inc = m.group(1) or m.group(2)
            base = os.path.dirname(cur) if cur else cwd
            path = os.path.normpath(os.path.join(base, inc))
            canon = os.path.realpath(path)
            stack_canons = [c for c, _ in stack]

            if not os.path.isfile(canon):
                sys.stderr.write(f"sqlinclude: {path}: no such file\n")
                return True
            if canon in stack_canons:
                chain = " -> ".join(stack_canons + [canon])
                sys.stderr.write(f"sqlinclude: include cycle: {chain}\n")
                return True

            try:
                with open(canon, encoding="utf-8") as fh:
                    sub = fh.read()
            except OSError as exc:
                sys.stderr.write(f"sqlinclude: {path}: {exc}\n")
                return True
            if sub and not sub.endswith("\n"):
                sub += "\n"

            disp = _slashed(os.path.relpath(canon, cwd))
            if out is not None and not no_markers:
                out.append(f'-- #line 1 "{disp}"\n')
            subtree = None
            if tree is not None:
                subtree = {"name": disp, "children": []}
                tree["children"].append(subtree)
            stack.append((canon, disp))
            if walk(
                sub, path, out, stack, no_markers, env, blocked, on_var, on_define, subtree
            ):
                return True
            stack.pop()
            if out is not None and not no_markers:
                parent = stack[-1][1] if stack else cur_disp
                out.append(f'-- #line {line_no + 1} "{parent}"\n')
            continue

        m = DEFINE_RE.match(raw)
        if m:
            name, value = m.group(1), m.group(2)
            if name not in blocked and name not in env:
                env[name] = value
                if on_define is not None:
                    on_define(name, cur_disp, line_no)
            continue

        if on_var is not None:
            for name in VAR_RE.findall(raw):
                on_var(name, env.get(name), cur_disp, line_no)
        if out is not None:
            out.append(VAR_RE.sub(lambda mm: env.get(mm.group(1), mm.group(0)), raw))
    return False


def collect_vars(
    source: str, top: str | None, cli_vars: dict[str, str]
) -> tuple[list[str], dict[str, str | None], dict[str, str]] | None:
    """Walk the tree without emitting.

    Returns ``(order, values, sources)`` where ``order`` lists each variable's
    first occurrence, ``values`` its value at that point (``None`` if
    undefined), and ``sources`` its origin (``"--vars"``, ``"file:line"``, or
    ``"undefined"``). Returns ``None`` on error.
    """
    env = dict(cli_vars)
    sources = {name: ORIGIN_CLI for name in cli_vars}
    order: list[str] = []
    values: dict[str, str | None] = {}
    origins: dict[str, str] = {}

    def on_define(name: str, disp: str, line: int) -> None:
        sources[name] = f"{disp}:{line}"

    def on_var(name: str, value: str | None, disp: str, line: int) -> None:
        if name not in values:
            order.append(name)
            values[name] = value
            origins[name] = sources.get(name, ORIGIN_UNDEFINED)

    if walk(source, top, None, [], True, env, set(), on_var, on_define):
        return None
    return order, values, origins


def collect_tree(source: str, top: str | None) -> dict | None:
    """Walk the tree, recording @include relationships.

    Returns the root node ``{"name", "children"}`` or ``None`` on error.
    """
    root = {
        "name": _slashed(os.path.relpath(os.path.realpath(top), os.getcwd()))
        if top
        else STDIN_NAME,
        "children": [],
    }
    if walk(source, top, None, [], True, {}, set(), tree=root):
        return None
    return root


def render_tree(node: dict, ascii_only: bool = False) -> str:
    """Render an include tree as an ASCII/Unicode diagram (one line per file)."""
    lines = [node["name"]]
    children: Iterable[dict] = node["children"]
    for i, child in enumerate(children):
        _render_tree_child(child, "", i == len(children) - 1, lines, ascii_only)
    return "\n".join(lines) + "\n"


def _render_tree_child(
    node: dict, prefix: str, last: bool, lines: list[str], ascii_only: bool
) -> None:
    if ascii_only:
        stem = "`-- " if last else "|-- "
        bar = "|   "
    else:
        stem = "└── " if last else "├── "
        bar = "│   "
    lines.append(prefix + stem + node["name"])
    next_prefix = prefix + ("    " if last else bar)
    children: Iterable[dict] = node["children"]
    for i, child in enumerate(children):
        _render_tree_child(child, next_prefix, i == len(children) - 1, lines, ascii_only)
