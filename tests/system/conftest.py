"""System test configuration and fixtures."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace(test_data_dir):
    """Create a temporary workspace with test data for system tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Copy test files to temporary workspace
        for f in test_data_dir.glob("*"):
            if f.is_file():
                shutil.copy2(f, tmp_path)
        yield tmp_path
