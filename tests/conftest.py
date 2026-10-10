from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Callable

import pytest

from sqlinclude import cli

TESTS_DIR = Path(__file__).parent
FIXTURES = TESTS_DIR / "fixtures"
EXPECTED = TESTS_DIR / "expected"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def expected_dir() -> Path:
    return EXPECTED


@pytest.fixture
def run_cli(monkeypatch):
    """Invoke ``cli.main`` in-process with a deterministic stdout encoding.

    Returns ``(returncode, stdout_text, stderr_text)``.
    """

    def _run(
        args: list[str],
        *,
        cwd: Path = FIXTURES,
        stdin_text: str | None = None,
        initial_encoding: str = "utf-8",
        tty: bool = False,
        edit_buffer: Callable[[str, str], str | None] | None = None,
    ):
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(cli, "have_ctrl_tty", lambda: tty)
        if edit_buffer is not None:
            monkeypatch.setattr(cli, "edit_buffer", edit_buffer)

        out_buf = io.BytesIO()
        stdout = io.TextIOWrapper(out_buf, encoding=initial_encoding, newline="")
        stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        if stdin_text is not None:
            monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

        rc = cli.main(["sqlinclude", *args])
        stdout.flush()
        return rc, out_buf.getvalue().decode("utf-8"), stderr.getvalue()

    return _run
