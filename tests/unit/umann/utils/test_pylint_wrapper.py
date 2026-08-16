"""Tests for the sorted Pylint wrapper."""

import runpy
import subprocess
import sys
from unittest.mock import patch

import pytest

from umann.utils.pylint_wrapper import GCC_MESSAGE_TEMPLATE, main, sort_gcc_output

pytestmark = pytest.mark.unit


def test_sort_gcc_output_uses_numeric_row_order():
    output = (
        "bin/iter_dir_to_csv.py:192:4: C0415: Import outside toplevel (argparse) (import-outside-toplevel)\n"
        "bin/iter_dir_to_csv.py:18:0: W0611: Unused Path imported from pathlib (unused-import)\n"
    )

    assert sort_gcc_output(output) == (
        "bin/iter_dir_to_csv.py:18:0: W0611: Unused Path imported from pathlib (unused-import)\n"
        "bin/iter_dir_to_csv.py:192:4: C0415: Import outside toplevel (argparse) (import-outside-toplevel)\n"
    )


def test_sort_gcc_output_sorts_by_filename_row_and_column():
    output = "b.py:2:4: second\na.py:10:0: tenth\na.py:2:8: later column\na.py:2:3: earlier column\n"

    assert sort_gcc_output(output) == (
        "a.py:2:3: earlier column\na.py:2:8: later column\na.py:10:0: tenth\nb.py:2:4: second\n"
    )


def test_sort_gcc_output_drops_non_diagnostic_output():
    output = "b.py:2:0: warning\n\nYour code has been rated at 9.00/10\n"

    assert sort_gcc_output(output) == "b.py:2:0: warning\n"


def test_sort_gcc_output_removes_module_banners():
    output = (
        "************* Module db.model\n"
        "src/umann/db/model.py:4:0: W0611: Unused import (unused-import)\n"
        "************* Module tests.conftest\n"
        "\nYour code has been rated at 9.00/10\n"
    )

    assert sort_gcc_output(output) == "src/umann/db/model.py:4:0: W0611: Unused import (unused-import)\n"


def test_main_uses_text_reporter_with_gcc_message_template(capsys):
    completed = subprocess.CompletedProcess([], 4, stdout="example.py:2:0: C0000: message (symbol)\n", stderr="")

    with patch("umann.utils.pylint_wrapper.subprocess.run", return_value=completed) as run:
        assert main(["example.py"]) == 4

    command = run.call_args.args[0]
    assert command[0] == sys.executable
    assert command[1:3] == ["-m", "pylint"]
    assert "--score=n" in command
    assert "--reports=n" in command
    assert "--output-format=text" in command
    assert f"--msg-template={GCC_MESSAGE_TEMPLATE}" in command
    assert command[-1] == "example.py"
    assert capsys.readouterr().out == completed.stdout


def test_module_main_exits_with_main_return_code():
    completed = subprocess.CompletedProcess([], 7, stdout="", stderr="")
    saved_module = sys.modules.pop("umann.utils.pylint_wrapper", None)
    try:
        with patch("subprocess.run", return_value=completed):
            with patch.object(sys, "argv", ["pylint_wrapper.py"]):
                with pytest.raises(SystemExit) as exc:
                    runpy.run_module("umann.utils.pylint_wrapper", run_name="__main__")
    finally:
        if saved_module is not None:
            sys.modules["umann.utils.pylint_wrapper"] = saved_module

    assert exc.value.code == 7
