"""Unit tests for filesystem utility functions.

Tests the basic utility functions like project_root path resolution.
"""

import unittest
from pathlib import Path

import pytest

from umann.utils import fs_utils
from umann.utils.fs_utils import md5_file, project_root, urealpath, urelpath, volume_convert

pytestmark = pytest.mark.unit  # Mark all tests in this module as unit tests


class TestFsUtils(unittest.TestCase):
    """Test FS utils functions (unittest style for legacy test)."""

    def test_project_root(self):
        result = Path(project_root())
        assert result == Path(__file__).parent.parent.parent.parent.parent


def test_urealpath_symlink_resolution(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert urealpath(str(link)) == urealpath(str(target))


def test_urealpath_volume_conversion_win(monkeypatch):
    # Force vol_type to simulate Windows without relying on cached os.name
    monkeypatch.setattr(fs_utils, "vol_type", lambda: "win")
    path = "/mnt/c/Users/test/file.txt"
    converted = urealpath(path)
    assert converted.startswith("C:/Users/test/file.txt")


def test_volume_convert_unx(monkeypatch):
    # Directly test volume_convert mapping C:/ -> /mnt/c/ under Unix simulation
    monkeypatch.setattr(fs_utils, "vol_type", lambda: "unx")
    path = "C:/Users/test/file.txt"
    converted = fs_utils.volume_convert(path)
    assert converted == "/mnt/c/Users/test/file.txt"


def test_urelpath_volume_conversion_win(monkeypatch):
    monkeypatch.setattr(fs_utils, "vol_type", lambda: "win")
    path = "/mnt/c/Alpha/Beta"
    rel_converted = urelpath(path)
    # Should return a relative path (no leading slash)
    assert not rel_converted.startswith("/")


def test_volume_convert_win(monkeypatch):
    monkeypatch.setattr(fs_utils, "vol_type", lambda: "win")
    path = "/mnt/c/Alpha/Beta"
    converted = fs_utils.volume_convert(path)
    assert converted == "C:/Alpha/Beta"


# project_root flag tests
def test_project_root_with_file_path():
    result = project_root("config.yaml")
    assert result.endswith("/config.yaml")
    assert Path(result).parent == Path(__file__).parent.parent.parent.parent.parent


def test_project_root_relative():
    result = project_root(relative=True)
    # Should return relative path to repo root from cwd
    assert not result.startswith("/")


def test_project_root_as_module():
    result = project_root("src/umann/config.py", as_module=True)
    # as_module removes 'src.' prefix and converts slashes to dots
    assert result == "umann.config"
    assert "/" not in result
    assert not result.endswith(".py")


def test_project_root_relative_and_as_module():
    result = project_root("src/umann/utils/fs_utils.py", relative=True, as_module=True)
    # as_module converts path to module notation
    assert result == "umann.utils.fs_utils"
    assert not result.startswith("/")
    assert not result.endswith(".py")


# Edge cases and error conditions
def test_volume_convert_backslash_replacement():
    path = r"C:\Users\test\file.txt"
    result = volume_convert(path)
    # Backslashes get replaced with forward slashes
    assert "\\" not in result
    assert "/" in result
    # Volume conversion also applies based on vol_type (currently unx)
    assert "Users/test/file.txt" in result


def test_volume_convert_preserves_non_drive_paths():
    path = "/home/user/file.txt"
    result = volume_convert(path)
    assert result == "/home/user/file.txt"


def test_volume_convert_handles_lowercase_drive(monkeypatch):
    monkeypatch.setattr(fs_utils, "vol_type", lambda: "win")
    path = "/mnt/f/photos/image.jpg"
    result = volume_convert(path)
    assert result == "F:/photos/image.jpg"


def test_md5_file_computes_hash(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"Hello, World!")
    result = md5_file(str(test_file))
    # MD5 of "Hello, World!" is 65a8e27d8879283831b664bd8b7f0ad4
    assert result == "65a8e27d8879283831b664bd8b7f0ad4"
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_md5_file_handles_binary_content(tmp_path):
    test_file = tmp_path / "binary.dat"
    test_file.write_bytes(bytes(range(256)))
    result = md5_file(str(test_file))
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_urealpath_nonexistent_path():
    # urealpath should still process path even if it doesn't exist
    result = urealpath("/nonexistent/path/to/file.txt")
    assert isinstance(result, str)
    assert len(result) > 0
