"""Unit tests for SQL utility functions."""

# pylint: disable=protected-access

import runpy

import pytest

from umann.utils import sql_utils as su

pytestmark = pytest.mark.unit


def test_remove_sql_comments_and_backtick_helpers():
    assert su.substitute_parameters_in_sql("SELECT ?", (42,)) == "SELECT 42"
    assert su.substitute_parameters_in_sql("SELECT ? + ?", (42,)) == "SELECT 42 + ?"
    assert su.substitute_parameters_in_sql("SELECT ?", (42, 99)) == "SELECT 42"
    assert su.substitute_parameters_in_sql("SELECT ?", 42) == "SELECT ?\n-- Parameters: 42"

    assert su.remove_sql_comments(["SELECT 1 -- comment"]) == ["SELECT 1"]
    assert su.backtick("column1") == "`column1`"
    assert su.backtick(["column1", "column2"]) == "`column1`, `column2`"


def test_placeholder_and_values_and_statement_helpers():
    assert su.placeholder_and_values({"a": 1}, action="insert") == ("?", (1,))
    assert su.placeholder_and_values({"a": 1}, action="update") == ("`a`=?", (1,))
    assert su.placeholder_and_values({"a": 1, "b": 2}) == ("`a`=? AND `b`=?", (1, 2))

    assert su._statement_table_name("CREATE_TABLE", "tbl", "CREATE TABLE tbl (id INTEGER)") == "tbl"
    assert su._statement_table_name("CREATE_INDEX", "ix", "CREATE INDEX ix ON tbl (id)") == "tbl"
    assert su._statement_table_name("CREATE_TRIGGER", "tr", "CREATE TRIGGER tr AFTER INSERT ON tbl BEGIN END") == "tbl"
    assert su._statement_table_name("INSERT", None, "INSERT INTO tbl (id) VALUES (1)") == "tbl"
    assert su._statement_dependencies("CREATE TABLE", "tbl", "CREATE TABLE tbl (x REFERENCES other(id))") == {"other"}
    assert su._statement_dependencies("INSERT", "tbl", "INSERT INTO tbl VALUES (1)") == set()


def test_collect_sort_prepare_and_keywords():
    statements, deps = su._collect_sql_statements(["", "CREATE TABLE a (id INTEGER PRIMARY KEY)", "DROP TABLE x"])
    assert statements[0]["type"] == "CREATE_TABLE"
    assert "a" in deps
    assert statements[1]["type"] == "UNKNOWN"

    assert su._build_table_order({"a": {"b"}, "b": set()}) == {"b": 0, "a": 1}
    assert su._build_table_order({"a": {"b"}}) == {"b": 0, "a": 1}
    assert su._statement_sort_key({"type": "INSERT", "table": "a", "name": None}, {"a": 1})[:2] == (2, 0)
    assert su._statement_sort_key({"type": "CREATE_TABLE", "table": "a", "name": "a"}, {"a": 7})[1] == 7

    assert su._prepare_sql_commands("SELECT 1", None) == ["SELECT 1"]
    assert su._prepare_sql_commands(["SELECT 1"], None) == ["SELECT 1"]
    assert "SELECT" in su.sqlite_keywords()

    with pytest.raises(TypeError):
        su.sql_format("SELECT 1", unexpected=True)


def test_sql_format_and_split_helpers():
    assert su.split_sql_statements("SELECT 1; SELECT 2;") == ["SELECT 1;", "SELECT 2;"]
    assert (
        su.sql_format("SELECT `from` FROM t", options={"remove_backticks": True, "sort": False})
        == "SELECT `from` FROM t"
    )
    assert su._format_sql_command("", keep_comments=False, flatten=True, remove_backticks=True) is None

    def boom(*_args, **_kwargs):
        raise su.SQLParseError("boom")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(su.sqlparse, "format", boom)
        assert su.remove_sql_comments("SELECT 1 -- comment") == "SELECT 1"


def test_glob_to_where_and_main_execution(monkeypatch, capsys):
    where, binds = su.glob_to_where(["/mnt/f/photos/20[01]?/*.jpg", "/mnt/d/scan/"])
    assert "ext.ext" in where
    assert binds == ("/mnt/f", "/photos/20[01]?/", ".jpg", "/mnt/d", "/scan/")

    with pytest.raises(ValueError):
        su.glob_to_where([""])

    monkeypatch.setattr(su.sys, "argv", ["sql_utils.py", "/mnt/f/photos/20[01]?/*"])
    runpy.run_module("umann.utils.sql_utils", run_name="__main__")
    out = capsys.readouterr().out
    assert "vol.unx" in out
