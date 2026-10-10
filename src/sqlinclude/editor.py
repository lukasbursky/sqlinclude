"""Cross-platform terminal + editor helpers.

The interactive undefined-variable flow needs to reach the user's controlling
terminal even when stdout is piped (e.g. ``sqlinclude x.sql | bq query``). On
POSIX that is ``/dev/tty``; on Windows the console is reached through the
``CONIN$`` / ``CONOUT$`` device names. This module hides that difference.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
import tempfile
from typing import Iterator

from .preprocess import (
    ORIGIN_UNDEFINED,
    DEFINE_RE,
    render_tree,
)

IS_WINDOWS = os.name == "nt"


def render_buffer(
    top_disp: str,
    order: list[str],
    values: dict[str, str | None],
    origins: dict[str, str],
    tree: dict | None = None,
) -> str:
    lines = [
        f"# sqlinclude variables -- {top_disp}",
        "# Edit values below. Delete a line to leave that variable undefined",
        "# (it passes through as @name). Blank lines and # comments are ignored.",
        "#",
    ]
    if tree is not None:
        lines.append("# include tree:")
        lines.extend(f"# {ln}" for ln in render_tree(tree).splitlines())
        lines.append("#")
    for name in order:
        origin = origins.get(name, ORIGIN_UNDEFINED)
        lines.append(f"# {origin}")
        lines.append(f"@define {name} = {values.get(name) or ''}")
    return "\n".join(lines) + "\n"


def parse_buffer(text: str) -> dict[str, str]:
    """Read an edited buffer; empty values mean 'undefined'. Returns env dict."""
    env: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = DEFINE_RE.match(s)
        if m:
            name, value = m.group(1), m.group(2)
            if value:
                env[name] = value
    return env


def resolve_editor() -> str:
    """Honor $VISUAL / $EDITOR; fall back to a platform-appropriate editor."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return editor
    return "notepad" if IS_WINDOWS else "vim"


def split_editor(editor: str) -> list[str]:
    """Split an editor command into argv.

    POSIX shell rules apply off Windows; on Windows backslashes in paths must
    survive, so we use ``shlex.split(..., posix=False)`` and strip the quotes
    it leaves behind.
    """
    if not IS_WINDOWS:
        return shlex.split(editor)
    parts = shlex.split(editor, posix=False)
    return [
        p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts
    ]


def have_ctrl_tty() -> bool:
    """True if a controlling terminal can be opened."""
    if IS_WINDOWS:
        try:
            with open("CONIN$", "rb"):
                return True
        except OSError:
            return False
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


@contextlib.contextmanager
def _console_streams() -> Iterator[tuple | None]:
    """Yield ``(stdin, stdout, stderr)`` attached to the controlling console.

    Yields ``None`` when no console is available. On Windows the input and
    output devices are distinct objects; on POSIX the same tty fd serves all
    three streams.
    """
    if IS_WINDOWS:
        try:
            stdin = open("CONIN$", "rb")
            stdout = open("CONOUT$", "wb")
            stderr = open("CONOUT$", "wb")
        except OSError:
            yield None
            return
        try:
            yield (stdin, stdout, stderr)
        finally:
            for handle in (stdin, stdout, stderr):
                with contextlib.suppress(OSError):
                    handle.close()
    else:
        try:
            fd = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            yield None
            return
        try:
            yield (fd, fd, fd)
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)


def undefined_count(order: list[str], values: dict[str, str | None]) -> int:
    return sum(1 for n in order if values[n] is None)


def edit_buffer(text: str, editor: str) -> str | None:
    """Open ``editor`` on a temp file holding ``text``; return edited contents.

    Returns ``None`` if the editor exits non-zero.
    """
    fd, tmp = tempfile.mkstemp(prefix="sqlinclude-", suffix=".sql")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        with _console_streams() as streams:
            if IS_WINDOWS:
                # Editors such as VS Code resolve to ``code.cmd``; those need
                # the command interpreter, so pass a command line and shell=True.
                cmdline = editor + " " + subprocess.list2cmdline([tmp])
                if streams is not None:
                    rc = subprocess.call(
                        cmdline, shell=True, stdin=streams[0], stdout=streams[1], stderr=streams[2]
                    )
                else:
                    rc = subprocess.call(cmdline, shell=True)
            else:
                cmd = split_editor(editor) + [tmp]
                if streams is not None:
                    rc = subprocess.call(
                        cmd, stdin=streams[0], stdout=streams[1], stderr=streams[2]
                    )
                else:
                    rc = subprocess.call(cmd)
        if rc != 0:
            sys.stderr.write(f"sqlinclude: editor exited with status {rc}\n")
            return None
        with open(tmp, encoding="utf-8") as fh:
            return fh.read()
    finally:
        os.unlink(tmp)
