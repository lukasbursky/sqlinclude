from __future__ import annotations

import os
import shlex
import sys

import pytest

from sqlinclude import editor


def test_resolve_editor_prefers_visual(monkeypatch):
    monkeypatch.setenv("VISUAL", "myvis")
    monkeypatch.setenv("EDITOR", "myed")
    assert editor.resolve_editor() == "myvis"


def test_resolve_editor_prefers_editor(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "myed")
    assert editor.resolve_editor() == "myed"


def test_resolve_editor_fallback(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    assert editor.resolve_editor() == ("notepad" if os.name == "nt" else "vim")


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell quoting")
def test_split_editor_posix():
    assert editor.split_editor("code --wait") == ["code", "--wait"]


def _python_command(code: str) -> str:
    if os.name == "nt":
        return f'"{sys.executable}" -c "{code}"'
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _script_editor(script_path) -> str:
    if os.name == "nt":
        return f'"{sys.executable}" "{script_path}"'
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"


def test_edit_buffer_roundtrip(tmp_path):
    script = tmp_path / "fake_editor.py"
    script.write_text(
        "import sys\n"
        "with open(sys.argv[1], 'w', encoding='utf-8') as fh:\n"
        "    fh.write('CHANGED\\n')\n",
        encoding="utf-8",
    )
    assert editor.edit_buffer("original\n", _script_editor(script)) == "CHANGED\n"


def test_edit_buffer_nonzero_exit_returns_none(tmp_path):
    assert editor.edit_buffer("x\n", _python_command("import sys; sys.exit(3)")) is None
