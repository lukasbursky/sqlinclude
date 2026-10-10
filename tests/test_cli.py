from __future__ import annotations


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def test_main_expands_includes(run_cli, expected_dir):
    rc, out, err = run_cli(["ok_main.sql"])
    assert rc == 0
    assert out == read(expected_dir / "main.sql")
    assert err == ""


def test_no_markers(run_cli, expected_dir):
    rc, out, _ = run_cli(["-n", "ok_nomarkers.sql"])
    assert rc == 0
    assert out == read(expected_dir / "nomarkers.sql")


def test_stdin(run_cli, fixtures_dir, expected_dir):
    rc, out, _ = run_cli([], stdin_text=read(fixtures_dir / "ok_main.sql"))
    assert rc == 0
    assert out == read(expected_dir / "stdin.sql")


def test_vars_beats_file_define(run_cli, expected_dir):
    rc, out, _ = run_cli(["--vars", "start='cli'", "ok_vars_cli.sql"])
    assert rc == 0
    assert out == read(expected_dir / "vars_cli.sql")


def test_override(run_cli, expected_dir):
    rc, out, _ = run_cli(["ok_override.sql"])
    assert rc == 0
    assert out == read(expected_dir / "override.sql")


def test_include_leak(run_cli, expected_dir):
    rc, out, _ = run_cli(["ok_leak.sql"])
    assert rc == 0
    assert out == read(expected_dir / "leak.sql")


def test_undefined_var_passthrough_without_tty(run_cli, expected_dir):
    rc, out, err = run_cli(["ok_vars.sql"], tty=False)
    assert rc == 0
    assert out == read(expected_dir / "vars.sql")
    assert "undefined variables (1): @region -- left as @name" in err


def test_tree_unicode(run_cli, expected_dir):
    rc, out, _ = run_cli(["--tree", "ok_main.sql"])
    assert rc == 0
    assert out == read(expected_dir / "tree_main.txt")


def test_tree_stdin(run_cli, fixtures_dir, expected_dir):
    rc, out, _ = run_cli(["--tree"], stdin_text=read(fixtures_dir / "ok_main.sql"))
    assert rc == 0
    assert out == read(expected_dir / "tree_stdin.txt")


def test_tree_no_includes(run_cli, expected_dir):
    rc, out, _ = run_cli(["--tree", "orders.sql"])
    assert rc == 0
    assert out == read(expected_dir / "tree_orders.txt")


def test_tree_unicode_survives_narrow_stdout(run_cli, expected_dir):
    # A cp1252 stdout cannot encode the box-drawing glyphs; forcing UTF-8 must
    # keep the Unicode tree intact instead of crashing or degrading to ASCII.
    rc, out, _ = run_cli(["--tree", "ok_main.sql"], initial_encoding="cp1252")
    assert rc == 0
    assert out == read(expected_dir / "tree_main.txt")


def test_tree_explicit_ascii(run_cli):
    rc, out, _ = run_cli(["--tree", "--ascii", "orders.sql"])
    assert rc == 0
    assert out == "orders.sql\n"


def test_missing_include_errors(run_cli):
    rc, out, err = run_cli(["err_missing.sql"])
    assert rc == 1
    assert out == ""
    assert "no such file" in err


def test_cycle_errors(run_cli):
    rc, _, err = run_cli(["err_cycle_a.sql"])
    assert rc == 1
    assert "include cycle" in err


def test_bad_vars_arg(run_cli):
    rc, _, err = run_cli(["--vars", "novalue", "ok_main.sql"])
    assert rc == 2
    assert "--vars expects name=value" in err


def test_edit_buffer_result_used(run_cli, expected_dir):
    def fake_edit(text, editor):
        return text.replace("'2024-01-01'", "'2024-06-01'")

    rc, out, err = run_cli(["ok_edit.sql"], tty=True, edit_buffer=fake_edit)
    assert rc == 0
    assert out == read(expected_dir / "edit.sql")
    assert "opening" in err


def test_no_edit_skips_editor(run_cli, expected_dir):
    def boom(text, editor):
        raise AssertionError("editor must not be opened with --no-edit")

    rc, out, err = run_cli(["ok_edit.sql", "--no-edit"], tty=True, edit_buffer=boom)
    assert rc == 0
    assert out == read(expected_dir / "noedit.sql")
    assert err == ""


def test_non_ascii_passthrough_survives_narrow_stdout(tmp_path, run_cli):
    (tmp_path / "q.sql").write_text("select '▲' as arrow;\n", encoding="utf-8")
    rc, out, _ = run_cli(["q.sql"], cwd=tmp_path, initial_encoding="cp1250")
    assert rc == 0
    assert out == "select '▲' as arrow;\n"


def test_bom_stripped(tmp_path, run_cli):
    (tmp_path / "bom.sql").write_text("select 1;\n", encoding="utf-8-sig")
    rc, out, _ = run_cli(["bom.sql"], cwd=tmp_path)
    assert rc == 0
    assert "\ufeff" not in out
    assert out == "select 1;\n"


def test_non_ascii_passthrough_subprocess(tmp_path):
    # Reproduces the Windows failure: a piped stdout whose encoding is the ANSI
    # code page cannot encode the ▲ literal in the source.
    import os
    import subprocess
    import sys

    src = tmp_path / "q.sql"
    src.write_text("select '▲' as arrow;\n", encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1250"}
    proc = subprocess.run(
        [sys.executable, "-m", "sqlinclude", str(src)],
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode("utf-8") == "select '▲' as arrow;\n"

