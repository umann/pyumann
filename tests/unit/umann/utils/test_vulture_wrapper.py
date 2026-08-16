"""Tests for the in-process Vulture wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from umann.utils.vulture_wrapper import _git_python_files, _render_whitelist_sorted, main

pytestmark = pytest.mark.unit


def _item(line: str) -> Mock:
    item = Mock()
    item.get_whitelist_string.return_value = line
    return item


def test_render_whitelist_sorted_orders_by_filename_and_line():
    items = [
        _item("later  # unused function (b.py:10)"),
        _item("first  # unused import (a.py:2)"),
        _item("third  # unused variable (a.py:8)"),
    ]

    assert _render_whitelist_sorted(items) == (
        "a.py:2: unused import: first\n" "a.py:8: unused variable: third\n" "b.py:10: unused function: later\n"
    )


def test_git_python_files_returns_repo_paths():
    completed = subprocess.CompletedProcess([], 0, stdout="src/a.py\ntests/b.py\n", stderr="")
    with patch("umann.utils.vulture_wrapper.subprocess.run", return_value=completed):
        assert _git_python_files() == ["src/a.py", "tests/b.py"]


def test_main_uses_git_files_when_no_args_and_returns_dead_code(capsys):
    fake_item = _item("fn  # unused function (src/a.py:7)")
    fake_vulture = Mock()
    fake_vulture.get_unused_code.return_value = [fake_item]
    fake_vulture.exit_code = 0

    with patch("umann.utils.vulture_wrapper._git_python_files", return_value=["src/a.py"]):
        with patch(
            "umann.utils.vulture_wrapper.make_config",
            return_value={
                "verbose": False,
                "ignore_names": [],
                "ignore_decorators": [],
                "paths": ["src/a.py"],
                "exclude": [],
                "min_confidence": 0,
                "sort_by_size": False,
                "make_whitelist": True,
            },
        ):
            with patch("umann.utils.vulture_wrapper.Vulture", return_value=fake_vulture):
                assert main([]) == 3

    assert capsys.readouterr().out == "src/a.py:7: unused function: fn\n"
