"""Command-line interface for sqlinclude."""

from __future__ import annotations

import argparse
import os
import re
import sys

from . import __version__
from .editor import (
    edit_buffer,
    have_ctrl_tty,
    parse_buffer,
    render_buffer,
    resolve_editor,
    undefined_count,
)
from .preprocess import (
    STDIN_NAME,
    collect_tree,
    collect_vars,
    render_tree,
    walk,
)


def _force_utf8(stream) -> None:
    """Make a standard stream use UTF-8, when it supports reconfiguring.

    sqlinclude is a UTF-8-in/UTF-8-out filter; forcing the encoding keeps a
    Windows console, pipe, or file redirect from choking on non-ASCII SQL (the
    ANSI code page cannot encode characters such as the box-drawing glyphs used
    in --tree, or non-ASCII literals in a SQL query). No-op on Linux, where the
    streams are already UTF-8, and on replaced streams that lack
    ``reconfigure``.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (ValueError, OSError, LookupError):
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqlinclude",
        description="Expand @include directives and @define variables in SQL source "
        "(no SQL parsing).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example (analysis.sql):\n"
            "\n"
            "  @define start = '2024-01-01'\n"
            "  @define end = '2024-12-31'\n"
            "\n"
            "  WITH users AS (\n"
            '      @include "users.sql"\n'
            "  ),\n"
            "\n"
            "  orders AS (\n"
            "      @include orders.sql\n"
            "  )\n"
            "\n"
            "  SELECT ... WHERE created BETWEEN @start AND @end\n"
            "\n"
            "run:\n"
            "\n"
            "  sqlinclude analysis.sql | bq query\n"
            "  sqlinclude --vars start='2024-06-01' analysis.sql | bq query\n"
            "  sqlinclude --tree analysis.sql   # show the include tree, not SQL\n"
            "\n"
            "variables:\n"
            "\n"
            "  @define name = value   set a variable in a file (first definition wins)\n"
            "  --vars name=value      set a variable from the command line (repeatable)\n"
            "  @name                  substituted where defined; undefined names pass\n"
            "                         through unchanged (BigQuery @params stay intact)\n"
            "  -e, --edit             open the editor even when nothing is undefined\n"
            "  --no-edit              never open the editor; no stderr notes\n"
            "\n"
            "editing:\n"
            "\n"
            "  When a variable is undefined, sqlinclude opens $VISUAL/$EDITOR (or vim,\n"
            "  notepad on Windows) on the controlling terminal, even if its output is\n"
            "  piped. Edit values; delete a line to leave that variable undefined; blank\n"
            "  and # lines are ignored. With -e/--edit the buffer also shows the @include\n"
            "  tree. Undefined variables are always reported on stderr -- use\n"
            "  --no-edit to silence everything.\n"
        ),
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="-",
        help="SQL file to preprocess (default: read stdin)",
    )
    parser.add_argument(
        "-n",
        "--no-markers",
        action="store_true",
        help="do not emit -- #line markers around includes",
    )
    parser.add_argument(
        "--vars",
        action="append",
        default=[],
        metavar="name=value",
        help="set a variable (repeatable); wins over @define",
    )
    parser.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="open the editor even when no variable is undefined",
    )
    parser.add_argument(
        "--no-edit",
        action="store_true",
        help="never open the editor; leave undefined @names as-is (no stderr notes)",
    )
    parser.add_argument(
        "-t",
        "--tree",
        action="store_true",
        help="print the @include dependency tree as ASCII on stdout instead of expanding SQL",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="use ASCII (not Unicode) box characters in the include tree",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    _force_utf8(sys.stdin)
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    args = build_parser().parse_args(argv[1:])

    cli_vars: dict[str, str] = {}
    for pair in args.vars:
        if "=" not in pair:
            sys.stderr.write(f"sqlinclude: --vars expects name=value, got {pair!r}\n")
            return 2
        name, value = pair.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            sys.stderr.write(f"sqlinclude: invalid variable name in --vars: {name!r}\n")
            return 2
        cli_vars[name] = value

    if args.file == "-":
        source = sys.stdin.read()
        top = None
    else:
        try:
            with open(args.file, encoding="utf-8-sig") as fh:
                source = fh.read()
        except OSError as exc:
            sys.stderr.write(f"sqlinclude: {args.file}: {exc}\n")
            return 1
        top = args.file
    if source and not source.endswith("\n"):
        source += "\n"

    top_disp = (
        os.path.relpath(os.path.realpath(top), os.getcwd()).replace("\\", "/")
        if top
        else STDIN_NAME
    )

    if args.tree:
        root = collect_tree(source, top)
        if root is None:
            return 1
        sys.stdout.write(render_tree(root, ascii_only=args.ascii))
        return 0

    collected = collect_vars(source, top, cli_vars)
    if collected is None:
        return 1
    order, values, sources = collected
    undefined_present = any(values[n] is None for n in order)

    if (
        top is not None
        and not args.no_edit
        and (undefined_present or args.edit)
        and have_ctrl_tty()
    ):
        editor = resolve_editor()
        if undefined_present:
            sys.stderr.write(
                f"sqlinclude: opening {editor} for {undefined_count(order, values)} "
                "undefined variable(s)\n"
            )
        tree = None
        if args.edit:
            tree = collect_tree(source, top)
            if tree is None:
                return 1
        edited = edit_buffer(render_buffer(top_disp, order, values, sources, tree), editor)
        if edited is None:
            return 1
        env = parse_buffer(edited)
        blocked = set(order) - set(env)
    else:
        env = dict(cli_vars)
        blocked = set()
        if not args.no_edit and undefined_present:
            names = [n for n in order if values[n] is None]
            sys.stderr.write(
                "sqlinclude: undefined variables "
                f"({len(names)}): {', '.join('@' + n for n in names)} "
                "-- left as @name\n"
            )

    out: list[str] = []
    stack: list[tuple[str, str]] = []
    if walk(source, top, out, stack, args.no_markers, env, blocked):
        return 1
    sys.stdout.write("".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
