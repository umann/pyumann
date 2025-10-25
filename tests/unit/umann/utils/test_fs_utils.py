"""Unit tests for filesystem utility functions.

Tests the basic utility functions like project_root path resolution.
"""

import unittest
from pathlib import Path

import pytest

from umann.utils.fs_utils import project_root

pytestmark = pytest.mark.unit  # Mark all tests in this module as unit tests


class TestFsUtils(unittest.TestCase):
    """Test FS utils functions"""

    def test_project_root(self):
        """project_root should resolve to the repository root directory."""
        result = Path(project_root())
        assert result == Path(__file__).parent.parent.parent.parent.parent
