from __future__ import annotations

from sqlinclude.editor import parse_buffer, render_buffer
from sqlinclude.preprocess import (
    collect_tree,
    collect_vars,
    render_tree,
    walk,
)

BUFFER = (
    "# hdr\n"
    "# from a.sql:3\n"
    "@define start = '2024-01-01'\n"
    "# from --vars\n"
    "@define end = \n"
    "# undefined\n"
    "@define project = \n"
)


def test_parse_buffer_drops_empty_values():
    assert parse_buffer(BUFFER) == {"start": "'2024-01-01'"}


def test_parse_buffer_keeps_rest_of_line():
    assert parse_buffer("# c\n\n@define a = x\n@define b = y z\n") == {"a": "x", "b": "y z"}


def test_render_buffer_roundtrip():
    order = ["a", "b"]
    values = {"a": "'v'", "b": None}
    origins = {"a": "--vars", "b": "undefined"}
    rendered = render_buffer("analysis.sql", order, values, origins)
    assert "@define a = 'v'" in rendered
    assert "@define b = " in rendered
    assert "# --vars" in rendered and "# undefined" in rendered
    assert parse_buffer(rendered) == {"a": "'v'"}


def test_render_tree_unicode():
    tree = {
        "name": "a.sql",
        "children": [
            {"name": "b.sql", "children": [{"name": "c.sql", "children": []}]},
            {"name": "d.sql", "children": []},
        ],
    }
    expected = "a.sql\n├── b.sql\n│   └── c.sql\n└── d.sql\n"
    assert render_tree(tree) == expected


def test_render_tree_ascii():
    tree = {
        "name": "a.sql",
        "children": [
            {"name": "b.sql", "children": [{"name": "c.sql", "children": []}]},
            {"name": "d.sql", "children": []},
        ],
    }
    expected = "a.sql\n|-- b.sql\n|   `-- c.sql\n`-- d.sql\n"
    assert render_tree(tree, ascii_only=True) == expected


def test_collect_vars_marks_undefined_and_origins(tmp_path, monkeypatch):
    (tmp_path / "a.sql").write_text("@define x = 1\nSELECT @x, @y\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = collect_vars("@include a.sql\nSELECT @x\n", None, {})
    assert result is not None
    order, values, origins = result
    assert order == ["x", "y"]
    assert values == {"x": "1", "y": None}
    assert origins["y"] == "undefined"
    assert origins["x"] == "a.sql:1"


def test_collect_vars_cli_wins():
    result = collect_vars("SELECT @x\n", None, {"x": "cli"})
    assert result is not None
    order, values, origins = result
    assert values["x"] == "cli"
    assert origins["x"] == "--vars"


def test_walk_consumes_defines_and_leaves_undefined_names():
    out: list[str] = []
    env: dict[str, str] = {}
    err = walk(
        "SELECT @keep, @defined\n@define defined = 1\n",
        None,
        out,
        [],
        True,
        env,
        set(),
    )
    assert err is False
    assert "".join(out) == "SELECT @keep, @defined\n"


def test_collect_tree_stdin(tmp_path, monkeypatch):
    (tmp_path / "a.sql").write_text("SELECT 1;\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    tree = collect_tree("@include a.sql\n", None)
    assert tree is not None
    assert tree["name"] == "<stdin>"
    assert tree["children"][0]["name"] == "a.sql"
